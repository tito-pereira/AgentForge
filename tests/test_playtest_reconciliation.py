# SPDX-License-Identifier: MPL-2.0
"""Actual revision/execution reconciliation; authority and technical reviewers are synthetic."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_build_lifecycle import _ready, _review
from test_build_lifecycle import built as built
from test_validation_planning import _assess, _bindings
from test_workflow_reconciliation import successor
from test_workflow_runtime import SyntheticAdapter, _accept, _publish

from corinthos.contracts import ConflictError
from corinthos.lifecycle.playtest import PlaytestService
from corinthos.workflow.runtime import WorkflowRunner


def _eligible(builds, build, planner, refs):
    _ready(builds, build)
    draft = planner.derive(
        refs["project"], "PLAYTEST_MILESTONE", target_ref=refs["workflow"], target_ids=["early"]
    )
    bindings = _bindings(draft)
    plan = planner.publish(
        draft,
        bindings,
        _assess(draft, bindings),
        actor_id="synthetic-lineage-planner",
        contract_id="lineage-plan-" + refs["workflow"].revision_id,
    )
    builds.validate(
        build["record_id"], plan, evaluator="synthetic-lineage-evaluator", reviewer=_review
    )


def _old_active(built):
    builds, old, planner, refs, execution, spec = built
    _eligible(builds, old, planner, refs)
    service = PlaytestService(builds.store)
    service.configure(refs["project"].project_id, enabled=True)
    service.promote(refs["project"].project_id, old["record_id"])
    return service, builds, old, planner, refs, execution, spec


def _extend_unrelated_checkpoint(workflow, spec):
    updated = successor(workflow)
    checkpoint = deepcopy(updated["payload"]["checkpoints"][0])
    checkpoint.update(
        checkpoint_id="future-check",
        depends_on=[],
        objective="Future approved verification, outside early milestone.",
    )
    checkpoint["completion_criteria"][0]["criterion_id"] = "future-ready"
    updated["payload"]["checkpoints"].append(checkpoint)
    return updated, [spec, replace(spec, checkpoint_id="future-check")]


def test_approved_descendant_requires_actual_reconciled_execution_and_preserves_original_attempt(
    built,
):
    service, builds, old, planner, refs, execution, spec = _old_active(built)
    updated, specs = _extend_unrelated_checkpoint(builds.store.get(refs["workflow"]), spec)
    new_ref = _publish(builds.store, updated)
    runner = WorkflowRunner(builds.root, SyntheticAdapter(builds.store), reviewer=_accept)
    previous = builds.executions.get(execution["execution_id"])
    reconciled = builds.executions.reconcile(
        execution["execution_id"],
        previous["version"],
        new_ref,
        runner.prepare_bindings(new_ref, specs),
        actor_id="synthetic-lineage-operator",
        preserve_checkpoint_ids=["greet"],
        reason="Exact approved equivalent Workflow successor.",
    )
    assert (
        reconciled["checkpoints"]["greet"]["inherited_from"]["execution_id"]
        == execution["execution_id"]
    )
    new_refs = {**refs, "workflow": new_ref}
    new = builds.prepare(new_ref, "early", reconciled["execution_id"], builds.root)
    _eligible(builds, new, planner, new_refs)
    promoted = service.promote(refs["project"].project_id, new["record_id"])
    assert promoted["state"] == "PROMOTED"
    assert promoted["project"]["active_build_id"] == new["record_id"]
    assert (
        builds.executions.get(reconciled["execution_id"])["checkpoints"]["greet"]["attempt_id"]
        == previous["checkpoints"]["greet"]["attempt_id"]
    )
    assert service.repository.get("BUILD", old["record_id"])["origin"] == old["origin"]


def test_approved_workflow_without_actual_reconciliation_cannot_replace_old_build(built, tmp_path):
    service, builds, old, _, refs, _, spec = _old_active(built)
    updated, specs = _extend_unrelated_checkpoint(builds.store.get(refs["workflow"]), spec)
    new_ref = _publish(builds.store, updated)
    # A separate real workspace/execution is not reconciliation of the active build lineage.
    workspace = tmp_path / "unrelated-workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("Hello Ada", encoding="utf-8")
    runner = WorkflowRunner(builds.root, SyntheticAdapter(builds.store), reviewer=_accept)
    bindings = runner.prepare_bindings(new_ref, specs)
    bindings["workspace"] = str(workspace)
    unrelated = builds.executions.register(new_ref, bindings, actor_id="synthetic-lineage-operator")
    # This unsealed synthetic record exercises only the lineage guard. It supplies
    # no completed checkpoint, ready marker or fabricated Validation proof.
    service.repository.create(
        "BUILD",
        refs["project"].project_id,
        {"execution_id": unrelated["execution_id"]},
        record_id="unrelated-unsealed-build",
        state="PREPARING",
    )
    with service.repository.transaction() as connection:
        previous = service._admission_history(
            refs["project"].project_id, old["record_id"], connection
        )
        candidate = {
            **previous,
            "build_id": "unrelated-unsealed-build",
            "workflow_ref": new_ref.to_json(),
        }
        with pytest.raises(ConflictError, match="actual unambiguous execution reconciliation"):
            service._reconciled_lineage(previous, candidate, connection)


def test_affected_checkpoint_cannot_be_carried_and_fresh_successor_can_promote(built):
    service, builds, _, planner, refs, execution, spec = _old_active(built)
    updated = successor(builds.store.get(refs["workflow"]))
    updated["payload"]["checkpoints"][0]["objective"] += " Inspect the approved revised objective."
    new_ref = _publish(builds.store, updated)
    runner = WorkflowRunner(builds.root, SyntheticAdapter(builds.store), reviewer=_accept)
    previous = builds.executions.get(execution["execution_id"])
    bindings = runner.prepare_bindings(new_ref, [spec])
    with pytest.raises(ConflictError, match="carried checkpoint"):
        builds.executions.reconcile(
            execution["execution_id"],
            previous["version"],
            new_ref,
            bindings,
            actor_id="synthetic-lineage-operator",
            preserve_checkpoint_ids=["greet"],
            reason="Synthetic invalid attempt to carry changed checkpoint.",
        )
    fresh = builds.executions.reconcile(
        execution["execution_id"],
        previous["version"],
        new_ref,
        bindings,
        actor_id="synthetic-lineage-operator",
        preserve_checkpoint_ids=[],
        reason="Rerun affected checkpoint under approved successor.",
    )
    assert runner.run_next(fresh["execution_id"])["state"] == "COMPLETED"
    new = builds.prepare(new_ref, "early", fresh["execution_id"], builds.root)
    _eligible(builds, new, planner, {**refs, "workflow": new_ref})
    assert service.promote(refs["project"].project_id, new["record_id"])["state"] == "PROMOTED"
    assert (
        builds.executions.get(fresh["execution_id"])["checkpoints"]["greet"]["inherited_from"]
        is None
    )
