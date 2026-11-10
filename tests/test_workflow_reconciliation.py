# SPDX-License-Identifier: MPL-2.0
"""Revision and PRR tests publish explicitly synthetic approved contract fixtures."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_workflow_planning import ACTOR, edit, fixture, paired_modules, publish, ready, review

from corinthos.contracts import ConflictError, ContractError, ContractRef, IntegrityError
from corinthos.project_manager import ProjectManager
from corinthos.workflow.reconciliation import RevisionReconciler
from corinthos.workflow.service import WorkflowPlanner


def published_plan(root, *, paired=False, independent=False, second_checkpoint=False):
    planner = WorkflowPlanner(root)
    snapshot = (
        paired_modules(planner) if paired else ready(planner, second_checkpoint=second_checkpoint)
    )
    if independent:
        snapshot = edit(
            planner,
            snapshot,
            action="upsert_module",
            module_id="independent",
            purpose_and_boundaries={
                "purpose": "Independent support",
                "responsibilities": ["Document local operation"],
                "exclusions": [],
            },
            requirement_ids=[],
        )
        checkpoint = deepcopy(next(iter(snapshot["draft"]["checkpoints"].values())))
        checkpoint.update(
            checkpoint_id="independent-step",
            module_ids=["independent"],
            requirement_ids=[],
            depends_on=[],
        )
        checkpoint["completion_criteria"][0]["criterion_id"] = "independent-ready"
        snapshot = edit(planner, snapshot, action="upsert_checkpoint", checkpoint=checkpoint)
    frozen = review(planner, snapshot)
    for document in frozen["review"]["documents"]:
        publish(planner.store, document)
    workflow = frozen["review"]["documents"][-1]
    return planner, workflow, frozen["review"]["documents"]


def successor(document):
    updated = deepcopy(document)
    metadata = updated["metadata"]
    metadata.update(
        version=metadata["version"] + 1,
        revision_id="revision-" + uuid4().hex,
        supersedes=ContractRef.from_document(document).to_json(),
        created_at=datetime.now(UTC).isoformat(),
        approval={
            "kind": "HUMAN",
            "approval_id": "synthetic-approval-" + uuid4().hex,
            "actor_id": ACTOR,
        },
    )
    return updated


def diagnosis(workflow):
    payload = fixture("project-revision-request")["payload"]
    return {
        "kind": "STRUCTURAL_CONFLICT",
        "affected_proposals": payload["affected_proposals"],
        "inconsistencies": payload["inconsistencies"],
        "evidence": [
            {
                "source_ref": ContractRef.from_document(workflow).to_json(),
                "evidence_ids": [],
                "description": "Synthetic diagnosis cites the exact engineering plan and its runtime prerequisite.",
                "limitations": [
                    "This synthetic fixture does not claim an executed deployment failure."
                ],
            }
        ],
        "alternatives": payload["alternatives"],
        "impact": {
            **payload["impact"],
            "module_ids": [row["module_id"] for row in workflow["payload"]["modules"]],
            "checkpoint_ids": [row["checkpoint_id"] for row in workflow["payload"]["checkpoints"]],
            "technology_decision_refs": [
                row["decision_contract_ref"] for row in workflow["payload"]["technology_decisions"]
            ],
        },
    }


def test_current_plan_reports_exact_sources_without_mutating_history(tmp_path):
    planner, workflow, documents = published_plan(tmp_path)
    reconciler = RevisionReconciler(planner.store)
    before = planner.store.list_events()
    report = reconciler.inspect(ContractRef.from_document(workflow))
    assert report["current"]
    assert report["changes"] == []
    assert report["preserved_checkpoint_ids"] == ["greet"]
    assert {raw["contract_type"] for raw in report["source_refs"]} == {
        "PROJECT",
        "WORKFLOW",
        "MODULE",
        "TECHNOLOGY_DECISION",
    }
    assert planner.store.list_events() == before
    for document in documents:
        assert planner.store.get(ContractRef.from_document(document)) == document


def test_provider_revision_affects_consumers_and_preserves_independent_work(tmp_path):
    planner, workflow, documents = published_plan(tmp_path, paired=True, independent=True)
    provider = next(
        item
        for item in documents
        if item["metadata"]["contract_type"] == "MODULE"
        and item["payload"]["module_id"] == "provider"
    )
    changed = successor(provider)
    changed["payload"]["purpose_and_boundaries"]["exclusions"].append(
        "A clarified provider-only boundary"
    )
    changed_ref = publish(planner.store, changed)
    reconciler = RevisionReconciler(planner.store)
    report = reconciler.inspect(ContractRef.from_document(workflow))
    assert not report["current"]
    assert report["affected_module_ids"] == ["consumer", "provider"]
    assert report["affected_checkpoint_ids"] == ["consumer-step", "provider-step"]
    assert report["preserved_checkpoint_ids"] == ["independent-step"]
    new_workflow = successor(workflow)
    for row in new_workflow["payload"]["modules"]:
        if row["module_id"] == "provider":
            row["module_contract_ref"] = changed_ref.to_json()
    new_ref = publish(planner.store, new_workflow)
    # The consumer retains its original exact provider reference. Its required
    # interface terms are present unchanged in the new approved provider.
    assert reconciler.inspect(new_ref)["current"]
    impact = reconciler.compare(ContractRef.from_document(workflow), new_ref)
    assert impact["preserved_module_ids"] == ["independent"]
    assert impact["preserved_checkpoint_ids"] == ["independent-step"]
    assert planner.store.get(ContractRef.from_document(provider)) == provider


def test_project_requirement_change_maps_by_ids_and_global_scope_is_conservative(tmp_path):
    planner, workflow, _ = published_plan(tmp_path, paired=True, independent=True)
    reconciler = RevisionReconciler(planner.store)
    project = planner.store.get(ContractRef.from_json(workflow["payload"]["project_contract_ref"]))
    updated = successor(project)
    updated["payload"]["requirements"][0]["acceptance_criteria"][0]["criterion"] += (
        " Preserve punctuation."
    )
    publish(planner.store, updated)
    report = reconciler.inspect(ContractRef.from_document(workflow))
    assert not report["current"]
    assert report["affected_module_ids"] == ["consumer", "provider"]
    assert report["preserved_checkpoint_ids"] == ["independent-step"]
    global_change = successor(updated)
    global_change["payload"]["scope"]["risks"].append("A new project-wide assumption needs review.")
    publish(planner.store, global_change)
    report = reconciler.inspect(ContractRef.from_document(workflow))
    assert set(report["affected_module_ids"]) == {"provider", "consumer", "independent"}
    assert report["preserved_checkpoint_ids"] == []


def test_technology_and_workflow_revision_drift_are_detected(tmp_path):
    planner, workflow, documents = published_plan(tmp_path, second_checkpoint=True)
    reconciler = RevisionReconciler(planner.store)
    changed_workflow = successor(workflow)
    target = next(
        row
        for row in changed_workflow["payload"]["checkpoints"]
        if row["checkpoint_id"] == "checkpoint-second"
    )
    target["depends_on"] = ["greet"]
    new_ref = publish(planner.store, changed_workflow)
    impact = reconciler.compare(ContractRef.from_document(workflow), new_ref)
    assert impact["affected_checkpoint_ids"] == ["checkpoint-second"]
    assert impact["preserved_checkpoint_ids"] == ["greet"]
    assert not reconciler.inspect(ContractRef.from_document(workflow))["current"]
    technology = next(
        item for item in documents if item["metadata"]["contract_type"] == "TECHNOLOGY_DECISION"
    )
    changed_technology = successor(technology)
    changed_technology["payload"]["decision_rationale"] += (
        " Additional confirmed compatibility constraints."
    )
    publish(planner.store, changed_technology)
    report = reconciler.inspect(new_ref)
    assert not report["current"]
    assert {row["expected_ref"]["contract_type"] for row in report["changes"]} == {
        "TECHNOLOGY_DECISION"
    }
    assert report["affected_checkpoint_ids"] == ["checkpoint-second", "greet"]
    with pytest.raises(ConflictError, match="stale"):
        reconciler.compare(ContractRef.from_document(workflow), new_ref)


def test_structural_request_uses_real_kernel_and_real_pm_intake_without_project_change(tmp_path):
    planner, workflow, _ = published_plan(tmp_path)
    reconciler = RevisionReconciler(planner.store)
    payload = diagnosis(workflow)
    ref = reconciler.create_revision_request(
        ContractRef.from_document(workflow),
        payload,
        actor_id="workflow-diagnosis",
        request_id="stable-request",
    )
    original = planner.store.get(ContractRef.from_json(workflow["payload"]["project_contract_ref"]))
    request = planner.store.get(ref)
    assert request["metadata"]["approval"] is None
    assert request["payload"]["evidence"][0]["evidence_ids"] == []
    assert request["payload"]["inconsistencies"][0]["kind"] == "STRUCTURAL_CONFLICT"
    event_count = len(planner.store.list_events())
    assert (
        reconciler.create_revision_request(
            ContractRef.from_document(workflow),
            payload,
            actor_id="workflow-diagnosis",
            request_id="stable-request",
        )
        == ref
    )
    assert len(planner.store.list_events()) == event_count
    session = reconciler.negotiate_request(ref, "STRUCTURAL", actor_id="local-owner")
    assert session["source_prr"] == ref.to_json()
    assert session["base_ref"] == ContractRef.from_document(original).to_json()
    manager = ProjectManager(tmp_path)
    kept = manager.keep(session["session_id"], session["version"], actor_id="local-owner")
    assert kept["state"] == "CLOSED_UNCHANGED"
    assert planner.store.get(ContractRef.from_document(original)) == original
    assert len(planner.store.list_events()) == event_count


@pytest.mark.parametrize(
    "fault",
    [
        "bug",
        "no_facts",
        "no_evidence",
        "malformed_evidence",
        "no_limitations",
        "fake_validation_ids",
        "out_of_plan",
        "empty_request_id",
    ],
)
def test_invalid_or_ordinary_failure_diagnoses_publish_nothing(tmp_path, fault):
    planner, workflow, _ = published_plan(tmp_path)
    reconciler = RevisionReconciler(planner.store)
    payload = diagnosis(workflow)
    request_id = "bounded-request"
    if fault == "bug":
        payload["kind"] = "BUG_FIX"
    elif fault == "no_facts":
        payload["inconsistencies"][0]["confirmed_facts"] = []
    elif fault == "no_evidence":
        payload["evidence"] = []
    elif fault == "malformed_evidence":
        payload["evidence"] = None
    elif fault == "no_limitations":
        payload["evidence"][0]["limitations"] = []
    elif fault == "fake_validation_ids":
        payload["evidence"][0]["evidence_ids"] = ["invented-test-result"]
    elif fault == "out_of_plan":
        payload["impact"]["module_ids"] = ["unrelated-module"]
    else:
        request_id = ""
    before = planner.store.list_events()
    with pytest.raises(ContractError):
        reconciler.create_revision_request(
            ContractRef.from_document(workflow),
            payload,
            actor_id="workflow-diagnosis",
            request_id=request_id,
        )
    assert planner.store.list_events() == before


def test_stale_product_request_and_changed_request_identity_fail_closed(tmp_path):
    planner, workflow, _ = published_plan(tmp_path)
    reconciler = RevisionReconciler(planner.store)
    payload = diagnosis(workflow)
    reference = ContractRef.from_document(workflow)
    reconciler.create_revision_request(
        reference, payload, actor_id="workflow", request_id="request-once"
    )
    payload["inconsistencies"][0]["description"] += " A different diagnosis."
    with pytest.raises(ConflictError, match="another structural diagnosis"):
        reconciler.create_revision_request(
            reference, payload, actor_id="workflow", request_id="request-once"
        )
    project = planner.store.get(ContractRef.from_json(workflow["payload"]["project_contract_ref"]))
    changed = successor(project)
    changed["payload"]["vision"] += " Another approved global goal."
    publish(planner.store, changed)
    with pytest.raises(ConflictError, match="current approved"):
        reconciler.create_revision_request(
            reference, payload, actor_id="workflow", request_id="new-request"
        )


def test_owner_change_routes_directly_to_pm_without_manufacturing_a_request(tmp_path):
    planner, workflow, _ = published_plan(tmp_path)
    reconciler = RevisionReconciler(planner.store)
    before = planner.store.list_events()
    session = reconciler.start_project_revision(
        workflow["payload"]["project_contract_ref"],
        "Owner requested a new target.",
        actor_id="owner",
    )
    assert session["source_prr"] is None
    assert session["reason"] == "Owner requested a new target."
    assert planner.store.list_events() == before
    with pytest.raises(IntegrityError):
        reconciler.inspect(workflow["payload"]["project_contract_ref"])
