# SPDX-License-Identifier: MPL-2.0
"""Installed-resource initialization and synthetic advisory provenance checks."""

import json
import os

import pytest

from corinthos.adapters.model import AgentResult
from corinthos.bootstrap import adapter_manager, initialize
from corinthos.contracts import ConflictError, IntegrityError
from corinthos.contracts.model import canonical_json
from corinthos.lifecycle.repository import LifecycleRepository
from corinthos.project_manager.advice import advise
from corinthos.project_manager.service import ProjectManager


def test_packaged_initialization_works_outside_checkout_and_preserves_owner_bytes(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "new" / "workspace"
    workspace.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    original = b"# Owner instructions\r\nPreserve these exact bytes.\r\n"
    (workspace / "AGENTS.override.md").write_bytes(original)
    (workspace / "CLAUDE.md").write_bytes(original)
    first = initialize(workspace)
    profile = (workspace / ".corinthos/bootstrap.json").read_bytes()
    codex = (workspace / "AGENTS.override.md").read_bytes()
    claude = (workspace / "CLAUDE.md").read_bytes()
    assert codex == claude and codex.startswith(original)
    assert all(rule.encode() in codex for rule in ("M1", "M2", "M3", "M4", "M5"))
    assert not (workspace / "AGENTS.md").exists()
    assert not (workspace / ".corinthos/state.db").exists()
    assert all(item["changed"] for item in first["instructions"])
    repeated = initialize(workspace)
    assert all(not item["changed"] for item in repeated["instructions"])
    assert (workspace / ".corinthos/bootstrap.json").read_bytes() == profile
    assert adapter_manager(workspace).standard_sha256 == first["standard_sha256"]


def test_permissive_override_cannot_disable_any_commandment(tmp_path):
    policy, schema = tmp_path / "policy.json", tmp_path / "schema.json"
    policy.write_text(json.dumps({"standard_version": "0.1", "commandments": {}}))
    schema.write_text("{}")
    with pytest.raises(IntegrityError, match="mandatory M1-M5"):
        initialize(tmp_path / "workspace", policy_path=policy, schema_path=schema)
    assert not (tmp_path / "workspace/.corinthos/bootstrap.json").exists()


def test_existing_profile_and_modified_managed_instructions_are_preserved(tmp_path):
    initialize(tmp_path)
    profile = tmp_path / ".corinthos/bootstrap.json"
    before = profile.read_bytes()
    policy = tmp_path / "different.json"
    standard = json.loads(before)["standard"]
    standard["commandments"]["M1"]["description"] = "A different explicit description."
    policy.write_text(canonical_json(standard), encoding="utf-8")
    with pytest.raises(ConflictError, match="conflicts"):
        initialize(tmp_path, policy_path=policy)
    assert profile.read_bytes() == before
    target = tmp_path / "AGENTS.md"
    target.write_bytes(target.read_bytes().replace(b"M1", b"XX", 1))
    modified = target.read_bytes()
    with pytest.raises(IntegrityError, match="section changed"):
        initialize(tmp_path)
    assert target.read_bytes() == modified
    assert profile.read_bytes() == before


def test_unsafe_or_corrupt_saved_configuration_is_not_overwritten(tmp_path):
    initialize(tmp_path)
    path = tmp_path / ".corinthos/bootstrap.json"
    path.write_bytes(b"partial private configuration")
    for action in (initialize, adapter_manager):
        with pytest.raises(IntegrityError, match="invalid"):
            action(tmp_path)
        assert path.read_bytes() == b"partial private configuration"
    path.unlink()
    external = tmp_path / "owner.json"
    external.write_bytes(b"preserve owner data")
    os.link(external, path)
    with pytest.raises(IntegrityError, match="ordinary"):
        initialize(tmp_path)
    assert external.read_bytes() == b"preserve owner data"


def test_advice_is_explicit_restart_safe_and_does_not_change_negotiation(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    session = manager.start("A synthetic local idea.", actor_id="synthetic-owner")
    observed = []

    def probe(self, provider, workspace, prompt, **kwargs):
        observed.append((provider, workspace, prompt))
        return AgentResult(
            provider,
            "COMPLETED",
            "synthetic-task",
            "synthetic-attempt",
            output="Synthetic advice only.",
        )

    monkeypatch.setattr("corinthos.adapters.service.AdapterManager.probe", probe)
    manager.assess(session["session_id"])
    manager.get(session["session_id"])
    assert observed == []
    result = advise(
        manager, session["session_id"], provider="codex", operation_id="synthetic-advice"
    )
    assert result["state"] == "COMPLETED"
    assert result["snapshot"]["result"]["output"] == "Synthetic advice only."
    assert manager.get(session["session_id"]) == session
    reopened = ProjectManager(tmp_path)
    assert (
        advise(reopened, session["session_id"], provider="codex", operation_id="synthetic-advice")
        == result
    )
    assert len(observed) == 1
    assert LifecycleRepository(tmp_path).get("OPERATION", "synthetic-advice") == result
    assert manager.store.list_events() == []


def test_interrupted_advice_is_recorded_without_silent_rerun(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    session = manager.start("A synthetic local idea.", actor_id="synthetic-owner")

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("corinthos.adapters.service.AdapterManager.probe", interrupted)
    with pytest.raises(KeyboardInterrupt):
        advise(manager, session["session_id"], provider="claude", operation_id="interrupted-advice")
    result = advise(
        manager, session["session_id"], provider="claude", operation_id="interrupted-advice"
    )
    assert result["state"] == "INTERRUPTED"
    assert manager.get(session["session_id"]) == session
