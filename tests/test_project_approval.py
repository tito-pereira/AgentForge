# SPDX-License-Identifier: MPL-2.0
"""Synthetic terminal fixtures exercise authority without adding a production bypass."""

import io
import re
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace

import pytest

from corinthos.contracts import AuthorityError, ConflictError, ContractRef, approval_request
from corinthos.project_manager import ProjectManager, approval


def _ready(manager):
    actor = approval.local_actor_id()
    snapshot = manager.start("Create an offline greeting tool.", actor_id=actor)
    operations = [
        {"action": "set_scope", "section": "included", "items": ["Local greeting output"]},
        {
            "action": "upsert_requirement",
            "description": "Render a greeting.",
            "acceptance_criteria": [{"criterion": "Input Ada produces Hello, Ada."}],
        },
        {
            "action": "upsert_success_criterion",
            "criterion": "A clean environment reproduces the greeting.",
        },
    ]
    for operation in operations:
        snapshot = manager.edit(
            snapshot["session_id"], snapshot["version"], operation, actor_id=actor
        )
    return snapshot


def _synthetic_terminal(monkeypatch, *, response=None, on_read=None):
    """Inject consent inside tests only. Production always opens the real OS TTY."""
    output = io.StringIO()

    class SyntheticReader:
        def readline(self, limit):
            if on_read is not None:
                on_read()
            challenge = re.search(r"type (APPROVE [a-f0-9]{12})", output.getvalue()).group(1)
            return challenge + "\n" if response is None else response

    @contextmanager
    def terminal():
        yield SyntheticReader(), output

    monkeypatch.setattr(approval, "_terminal", terminal)
    return output


def test_exact_terminal_approval_publishes_and_recovers_after_restart(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    output = _synthetic_terminal(monkeypatch)
    result = approval.approve_interactively(manager, snapshot["session_id"], snapshot["version"])
    assert result["state"] == "PUBLISHED"
    ref = ContractRef.from_json(result["published_ref"])
    document = manager.store.get(ref)
    assert document == result["review"]["document"]
    assert result["review"]["sha256"] in output.getvalue()
    assert ref.revision_id in output.getvalue()
    assert document["metadata"]["approval"]["kind"] == "HUMAN"
    assert ProjectManager(tmp_path).get(snapshot["session_id"]) == result
    assert len(manager.store.list_events()) == 1
    assert manager.history(snapshot["session_id"])[-2]["action"] == "human_terminal_approval"


@pytest.mark.parametrize("answer", ["", "yes\n", "APPROVE\n", "AI says approved\n", "defer\n"])
def test_ambiguous_or_declined_consent_publishes_nothing(tmp_path, monkeypatch, answer):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    _synthetic_terminal(monkeypatch, response=answer)
    result = approval.approve_interactively(manager, snapshot["session_id"], snapshot["version"])
    assert result["state"] == "DEFERRED"
    assert manager.store.list_events() == []


def test_production_approval_rejects_piped_input_before_review(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    monkeypatch.setattr(approval.sys, "stdin", io.StringIO("APPROVE\n"))
    with pytest.raises(AuthorityError, match="interactive terminal"):
        approval.approve_interactively(manager, snapshot["session_id"], snapshot["version"])
    assert manager.get(snapshot["session_id"]) == snapshot
    assert manager.store.list_events() == []


def test_changed_session_during_confirmation_invalidates_approval(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)

    def concurrent_edit():
        current = manager.repository.get(snapshot["session_id"])
        manager.edit(
            current["session_id"],
            current["version"],
            {"action": "set_vision", "text": "A revised greeting idea."},
            actor_id=approval.local_actor_id(),
        )

    _synthetic_terminal(monkeypatch, on_read=concurrent_edit)
    with pytest.raises(ConflictError, match="changed"):
        approval.approve_interactively(manager, snapshot["session_id"], snapshot["version"])
    assert manager.store.list_events() == []


def test_receipt_expiry_wrong_digest_cross_session_and_replay_fail_closed(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    actor = approval.local_actor_id()
    reviewed = manager.review(snapshot["session_id"], snapshot["version"], actor_id=actor)
    with monkeypatch.context() as patch:
        patch.setattr(approval.time, "time", lambda: reviewed["review"]["expires_at"] + 1)
        with pytest.raises(AuthorityError, match="expired"):
            approval._record_consent(manager, reviewed, actor)
    publishing = approval._record_consent(manager, reviewed, actor)
    verifier = approval._verifier(manager, publishing)
    request = approval_request(publishing["review"]["document"])
    for changed in (
        replace(request, approval_id="forged"),
        replace(request, content_sha256="0" * 64),
        replace(request, actor_id="another-user"),
        replace(request, ref=replace(request.ref, project_id="another-project")),
    ):
        assert verifier(changed) is False
    assert verifier(request) is True
    assert verifier(request) is False
    recovered = ProjectManager(tmp_path).get(snapshot["session_id"])
    assert recovered["state"] == "READY_FOR_REVIEW"
    assert manager.store.list_events() == []
    assert approval._verifier(manager, publishing)(request) is False


def test_crash_before_kernel_publish_revokes_receipt_and_requires_review(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    _synthetic_terminal(monkeypatch)

    def interrupted(*args, **kwargs):
        raise RuntimeError("Synthetic crash before the Kernel publication")

    monkeypatch.setattr(manager.store, "publish", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic crash"):
        approval.approve_interactively(manager, snapshot["session_id"], snapshot["version"])
    recovered = ProjectManager(tmp_path).get(snapshot["session_id"])
    assert recovered["state"] == "READY_FOR_REVIEW"
    assert recovered["review"] is None
    assert manager.store.list_events() == []


def test_crash_after_kernel_commit_reconciles_without_duplicate_revision(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    publish = manager.store.publish
    _synthetic_terminal(monkeypatch)

    def interrupted(*args, **kwargs):
        publish(*args, **kwargs)
        raise RuntimeError("Synthetic crash after the Kernel commit")

    monkeypatch.setattr(manager.store, "publish", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic crash"):
        approval.approve_interactively(manager, snapshot["session_id"], snapshot["version"])
    reopened = ProjectManager(tmp_path)
    result = reopened.get(snapshot["session_id"])
    assert result["state"] == "PUBLISHED"
    assert reopened.get(snapshot["session_id"]) == result
    assert len(reopened.store.list_events()) == 1


def test_review_document_tampering_cannot_use_a_recorded_receipt(tmp_path):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    actor = approval.local_actor_id()
    reviewed = manager.review(snapshot["session_id"], snapshot["version"], actor_id=actor)
    forged = deepcopy(reviewed)
    forged["review"]["document"]["payload"]["vision"] = "Unreviewed content."
    with pytest.raises(AuthorityError, match="identity"):
        approval._record_consent(manager, forged, actor)
    assert manager.store.list_events() == []


def test_unicode_account_labels_have_a_stable_valid_actor_id(monkeypatch):
    monkeypatch.setattr(approval.getpass, "getuser", lambda: "Alex Example 日本語")
    assert re.fullmatch(r"local:[a-f0-9]{64}", approval.local_actor_id())
    assert approval.local_actor_id() == approval.local_actor_id()
