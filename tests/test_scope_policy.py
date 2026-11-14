# SPDX-License-Identifier: MPL-2.0
"""Exercise structured scope recommendations and transactional operator decisions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from test_work_items import _create, _example, _publish
from test_work_items import work as work

from corinthos.contracts import ConflictError, ContractStore
from corinthos.lifecycle.repository import LifecycleRepository
from corinthos.sessions.repository import SessionRepository
from corinthos.work import WorkError
from corinthos.work.scope import ScopePolicyService
from corinthos.workflow.execution_repository import ExecutionRepository


def test_scope_assessment_is_passive_and_ignores_prose(work, monkeypatch):
    dependency = _create(work, "Earlier task")
    item = _create(
        work,
        "Urgent production security and architectural rewrite",
        affected_modules=["z-module", "a-module"],
        depends_on=[dependency.work_item_id],
    )
    policy = ScopePolicyService(work.root)
    original = (work.root / ".corinthos" / "state.db").read_bytes()

    def fail_write(*args, **kwargs):
        pytest.fail("A passive assessment opened a write transaction.")

    monkeypatch.setattr(ContractStore, "_transaction", fail_write)
    result = policy.assess(item.work_item_id)
    assert result == policy.assess(item.work_item_id)
    assert result["selected_scope"] == result["minimum_required_scope"] == "TASK"
    assert result["recommended_scope"] == "CHANGE"
    assert result["effective_flow"] == "TASK" and result["policy_version"] == 1
    assert result["unknowns"] == ["AFFECTED_MODULE_AUTHORITY_UNKNOWN", "RISK_UNKNOWN"]
    with work._read() as repository:
        reversed_item = replace(item, affected_modules=tuple(reversed(item.affected_modules)))
        assert policy.assess_item(repository.connection, reversed_item) == result
    assert work.get(item.work_item_id) == item
    assert (work.root / ".corinthos" / "state.db").read_bytes() == original


def test_exact_stale_technology_requires_project_authority(work):
    store = ContractStore(work.root)
    _publish(store, _example("project"))
    decision = _example("technology-decision")
    original = _publish(store, decision)
    _publish(store, _example("module"))
    _publish(store, _example("workflow"))
    item = _create(work, "A bounded fixture", scope_level="PROJECT", affected_modules=["greeting"])
    policy = ScopePolicyService(work.root)
    assert policy.assess(item.work_item_id)["minimum_required_scope"] == "TASK"

    decision["metadata"].update(
        revision_id="scope-technology-r2",
        version=2,
        supersedes=original.to_json(),
        approval={"kind": "HUMAN", "approval_id": "scope-fixture-approval", "actor_id": "owner"},
    )
    decision["payload"]["decision_rationale"] = (
        "Revised rationale from the fixture's technology authority."
    )
    _publish(store, decision)
    result = policy.assess(item.work_item_id)
    assert result["minimum_required_scope"] == "PROJECT"
    assert "APPLICABLE_WORKFLOW_TECHNOLOGY_REVISION_STALE" in result["signals"]
    with pytest.raises(WorkError, match="structurally required minimum"):
        policy.set(item.work_item_id, "CHANGE", item.updated_at, True)
    assert work.get(item.work_item_id) == item


def test_scope_decisions_use_cas_and_append_exact_provenance(work):
    item = _create(work)
    policy = ScopePolicyService(work.root)
    elevated = policy.set(item.work_item_id, "CRITICAL", item.updated_at, actor_id="author")
    assert elevated["selected_scope"] == "CRITICAL" and elevated["updated_at"] > item.updated_at
    assert elevated["downgrade_requires_confirmation"]
    with pytest.raises(ConflictError, match="changed"):
        policy.set(item.work_item_id, "PROJECT", item.updated_at, True)
    with pytest.raises(WorkError, match="explicit confirmation"):
        policy.set(item.work_item_id, "CHANGE", elevated["updated_at"])

    lowered = policy.set(
        item.work_item_id, "CHANGE", elevated["updated_at"], True, actor_id="author"
    )
    assert lowered["selected_scope"] == "CHANGE"
    assert policy.set(item.work_item_id, "CHANGE", lowered["updated_at"]) == lowered
    events = LifecycleRepository(ContractStore(work.root)).events(item.project_id)
    assert [event["kind"] for event in events] == ["WORK_ITEM_SCOPE_CHANGED"] * 2
    assert [event["actor_id"] for event in events] == ["author", "author"]
    assert events[1]["data"] == {
        "work_item_id": item.work_item_id,
        "old_scope": "CRITICAL",
        "new_scope": "CHANGE",
        "updated_at": lowered["updated_at"],
        "policy_version": 1,
        "confirm_downgrade": True,
    }
    assert work.get(item.work_item_id) == replace(
        item, scope_level="CHANGE", updated_at=lowered["updated_at"]
    )
    closed = work.transition(item.work_item_id, "CANCELLED")
    with pytest.raises(WorkError, match="Terminal"):
        policy.set(item.work_item_id, "PROJECT", closed.updated_at)


def test_simultaneous_scope_decisions_commit_exactly_one_change(work):
    item = _create(work)
    barrier = Barrier(2)

    def set_scope(scope):
        barrier.wait(timeout=5)
        return ScopePolicyService(work.root).set(item.work_item_id, scope, item.updated_at)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(set_scope, scope) for scope in ("CHANGE", "PROJECT")]
        successes = []
        for future in futures:
            try:
                successes.append(future.result())
            except ConflictError as error:
                assert "Work Item changed" in str(error)
    [saved] = successes
    assert work.get(item.work_item_id).scope_level == saved["selected_scope"]
    [event] = LifecycleRepository(work.root).events(item.project_id)
    assert event["data"]["new_scope"] == saved["selected_scope"]


def test_scope_change_rolls_back_if_the_audit_event_cannot_be_saved(work, monkeypatch):
    item = _create(work)
    policy = ScopePolicyService(work.root)

    def fail_audit(*args, **kwargs):
        raise ConflictError("The audit could not be saved.")

    monkeypatch.setattr(LifecycleRepository, "event", fail_audit)
    with pytest.raises(ConflictError, match="audit could not be saved"):
        policy.set(item.work_item_id, "PROJECT", item.updated_at)
    assert work.get(item.work_item_id) == item
    assert LifecycleRepository(work.root).events(item.project_id) == []


def test_active_session_allows_elevation_and_fences_downgrade(work):
    item = _create(work)
    policy = ScopePolicyService(work.root)
    sessions = SessionRepository(work.root)
    session = sessions.create(
        item.work_item_id, provider="codex", owner_id="fixture", timeout_seconds=30
    )
    elevated = policy.set(item.work_item_id, "CRITICAL", item.updated_at)
    with pytest.raises(ConflictError, match="active Agent Session"):
        policy.set(item.work_item_id, "TASK", elevated["updated_at"], True)
    sessions.finish(session.session_id, session.owner_id, session.run_generation, "FAILED")
    assert (
        policy.set(item.work_item_id, "TASK", elevated["updated_at"], True)["selected_scope"]
        == "TASK"
    )


def test_current_bound_workflow_fences_scope_changes(work):
    store = ContractStore(work.root)
    for name in ("project", "technology-decision", "module", "workflow"):
        reference = _publish(store, _example(name))
    item = _create(
        work,
        scope_level="PROJECT",
        affected_modules=["greeting"],
        acceptance_criteria=["The output is Hello, Ada for input Ada."],
    )
    execution = ExecutionRepository(store).register(
        reference,
        {"workspace": str(work.root), "checkpoints": {"greet": {}}},
        actor_id="fixture",
        work_item_id=item.work_item_id,
    )
    policy = ScopePolicyService(work.root)
    assert execution["bindings"]["work_item"]["work_item_id"] == item.work_item_id
    with pytest.raises(ConflictError, match="bound Workflow"):
        policy.set(item.work_item_id, "CHANGE", item.updated_at, True)
    with pytest.raises(ConflictError, match="bound Workflow"):
        policy.set(item.work_item_id, "CRITICAL", item.updated_at)
    assert work.get(item.work_item_id) == item
