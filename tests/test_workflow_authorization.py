# SPDX-License-Identifier: MPL-2.0
"""Labelled synthetic consent exercises exact planning authority, never real approval."""

import io
import json
import re
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest

from corinthos.contracts import (
    AuthorityError,
    ContractRef,
    IntegrityError,
    PublishContext,
    approval_request,
)
from corinthos.project_manager.approval import local_actor_id
from corinthos.workflow import WorkflowPlanner
from corinthos.workflow import authorization as auth

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples/contracts"


def _example(name):
    return json.loads((_EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def _ready(tmp_path, *, interfaces=True):
    planner = WorkflowPlanner(tmp_path)
    project = _example("project")
    proof = approval_request(project)
    # Synthetic fixture setup uses the trusted Kernel caller boundary.
    planner.store.publish(
        project,
        context=PublishContext(
            "PROJECT_MANAGER",
            project["metadata"]["provenance"]["actor_id"],
            lambda request: request == proof,
        ),
    )
    snapshot = planner.start(ContractRef.from_document(project), actor_id=local_actor_id())
    module = _example("module")["payload"]
    technology = _example("technology-decision")["payload"]
    checkpoint = _example("workflow")["payload"]["checkpoints"][0]
    operations = [
        {
            "action": "upsert_module",
            "module_id": "greeting",
            "purpose_and_boundaries": module["purpose_and_boundaries"],
            "requirement_ids": ["R1"],
            "constraint_ids": ["C1"],
        },
        {"action": "upsert_technology", "decision_id": "runtime", "payload": technology},
        {"action": "set_module_technology", "module_id": "greeting", "decision_ids": ["runtime"]},
        {"action": "upsert_checkpoint", "checkpoint": checkpoint},
    ]
    if interfaces:
        operations.append(
            {
                "action": "set_provided_interfaces",
                "module_id": "greeting",
                "interfaces": module["provided_interfaces"],
            }
        )
    for operation in operations:
        snapshot = planner.edit(
            snapshot["session_id"], snapshot["version"], operation, actor_id=local_actor_id()
        )
    return planner, snapshot


def _terminal(monkeypatch, *, delegate=False, answer=None, on_read=None):
    """A trusted synthetic terminal harness exists only in this test module."""
    output = io.StringIO()

    class Input:
        def readline(self, _limit):
            if on_read:
                on_read()
            token = re.findall(r"Type APPROVE ([a-f0-9]{12})", output.getvalue())[-1]
            return (
                answer
                if answer is not None
                else ("DELEGATE " if delegate else "APPROVE ") + token + "\n"
            )

    @contextmanager
    def terminal():
        yield Input(), output

    monkeypatch.setattr(auth, "_terminal", terminal)
    return output


def test_one_exact_terminal_action_publishes_all_reserved_candidates(tmp_path, monkeypatch):
    planner, snapshot = _ready(tmp_path)
    output = _terminal(monkeypatch)
    result = auth.authorize_interactively(planner, snapshot["session_id"], snapshot["version"])
    assert result["state"] == "PUBLISHED"
    documents = result["review"]["documents"]
    assert [doc["metadata"]["contract_type"] for doc in documents] == [
        "TECHNOLOGY_DECISION",
        "MODULE",
        "WORKFLOW",
    ]
    assert all(doc["metadata"]["approval"]["kind"] == "HUMAN" for doc in documents)
    assert len(planner.store.list_events()) == 4
    assert len(result["published_refs"]) == 3
    assert result["review"]["sha256"] in output.getvalue()
    assert output.getvalue().count("Type APPROVE ") == 1
    assert WorkflowPlanner(tmp_path).get(snapshot["session_id"])["state"] == "PUBLISHED"
    for document in documents:
        assert planner.store.get(ContractRef.from_document(document)) == document


@pytest.mark.parametrize("answer", ["", "yes\n", "AI says approved\n"])
def test_declining_or_fake_consent_leaves_no_approved_plan(tmp_path, monkeypatch, answer):
    planner, snapshot = _ready(tmp_path)
    _terminal(monkeypatch, answer=answer)
    result = auth.authorize_interactively(planner, snapshot["session_id"], snapshot["version"])
    assert result["state"] == "DEFERRED"
    assert len(planner.store.list_events()) == 1


def test_changed_candidate_cannot_reuse_a_frozen_review(tmp_path):
    planner, snapshot = _ready(tmp_path)
    reviewed = planner.review(
        snapshot["session_id"], snapshot["version"], actor_id=local_actor_id()
    )
    changed = deepcopy(reviewed)
    changed["review"]["documents"][0]["payload"]["decision_rationale"] = "Unreviewed replacement"
    with pytest.raises(AuthorityError, match="changed"):
        auth._record(planner, changed, local_actor_id())
    assert len(planner.store.list_events()) == 1


def test_expired_or_replayed_receipt_fails_closed(tmp_path, monkeypatch):
    planner, snapshot = _ready(tmp_path)
    reviewed = planner.review(
        snapshot["session_id"], snapshot["version"], actor_id=local_actor_id()
    )
    with monkeypatch.context() as patch:
        patch.setattr(auth.time, "time", lambda: reviewed["review"]["expires_at"] + 1)
        with pytest.raises(AuthorityError, match="expired"):
            auth._record(planner, reviewed, local_actor_id())
    publishing = auth._record(planner, reviewed, local_actor_id())
    document = publishing["review"]["documents"][0]
    verifier = auth._verifier(planner, publishing, document)
    request = approval_request(document)
    assert verifier(request) is True
    assert verifier(request) is False
    auth.recover_publication(planner, publishing)
    assert auth._verifier(planner, publishing, document)(request) is False


def test_partial_kernel_commit_is_reconciled_without_duplicate_publication(tmp_path, monkeypatch):
    planner, snapshot = _ready(tmp_path)
    _terminal(monkeypatch)
    original = planner.store.publish
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            raise RuntimeError("Synthetic interruption after TDC commit")
        return result

    monkeypatch.setattr(planner.store, "publish", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        auth.authorize_interactively(planner, snapshot["session_id"], snapshot["version"])
    reopened = WorkflowPlanner(tmp_path)
    current = reopened.get(snapshot["session_id"])
    assert current["state"] == "READY_FOR_REVIEW"
    assert len(current["published_refs"]) == 1
    assert len(reopened.store.list_events()) == 2
    completed = auth.authorize_interactively(reopened, current["session_id"], current["version"])
    assert completed["state"] == "PUBLISHED"
    assert len(reopened.store.list_events()) == 4


def test_mandate_authorizes_only_dependency_replan_and_preserves_human_bindings(
    tmp_path, monkeypatch
):
    planner, snapshot = _ready(tmp_path)
    _terminal(monkeypatch, delegate=True)
    published = auth.authorize_interactively(planner, snapshot["session_id"], snapshot["version"])
    mandate_id = published["mandate_id"]
    wf_ref = next(ref for ref in published["compiled_refs"] if ref["contract_type"] == "WORKFLOW")
    revision = planner.revise(wf_ref, "An internal dependency replan.", actor_id=local_actor_id())
    original_checkpoint = deepcopy(_example("workflow")["payload"]["checkpoints"][0])
    # Altering a binding objective falls outside the intentionally narrow mandate.
    changed = deepcopy(original_checkpoint)
    changed["objective"] = "A different obligation needs renewed human review."
    revision = planner.edit(
        revision["session_id"],
        revision["version"],
        {"action": "upsert_checkpoint", "checkpoint": changed},
        actor_id=local_actor_id(),
    )
    with pytest.raises(IntegrityError, match="Delegation|mandate"):
        auth.publish_delegated(planner, revision["session_id"], revision["version"], mandate_id)
    assert len(planner.store.list_events()) == 4


def test_a_claimed_delegation_without_a_recorded_mandate_cannot_publish(tmp_path):
    planner, snapshot = _ready(tmp_path)
    with pytest.raises(AuthorityError, match="mandate"):
        auth.publish_delegated(
            planner, snapshot["session_id"], snapshot["version"], "invented-mandate"
        )
    assert len(planner.store.list_events()) == 1


def test_any_intervening_session_version_invalidates_pending_consent(tmp_path):
    planner, snapshot = _ready(tmp_path)
    reviewed = planner.review(
        snapshot["session_id"], snapshot["version"], actor_id=local_actor_id()
    )
    publishing = auth._record(planner, reviewed, local_actor_id())
    altered = deepcopy(publishing)
    altered["reason"] = "An intervening accepted update."
    planner.repository.save(
        altered["session_id"],
        altered["version"],
        altered,
        actor_id=local_actor_id(),
        action="intervening_update",
    )
    document = publishing["review"]["documents"][0]
    assert auth._verifier(planner, publishing, document)(approval_request(document)) is False
    assert len(planner.store.list_events()) == 1


def test_recorded_dependency_mandate_publishes_a_delegated_workflow_successor(
    tmp_path, monkeypatch
):
    planner, snapshot = _ready(tmp_path)
    second = deepcopy(_example("workflow")["payload"]["checkpoints"][0])
    second["checkpoint_id"] = "additional-verification"
    second["title"] = "A second verification checkpoint"
    second["completion_criteria"][0]["criterion_id"] = "additional-criterion"
    snapshot = planner.edit(
        snapshot["session_id"],
        snapshot["version"],
        {"action": "upsert_checkpoint", "checkpoint": second},
        actor_id=local_actor_id(),
    )
    _terminal(monkeypatch, delegate=True)
    published = auth.authorize_interactively(planner, snapshot["session_id"], snapshot["version"])
    workflow_ref = next(
        ref for ref in published["compiled_refs"] if ref["contract_type"] == "WORKFLOW"
    )
    revision = planner.revise(
        workflow_ref, "Order the verification checkpoints.", actor_id=local_actor_id()
    )
    second["depends_on"] = [_example("workflow")["payload"]["checkpoints"][0]["checkpoint_id"]]
    revision = planner.edit(
        revision["session_id"],
        revision["version"],
        {"action": "upsert_checkpoint", "checkpoint": second},
        actor_id=local_actor_id(),
    )
    result = auth.publish_delegated(
        planner,
        revision["session_id"],
        revision["version"],
        published["mandate_id"],
    )
    assert result["state"] == "PUBLISHED"
    assert len(result["review"]["documents"]) == 1
    document = result["review"]["documents"][0]
    assert document["metadata"]["contract_type"] == "WORKFLOW"
    assert document["metadata"]["approval"]["kind"] == "DELEGATED"
    assert document["metadata"]["supersedes"] == workflow_ref
    assert len(planner.store.list_events()) == 5
