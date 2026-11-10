# SPDX-License-Identifier: MPL-2.0
"""Synthetic published contracts exercise durable claims without launching agents."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    ContractStore,
    IntegrityError,
    PublishContext,
    StoreError,
    approval_request,
)
from corinthos.workflow.execution_repository import ExecutionRepository

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/contracts"


def _publish(store, document):
    """Synthetic trusted fixture authority is separate from real terminal consent."""
    proof = approval_request(document) if document["metadata"]["approval"] else None
    origin = document["metadata"]["provenance"]
    return store.publish(
        document,
        context=PublishContext(
            origin["engine"], origin["actor_id"], lambda request: request == proof
        ),
    )


@pytest.fixture
def setup(tmp_path):
    store = ContractStore(tmp_path)
    for name in ("project", "technology-decision", "module", "workflow"):
        document = json.loads((EXAMPLES / (name + ".json")).read_text("utf-8"))
        if name == "workflow":
            second = deepcopy(document["payload"]["checkpoints"][0])
            second.update(
                checkpoint_id="second",
                depends_on=[document["payload"]["checkpoints"][0]["checkpoint_id"]],
            )
            second["completion_criteria"][0]["criterion_id"] = "second-ready"
            document["payload"]["checkpoints"].append(second)
        reference = _publish(store, document)
    clock = [1000.0]
    repository = ExecutionRepository(store, clock=lambda: clock[0])
    bindings = {
        "workspace": str(tmp_path),
        "checkpoints": {
            row["checkpoint_id"]: {"checks": ["Synthetic repository fixture"]}
            for row in document["payload"]["checkpoints"]
        },
    }
    execution = repository.register(reference, bindings, actor_id="fixture-owner")
    return repository, execution, document, clock


def _claim(repository, execution, checkpoint_id=None, *, owner="owner-one", ttl=30):
    checkpoint_id = checkpoint_id or next(
        key for key, row in execution["checkpoints"].items() if not row["depends_on"]
    )
    execution = repository.prepare(
        execution["execution_id"], checkpoint_id, execution["version"], actor_id="fixture-owner"
    )
    return repository.claim(
        execution["execution_id"],
        checkpoint_id,
        execution["version"],
        owner_id=owner,
        provider="codex",
        context={"source_snapshot": {"snapshot_id": "synthetic-before-effects"}},
        ttl=ttl,
    )


def _complete(repository, attempt):
    attempt = repository.transition(
        attempt["attempt_id"],
        attempt["fence"],
        "VERIFYING",
        owner_id=attempt["owner_id"],
        details={"agent_result": "Synthetic result, never checkpoint proof."},
    )
    return repository.transition(
        attempt["attempt_id"],
        attempt["fence"],
        "COMPLETED",
        owner_id=attempt["owner_id"],
        details={
            "checks": "Synthetic passing verification and gate fixture.",
            "cleanup_confirmed": True,
        },
    )


def test_registration_reopen_and_configuration_are_durable_and_idempotent(setup):
    repository, execution, workflow, _ = setup
    assert (
        repository.register(
            ContractRef.from_document(workflow), execution["bindings"], actor_id="another-owner"
        )["execution_id"]
        == execution["execution_id"]
    )
    reopened = ExecutionRepository(repository.store)
    assert reopened.get(execution["execution_id"])["bindings"] == execution["bindings"]
    assert reopened.history(execution["execution_id"])[0]["kind"] == "EXECUTION_REGISTERED"
    changed = deepcopy(execution["bindings"])
    changed["checkpoints"]["second"] = {"checks": ["A different configuration"]}
    with pytest.raises(ConflictError, match="reconciliation"):
        repository.register(ContractRef.from_document(workflow), changed, actor_id="fixture-owner")
    assert len(repository.list()) == 1


def test_prerequisites_verify_before_complete_and_fences_advance(setup):
    repository, execution, _, _ = setup
    with pytest.raises(ConflictError, match="prerequisite"):
        repository.prepare(
            execution["execution_id"], "second", execution["version"], actor_id="fixture-owner"
        )
    attempt = _claim(repository, execution)
    assert attempt["state"] == "RUNNING"
    assert attempt["context"]["workflow_ref"] == execution["workflow_ref"]
    with pytest.raises(ConflictError, match="not permitted"):
        repository.transition(
            attempt["attempt_id"],
            attempt["fence"],
            "COMPLETED",
            owner_id=attempt["owner_id"],
            details={"agent_said": "done"},
        )
    _complete(repository, attempt)
    current = repository.get(execution["execution_id"])
    assert current["lease"]["attempt_id"] is None
    second = _claim(repository, current, "second")
    assert second["fence"] > attempt["fence"]
    _complete(repository, second)
    assert repository.get(execution["execution_id"])["state"] == "COMPLETED"
    assert len(repository.store.list_events()) == 4


def test_competing_claims_commit_exactly_one_attempt(setup):
    repository, execution, _, _ = setup
    first = next(key for key, row in execution["checkpoints"].items() if not row["depends_on"])
    ready = repository.prepare(
        execution["execution_id"], first, execution["version"], actor_id="fixture-owner"
    )
    barrier = Barrier(2, timeout=10)

    def claim(owner):
        barrier.wait()
        try:
            return repository.claim(
                ready["execution_id"],
                first,
                ready["version"],
                owner_id=owner,
                provider="codex",
                context={"source_snapshot": {"snapshot_id": "fixture"}},
            )
        except ConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("owner-left", "owner-right")))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1
    assert (
        len(
            [
                event
                for event in repository.history(execution["execution_id"])
                if event["kind"] == "ATTEMPT_CLAIMED"
            ]
        )
        == 1
    )


def test_expiry_never_steals_uncertain_effects_and_explicit_retry_fences_old_owner(setup):
    repository, execution, _, clock = setup
    attempt = _claim(repository, execution, ttl=10)
    clock[0] += 11
    with pytest.raises(ConflictError, match="expired"):
        repository.renew(attempt["attempt_id"], attempt["fence"], owner_id=attempt["owner_id"])
    with pytest.raises(ConflictError):
        repository.transition(
            attempt["attempt_id"],
            attempt["fence"],
            "VERIFYING",
            owner_id=attempt["owner_id"],
            details={"observed": "late"},
        )
    repository.transition(
        attempt["attempt_id"],
        attempt["fence"],
        "INTERRUPTED",
        owner_id=attempt["owner_id"],
        details={"cleanup_confirmed": False, "reason": "Unknown external effects."},
    )
    current = repository.get(execution["execution_id"])
    assert current["lease"]["attempt_id"] == attempt["attempt_id"]
    with pytest.raises(ConflictError, match="Confirm"):
        repository.recover(
            current["execution_id"],
            attempt["checkpoint_id"],
            current["version"],
            actor_id="fixture-owner",
            inspection={"summary": "Insufficient inspection"},
            decision="RETRY",
        )
    current = repository.recover(
        current["execution_id"],
        attempt["checkpoint_id"],
        current["version"],
        actor_id="fixture-owner",
        inspection={
            "process_stopped": True,
            "effects_inspected": True,
            "summary": "Synthetic isolated workspace inspected after stopping the fake owner.",
        },
        decision="RETRY",
    )
    retried = repository.claim(
        current["execution_id"],
        attempt["checkpoint_id"],
        current["version"],
        owner_id="owner-new",
        provider="codex",
        context={"source_snapshot": {"snapshot_id": "after-inspection"}},
    )
    assert retried["previous_attempt_id"] == attempt["attempt_id"]
    assert retried["fence"] > attempt["fence"]
    with pytest.raises(ConflictError):
        repository.transition(
            attempt["attempt_id"],
            attempt["fence"],
            "COMPLETED",
            owner_id=attempt["owner_id"],
            details={"late": "cannot complete"},
        )
    repository.observe(
        attempt["attempt_id"],
        attempt["fence"],
        owner_id=attempt["owner_id"],
        details={"late_observation": "Retain the original source identity."},
    )
    assert repository.get_attempt(retried["attempt_id"])["state"] == "RUNNING"


def test_recover_verify_creates_a_new_checks_only_attempt_without_rerunning_agent(setup):
    repository, execution, _, _ = setup
    attempt = _claim(repository, execution)
    current = repository.get(execution["execution_id"])
    recovered = repository.recover(
        current["execution_id"],
        attempt["checkpoint_id"],
        current["version"],
        actor_id="fixture-owner",
        inspection={
            "process_stopped": True,
            "effects_inspected": True,
            "summary": "Existing output was inspected.",
        },
        decision="VERIFY",
        owner_id="verification-owner",
        context={"source_snapshot": {"snapshot_id": "observed-existing-output"}},
    )
    verified = repository.get_attempt(
        recovered["checkpoints"][attempt["checkpoint_id"]]["attempt_id"]
    )
    assert verified["provider"] == "verification" and verified["state"] == "VERIFYING"
    assert verified["previous_attempt_id"] == attempt["attempt_id"]
    assert repository.get_attempt(attempt["attempt_id"])["state"] == "INTERRUPTED"
    repository.transition(
        verified["attempt_id"],
        verified["fence"],
        "COMPLETED",
        owner_id="verification-owner",
        details={"checks": "Synthetic re-verification only.", "cleanup_confirmed": True},
    )


@pytest.mark.parametrize(
    "decision,final_state", [("RETRY", "READY"), ("VERIFY", "VERIFYING"), ("BLOCK", "BLOCKED")]
)
def test_recovery_transitions_through_recovering_with_committed_history(
    setup, monkeypatch, decision, final_state
):
    repository, execution, _, _ = setup
    attempt = _claim(repository, execution)
    repository.transition(
        attempt["attempt_id"],
        attempt["fence"],
        "INTERRUPTED",
        owner_id=attempt["owner_id"],
        details={"cleanup_confirmed": False},
    )
    current = repository.get(execution["execution_id"])
    original_event, observed = repository._event, []

    def inspect_transition(connection, execution_id, actor_id, kind, data, **identifiers):
        if kind in {"RECOVERY_STARTED", "RECOVERY_INSPECTED"}:
            actual = repository._checkpoint(connection, execution_id, attempt["checkpoint_id"])
            assert actual["state"] == data["to_state"]
            observed.append((data["from_state"], data["to_state"]))
        return original_event(connection, execution_id, actor_id, kind, data, **identifiers)

    monkeypatch.setattr(repository, "_event", inspect_transition)
    recovered = repository.recover(
        current["execution_id"],
        attempt["checkpoint_id"],
        current["version"],
        actor_id="fixture-owner",
        decision=decision,
        inspection={
            "process_stopped": True,
            "effects_inspected": True,
            "summary": "Inspected existing effects.",
        },
        context={"source_snapshot": {"snapshot_id": "inspected-output"}},
    )
    assert observed == [("INTERRUPTED", "RECOVERING"), ("RECOVERING", final_state)]
    assert recovered["checkpoints"][attempt["checkpoint_id"]]["state"] == final_state
    events = [
        event
        for event in repository.history(current["execution_id"])
        if event["kind"].startswith("RECOVERY_")
    ]
    assert [event["kind"] for event in events] == ["RECOVERY_STARTED", "RECOVERY_INSPECTED"]
    assert [
        (event["data"]["from_state"], event["data"]["to_state"]) for event in events
    ] == observed


def test_failed_recovery_rolls_back_recovering_state_fence_attempt_and_history(setup, monkeypatch):
    repository, execution, _, _ = setup
    attempt = _claim(repository, execution)
    current = repository.get(execution["execution_id"])
    original_attempt = repository.get_attempt(attempt["attempt_id"])
    history = repository.history(execution["execution_id"])
    original_event = repository._event

    def fail_after_final_event(connection, execution_id, actor_id, kind, data, **identifiers):
        event_id = original_event(connection, execution_id, actor_id, kind, data, **identifiers)
        if kind == "RECOVERY_INSPECTED":
            raise StoreError("Synthetic recovery commit failure")
        return event_id

    monkeypatch.setattr(repository, "_event", fail_after_final_event)
    with pytest.raises(StoreError, match="recovery commit failure"):
        repository.recover(
            current["execution_id"],
            attempt["checkpoint_id"],
            current["version"],
            actor_id="fixture-owner",
            decision="VERIFY",
            inspection={
                "process_stopped": True,
                "effects_inspected": True,
                "summary": "Inspected existing effects.",
            },
            context={"source_snapshot": {"snapshot_id": "inspected-output"}},
        )
    assert repository.get(execution["execution_id"]) == current
    assert repository.get_attempt(attempt["attempt_id"]) == original_attempt
    assert repository.history(execution["execution_id"]) == history
    with repository.store._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM wf_attempts").fetchone()[0] == 1


def test_late_transaction_failure_rolls_back_claim_before_any_external_effects(setup, monkeypatch):
    repository, execution, _, _ = setup
    first = next(key for key, row in execution["checkpoints"].items() if not row["depends_on"])
    ready = repository.prepare(
        execution["execution_id"], first, execution["version"], actor_id="fixture-owner"
    )

    def fail(*args, **kwargs):
        raise StoreError("Synthetic late event failure")

    monkeypatch.setattr(repository, "_event", fail)
    with pytest.raises(StoreError, match="late event"):
        repository.claim(
            ready["execution_id"],
            first,
            ready["version"],
            owner_id="owner-one",
            provider="codex",
            context={"source_snapshot": {"snapshot_id": "fixture"}},
        )
    current = repository.get(execution["execution_id"])
    assert current["version"] == ready["version"]
    assert current["checkpoints"][first]["state"] == "READY"
    assert current["lease"]["attempt_id"] is None
    with repository.store._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM wf_attempts").fetchone()[0] == 0


def test_stale_plan_cannot_finish_and_reconciliation_preserves_old_attempt_identity(setup):
    repository, execution, workflow, _ = setup
    attempt = _claim(repository, execution)
    changed = deepcopy(workflow)
    changed["metadata"].update(
        revision_id="workflow-r2",
        version=2,
        supersedes=ContractRef.from_document(workflow).to_json(),
        approval={
            "kind": "HUMAN",
            "approval_id": "synthetic-successor",
            "actor_id": "fixture-owner",
        },
    )
    changed["payload"]["checkpoints"][1]["objective"] = "An approved changed second objective."
    new_ref = _publish(repository.store, changed)
    with pytest.raises(ConflictError, match="source changed"):
        repository.renew(attempt["attempt_id"], attempt["fence"], owner_id=attempt["owner_id"])
    repository.transition(
        attempt["attempt_id"],
        attempt["fence"],
        "INTERRUPTED",
        owner_id=attempt["owner_id"],
        details={"cleanup_confirmed": False, "reason": "Plan changed."},
    )
    current = repository.get(execution["execution_id"])
    with pytest.raises(ConflictError, match="Inspect"):
        repository.reconcile(
            current["execution_id"],
            current["version"],
            new_ref,
            current["bindings"],
            actor_id="fixture-owner",
            preserve_checkpoint_ids=[],
            reason="Changed plan",
        )
    current = repository.recover(
        current["execution_id"],
        attempt["checkpoint_id"],
        current["version"],
        actor_id="fixture-owner",
        inspection={
            "process_stopped": True,
            "effects_inspected": True,
            "summary": "Stopped and inspected the original attempt.",
        },
        decision="BLOCK",
    )
    successor = repository.reconcile(
        current["execution_id"],
        current["version"],
        new_ref,
        current["bindings"],
        actor_id="fixture-owner",
        preserve_checkpoint_ids=[],
        reason="Use the approved successor plan.",
    )
    assert successor["workflow_ref"] == new_ref.to_json()
    assert repository.get(execution["execution_id"])["state"] == "SUPERSEDED"
    assert (
        repository.get_attempt(attempt["attempt_id"])["context"]["workflow_ref"]
        == execution["workflow_ref"]
    )


def test_unchanged_completed_work_carries_its_original_attempt_and_evidence_reference(setup):
    repository, execution, workflow, _ = setup
    attempt = _claim(repository, execution)
    _complete(repository, attempt)
    changed = deepcopy(workflow)
    changed["metadata"].update(
        revision_id="workflow-r2",
        version=2,
        supersedes=ContractRef.from_document(workflow).to_json(),
        approval={
            "kind": "HUMAN",
            "approval_id": "synthetic-successor",
            "actor_id": "fixture-owner",
        },
    )
    changed["payload"]["checkpoints"][1]["objective"] = "A revised second checkpoint."
    reference = _publish(repository.store, changed)
    current = repository.get(execution["execution_id"])
    successor = repository.reconcile(
        current["execution_id"],
        current["version"],
        reference,
        current["bindings"],
        actor_id="fixture-owner",
        preserve_checkpoint_ids=[attempt["checkpoint_id"]],
        reason="The first exact checkpoint and sources are unaffected.",
    )
    inherited = successor["checkpoints"][attempt["checkpoint_id"]]
    assert inherited["state"] == "COMPLETED"
    assert inherited["attempt_id"] == attempt["attempt_id"]
    assert inherited["inherited_from"]["workflow_ref"] == execution["workflow_ref"]
    assert successor["checkpoints"]["second"]["state"] == "PENDING"


def test_preservation_requires_completed_prerequisite_closure(setup):
    repository, execution, workflow, _ = setup
    first = _claim(repository, execution)
    _complete(repository, first)
    current = repository.get(execution["execution_id"])
    second = _claim(repository, current, "second")
    _complete(repository, second)
    current = repository.get(execution["execution_id"])
    with pytest.raises(ConflictError, match="prerequisite chain"):
        repository.reconcile(
            current["execution_id"],
            current["version"],
            ContractRef.from_document(workflow),
            current["bindings"],
            actor_id="fixture-owner",
            preserve_checkpoint_ids=["second"],
            reason="Synthetic incomplete carry selection.",
        )
    assert repository.get(execution["execution_id"])["state"] == "COMPLETED"


def test_changed_milestone_cannot_carry_affected_checkpoint_completion(setup):
    repository, execution, workflow, _ = setup
    attempt = _claim(repository, execution)
    _complete(repository, attempt)
    changed = deepcopy(workflow)
    changed["metadata"].update(
        revision_id="workflow-with-milestone-r2",
        version=2,
        supersedes=ContractRef.from_document(workflow).to_json(),
        approval={
            "kind": "HUMAN",
            "approval_id": "synthetic-milestone-approval",
            "actor_id": "fixture-owner",
        },
    )
    changed["payload"]["playtest_milestones"] = [
        {
            "milestone_id": "owner-review",
            "title": "Approved readiness review",
            "objective": "Review the first checkpoint under the new milestone obligations.",
            "depends_on": [],
            "required_checkpoint_ids": [attempt["checkpoint_id"]],
            "test_scope": {"included": ["The greeting journey"], "excluded": []},
            "test_scenarios": ["Inspect the changed readiness expectation."],
            "readiness_criteria": [
                {
                    "criterion_id": "milestone-ready",
                    "criterion": "The added readiness expectation is independently checked.",
                }
            ],
        }
    ]
    reference = _publish(repository.store, changed)
    current = repository.get(execution["execution_id"])
    with pytest.raises(ConflictError, match="milestone changes"):
        repository.reconcile(
            current["execution_id"],
            current["version"],
            reference,
            current["bindings"],
            actor_id="fixture-owner",
            preserve_checkpoint_ids=[attempt["checkpoint_id"]],
            reason="A caller cannot omit milestone impact from its carry selection.",
        )
    assert repository.get(execution["execution_id"])["state"] != "SUPERSEDED"
    assert len(repository.list()) == 1


@pytest.mark.parametrize(
    "field,key", [("structural_proposals", "description"), ("negotiated_decisions", "rationale")]
)
def test_changed_project_decisions_cannot_carry_old_completion(setup, field, key):
    repository, execution, workflow, _ = setup
    attempt = _claim(repository, execution)
    _complete(repository, attempt)
    project_ref = ContractRef.from_json(workflow["payload"]["project_contract_ref"])
    project = repository.store.get(project_ref)
    changed_project = deepcopy(project)
    changed_project["metadata"].update(
        revision_id="project-r2", version=2, supersedes=project_ref.to_json()
    )
    changed_project["payload"][field][0][key] = "An approved changed structural decision."
    new_project_ref = _publish(repository.store, changed_project)
    successor = deepcopy(workflow)
    successor["metadata"].update(
        revision_id="workflow-r2",
        version=2,
        supersedes=ContractRef.from_document(workflow).to_json(),
        approval={
            "kind": "HUMAN",
            "approval_id": "synthetic-successor",
            "actor_id": "fixture-owner",
        },
    )
    successor["payload"]["project_contract_ref"] = new_project_ref.to_json()
    new_ref = _publish(repository.store, successor)
    current = repository.get(execution["execution_id"])
    with pytest.raises(ConflictError, match="demonstrably unchanged"):
        repository.reconcile(
            current["execution_id"],
            current["version"],
            new_ref,
            current["bindings"],
            actor_id="fixture-owner",
            preserve_checkpoint_ids=[attempt["checkpoint_id"]],
            reason="Synthetic attempt to carry old decisions.",
        )


def test_reconciliation_cannot_switch_to_unrelated_workflow_lineage(setup):
    repository, execution, _, _ = setup
    for name in ("project", "technology-decision", "module", "workflow"):
        unrelated = json.loads(
            (EXAMPLES / (name + ".json")).read_text("utf-8").replace("demo-", "other-")
        )
        reference = _publish(repository.store, unrelated)
    with pytest.raises(ConflictError, match="same logical Workflow lineage"):
        repository.reconcile(
            execution["execution_id"],
            execution["version"],
            reference,
            execution["bindings"],
            actor_id="fixture-owner",
            preserve_checkpoint_ids=[],
            reason="Synthetic unrelated plan.",
        )


def test_attempt_cannot_replace_exact_sources_or_leave_authorized_workspace(setup, tmp_path):
    repository, execution, workflow, _ = setup
    first = next(key for key, row in execution["checkpoints"].items() if not row["depends_on"])
    ready = repository.prepare(
        execution["execution_id"], first, execution["version"], actor_id="fixture-owner"
    )
    with pytest.raises(IntegrityError, match="exact registered sources"):
        repository.claim(
            ready["execution_id"],
            first,
            ready["version"],
            owner_id="owner-one",
            provider="codex",
            context={"source_snapshot": {"snapshot_id": "fixture"}, "module_refs": []},
        )
    assert repository.get(execution["execution_id"])["lease"]["attempt_id"] is None
    outside = deepcopy(execution["bindings"])
    outside["workspace"] = str(tmp_path.parent)
    with pytest.raises(StoreError, match="authorized workspace"):
        repository.register(ContractRef.from_document(workflow), outside, actor_id="fixture-owner")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE wf_execution_events SET kind = 'forged'",
        "DELETE FROM wf_execution_events",
        "INSERT OR REPLACE INTO wf_execution_events SELECT * FROM wf_execution_events",
    ],
)
def test_execution_observations_are_append_only(setup, statement):
    repository, execution, _, _ = setup
    with pytest.raises(StoreError):
        with repository.store._transaction() as connection:
            connection.execute(statement)
    assert len(repository.history(execution["execution_id"])) == 1
