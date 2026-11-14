# SPDX-License-Identifier: MPL-2.0
"""Verify exact Work Item ownership through the existing Workflow execution repository."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_execution_repository import _claim, _complete, _publish
from test_workflow_runtime import SyntheticAdapter, _seed, _spec

from corinthos.contracts import AuthorityError, ConflictError, IntegrityError
from corinthos.sessions.repository import SessionRepository
from corinthos.work import WorkService
from corinthos.work.scope import ScopePolicyService
from corinthos.workflow.execution_repository import CurrentAuditBlocked, ExecutionRepository
from corinthos.workflow.runtime import WorkflowRunner
from corinthos.workflow.work_binding import (
    applicable_workflow,
    unbound_work_execution,
    work_execution,
    work_fingerprint,
)

_CRITERION = "The output is Hello, Ada for input Ada."


@pytest.fixture
def exact_workflow(tmp_path):
    store, reference = _seed(tmp_path)
    repository = ExecutionRepository(store)
    manager = SyntheticAdapter(store)
    runner = WorkflowRunner(tmp_path, manager, reviewer=lambda _: None)
    work = WorkService(tmp_path)
    return repository, runner, reference, work


def _item(work, *, scope="PROJECT", criteria=(_CRITERION,), modules=("greeting",)):
    return work.create(
        scope_level=scope,
        objective="Use the exact approved greeting workflow.",
        acceptance_criteria=criteria,
        affected_modules=modules,
    )


def _successor(repository, reference, kind):
    successor = deepcopy(repository.store.get(reference))
    successor["metadata"].update(
        revision_id="workflow-r2",
        version=2,
        supersedes=reference.to_json(),
        approval={"kind": kind, "approval_id": "fixture-next", "actor_id": "fixture-owner"},
    )
    successor["payload"]["checkpoints"][0]["title"] = "Check the approved local greeting"
    return _publish(repository.store, successor)


def _view(repository, item):
    with repository.store._connection() as connection:
        return work_execution(connection, item)


def test_exact_binding_survives_reopen_and_status_changes(exact_workflow):
    repository, runner, reference, work = exact_workflow
    item = _item(work)
    config = runner.configure(
        reference, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
    )
    assert config["bindings"]["work_item"] == {
        "work_item_id": item.work_item_id,
        "content_sha256": work_fingerprint(item),
    }
    reopened = ExecutionRepository(repository.store)
    assert reopened.get(config["execution_id"])["bindings"] == config["bindings"]
    assert (
        reopened.register(
            reference,
            config["bindings"],
            actor_id="fixture-owner",
            work_item_id=item.work_item_id,
        )["execution_id"]
        == config["execution_id"]
    )
    active = work.transition(item.work_item_id, "ACTIVE")
    assert active.updated_at != item.updated_at and work_fingerprint(active) == work_fingerprint(
        item
    )
    observed = _view(repository, active)
    assert observed["execution_id"] == config["execution_id"] and observed["binding_current"]
    assert observed["workflow_ref"] == reference.to_json()
    assert observed["checkpoints"] == [
        {"checkpoint_id": "greet", "state": "PENDING", "attempt_id": None, "inherited_from": None}
    ]
    attempt = _claim(repository, config)
    assert attempt["context"]["work_item"] == config["bindings"]["work_item"]


@pytest.mark.parametrize(
    ("scope", "criteria", "modules", "reason"),
    [
        ("TASK", (_CRITERION,), ("greeting",), "nonterminal PROJECT or CRITICAL"),
        ("PROJECT", ("An unrelated obligation.",), ("greeting",), "exact coverage"),
        ("PROJECT", (_CRITERION,), ("unknown-module",), "exact coverage"),
        ("CRITICAL", (_CRITERION,), ("greeting",), "human-approved Workflow"),
    ],
)
def test_invalid_bindings_fail_before_writes(exact_workflow, scope, criteria, modules, reason):
    repository, runner, reference, work = exact_workflow
    item = _item(work, scope=scope, criteria=criteria, modules=modules)
    with pytest.raises((ConflictError, AuthorityError), match=reason):
        runner.configure(
            reference, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
        )
    assert repository.list() == []


def test_empty_module_scope_requires_approved_whole_project_criteria(exact_workflow):
    repository, runner, reference, work = exact_workflow
    item = _item(work, modules=())
    with repository.store._connection() as connection:
        assert applicable_workflow(connection, repository.store.get(reference), item)
        assert not applicable_workflow(
            connection,
            repository.store.get(reference),
            replace(item, acceptance_criteria=("A clean environment reproduces the greeting.",)),
        )
    config = runner.configure(
        reference, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
    )
    assert config["bindings"]["work_item"]["work_item_id"] == item.work_item_id


def test_legacy_execution_does_not_claim_an_unbound_work_item(exact_workflow):
    repository, runner, reference, work = exact_workflow
    item = _item(work)
    legacy = runner.configure(reference, [_spec()], actor_id="fixture-owner")
    assert "work_item" not in legacy["bindings"] and _view(repository, item) is None
    with pytest.raises(ConflictError, match="another execution"):
        runner.configure(
            reference, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
        )
    prepared = repository.prepare(
        legacy["execution_id"], "greet", legacy["version"], actor_id="owner"
    )
    with pytest.raises(IntegrityError, match="unbound execution"):
        repository.claim(
            legacy["execution_id"],
            "greet",
            prepared["version"],
            owner_id="owner",
            provider="codex",
            context={
                "source_snapshot": {"snapshot_id": "fixture"},
                "work_item": {"work_item_id": item.work_item_id},
            },
        )


def test_explicit_reconciliation_can_bind_a_legacy_head_without_carrying_proof(exact_workflow):
    repository, runner, reference, work = exact_workflow
    item = _item(work)
    legacy = runner.configure(reference, [_spec()], actor_id="fixture-owner")
    unrelated = _item(work, criteria=("Unrelated Work Item.",))
    other = runner.root / "unclaimed"
    other.mkdir()

    def reconcile(execution, work_item_id, carried=()):
        return repository.reconcile(
            execution["execution_id"],
            execution["version"],
            reference,
            execution["bindings"],
            actor_id="fixture-owner",
            preserve_checkpoint_ids=carried,
            reason="Explicitly bind the existing Workflow lineage to this Work Item.",
            work_item_id=work_item_id,
        )

    with repository.store._connection() as connection:
        unbound = unbound_work_execution(connection, item, runner.root)
        assert unbound["execution_id"] == legacy["execution_id"]
        assert unbound["workflow_ref"] == reference.to_json() and not unbound["has_claim"]
        assert unbound_work_execution(connection, item, other) is None
    attempt = _claim(repository, legacy)
    current = repository.get(legacy["execution_id"])
    with pytest.raises(ConflictError, match="claimed workspace"):
        reconcile(current, item.work_item_id)
    _complete(repository, attempt)
    current = repository.get(legacy["execution_id"])
    with pytest.raises(ConflictError, match="exact coverage"):
        reconcile(current, unrelated.work_item_id)
    with pytest.raises(ConflictError, match="cannot carry"):
        reconcile(current, item.work_item_id, ["greet"])
    successor = reconcile(current, item.work_item_id)
    assert successor["execution_id"] != legacy["execution_id"]
    assert successor["checkpoints"]["greet"]["state"] == "PENDING"
    assert successor["checkpoints"]["greet"]["attempt_id"] is None
    assert _view(repository, item)["binding_current"]
    retained = repository.get(legacy["execution_id"])
    assert retained["state"] == "SUPERSEDED" and "work_item" not in retained["bindings"]
    assert retained["checkpoints"]["greet"]["attempt_id"] == attempt["attempt_id"]


def test_reconciliation_preserves_owner_and_rechecks_fingerprint(exact_workflow):
    repository, runner, reference, work = exact_workflow
    item = _item(work)
    old = runner.configure(
        reference, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
    )
    _complete(repository, _claim(repository, old))
    old = repository.get(old["execution_id"])
    assert _view(repository, item)["state"] == "COMPLETED"
    changed = work.update(item.work_item_id, objective="A newly bounded operational objective.")
    assert not _view(repository, changed)["binding_current"]
    new = _successor(repository, reference, "HUMAN")
    with pytest.raises(ConflictError, match="cannot carry"):
        repository.reconcile(
            old["execution_id"],
            old["version"],
            new,
            old["bindings"],
            actor_id="fixture-owner",
            preserve_checkpoint_ids=["greet"],
            reason="Exact existing Workflow successor.",
        )
    another = _item(work)
    rebound = deepcopy(old["bindings"])
    rebound["work_item"]["work_item_id"] = another.work_item_id
    with pytest.raises(ConflictError, match="Work Item owner"):
        repository.reconcile(
            old["execution_id"],
            old["version"],
            new,
            rebound,
            actor_id="fixture-owner",
            preserve_checkpoint_ids=[],
            reason="Rebind to unrelated Work Item.",
        )
    successor = repository.reconcile(
        old["execution_id"],
        old["version"],
        new,
        old["bindings"],
        actor_id="fixture-owner",
        preserve_checkpoint_ids=[],
        reason="Refresh same explicitly selected Work Item.",
    )
    assert successor["execution_id"] != old["execution_id"]
    assert successor["bindings"]["work_item"]["content_sha256"] == work_fingerprint(changed)
    assert _view(repository, changed)["binding_current"]
    assert successor["checkpoints"]["greet"]["state"] == "PENDING"
    assert _view(repository, another) is None


def test_second_workspace_cannot_claim_same_work_item(exact_workflow, tmp_path):
    repository, runner, reference, work = exact_workflow
    item = _item(work)
    first = runner.configure(
        reference, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
    )
    other = tmp_path / "another-workspace"
    other.mkdir()
    bindings = dict(first["bindings"], workspace=str(other))
    with pytest.raises(ConflictError, match="already has a current"):
        repository.register(reference, bindings, actor_id="fixture-owner")
    assert [row["execution_id"] for row in repository.list()] == [first["execution_id"]]


def test_active_binding_blocks_content_drift_and_scope_change(exact_workflow):
    repository, runner, reference, work = exact_workflow
    item = _item(work)
    config = runner.configure(
        reference, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
    )
    policy = ScopePolicyService(runner.root)
    with pytest.raises(ConflictError, match="bound Workflow"):
        policy.set(item.work_item_id, "CRITICAL", item.updated_at)
    with pytest.raises(ConflictError, match="bound Workflow"):
        policy.set(item.work_item_id, "CHANGE", item.updated_at, confirm_downgrade=True)
    attempt = _claim(repository, config)
    drift = work.update(item.work_item_id, objective="Changed during the attempt.")
    assert _view(repository, drift)["has_claim"] and not _view(repository, drift)["binding_current"]
    with pytest.raises(ConflictError, match="Work Item changed"):
        repository.renew(attempt["attempt_id"], attempt["fence"], owner_id=attempt["owner_id"])
    assert (
        repository.transition(
            attempt["attempt_id"],
            attempt["fence"],
            "INTERRUPTED",
            owner_id=attempt["owner_id"],
            details={"reason": "Work Item changed.", "cleanup_confirmed": True},
        )["state"]
        == "INTERRUPTED"
    )


def test_bound_workflow_cannot_claim_while_project_session_is_active(exact_workflow):
    repository, runner, reference, work = exact_workflow
    item = _item(work)
    session_item = _item(work, scope="TASK")
    config = runner.configure(
        reference, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
    )
    prepared = repository.prepare(
        config["execution_id"], "greet", config["version"], actor_id="fixture-owner"
    )
    sessions = SessionRepository(runner.root)
    session = sessions.create(
        session_item.work_item_id,
        provider="codex",
        owner_id="fixture-session",
        timeout_seconds=30,
        read_only=True,
        lease_seconds=30,
    )
    with pytest.raises(ConflictError, match="active Agent Session"):
        repository.claim(
            prepared["execution_id"],
            "greet",
            prepared["version"],
            owner_id="owner-one",
            provider="codex",
            context={"source_snapshot": {"snapshot_id": "fixture"}},
        )
    assert repository.get(config["execution_id"])["lease"]["attempt_id"] is None
    sessions.finish(
        session.session_id,
        session.owner_id,
        session.run_generation,
        "INTERRUPTED",
        reason="SYNTHETIC_FIXTURE_STOPPED",
    )
    assert _claim(repository, prepared)["state"] == "RUNNING"


@pytest.mark.parametrize("kind", ["DELEGATED", "HUMAN"])
def test_critical_binds_only_human_workflow_and_requires_formal_check(exact_workflow, kind):
    repository, runner, reference, work = exact_workflow
    item = _item(work, scope="CRITICAL")
    new = _successor(repository, reference, kind)
    if kind == "DELEGATED":
        with pytest.raises(AuthorityError, match="human-approved Workflow"):
            runner.configure(
                new, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
            )
        assert repository.list() == []
        return
    configuration = runner.configure(
        new, [_spec()], actor_id="fixture-owner", work_item_id=item.work_item_id
    )
    assert configuration["bindings"]["checkpoints"]["greet"]["audit_expectations"] == [
        {"level": "CHECKPOINT", "target_ref": new.to_json(), "scope": ["greet"]},
    ]
    assert _view(repository, item)["workflow_approval_kind"] == "HUMAN"
    assert _view(repository, item)["binding_current"]
    attempt = _claim(repository, configuration)
    with pytest.raises(CurrentAuditBlocked):
        _complete(repository, attempt)
    assert repository.get_attempt(attempt["attempt_id"])["state"] == "VERIFYING"
