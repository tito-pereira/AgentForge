# SPDX-License-Identifier: MPL-2.0
"""Planning tests use synthetic trusted contract receipts, never production consent."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    IntegrityError,
    PublishContext,
    approval_request,
)
from corinthos.workflow.service import WorkflowPlanner

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "contracts"
ACTOR = "synthetic-planning-owner"


def fixture(name):
    return json.loads((EXAMPLES / (name + ".json")).read_text("utf-8"))


def publish(store, document):
    """Provide a labeled exact test receipt outside the production terminal bridge."""
    request = approval_request(document)
    provenance = document["metadata"]["provenance"]
    return store.publish(
        document,
        context=PublishContext(
            provenance["engine"], provenance["actor_id"], lambda value: value == request
        ),
    )


def edit(planner, snapshot, **operation):
    return planner.edit(snapshot["session_id"], snapshot["version"], operation, actor_id=ACTOR)


def ready(planner, *, interfaces=False, second_checkpoint=False):
    project = fixture("project")
    reference = publish(planner.store, project)
    snapshot = planner.start(reference, actor_id=ACTOR)
    module = fixture("module")["payload"]
    snapshot = edit(
        planner,
        snapshot,
        action="upsert_module",
        module_id=module["module_id"],
        purpose_and_boundaries=module["purpose_and_boundaries"],
        requirement_ids=["R1"],
    )
    snapshot = edit(
        planner,
        snapshot,
        action="upsert_technology",
        decision_id="runtime",
        payload=fixture("technology-decision")["payload"],
    )
    snapshot = edit(
        planner,
        snapshot,
        action="set_module_technology",
        module_id=module["module_id"],
        decision_ids=["runtime"],
    )
    if interfaces:
        snapshot = edit(
            planner,
            snapshot,
            action="set_provided_interfaces",
            module_id=module["module_id"],
            interfaces=module["provided_interfaces"],
        )
    checkpoint = fixture("workflow")["payload"]["checkpoints"][0]
    snapshot = edit(planner, snapshot, action="upsert_checkpoint", checkpoint=checkpoint)
    if second_checkpoint:
        checkpoint = deepcopy(checkpoint)
        checkpoint.update(checkpoint_id="checkpoint-second", depends_on=[])
        checkpoint["completion_criteria"][0]["criterion_id"] = "second-criterion"
        snapshot = edit(planner, snapshot, action="upsert_checkpoint", checkpoint=checkpoint)
    return snapshot


def review(planner, snapshot, **kwargs):
    return planner.review(snapshot["session_id"], snapshot["version"], actor_id=ACTOR, **kwargs)


def test_complete_plan_freezes_exact_dependency_order_without_publishing(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner, interfaces=True)
    assert planner.assess(snapshot["session_id"])["issues"] == []
    frozen = review(planner, snapshot)
    documents = frozen["review"]["documents"]
    assert [item["metadata"]["contract_type"] for item in documents] == [
        "TECHNOLOGY_DECISION",
        "MODULE",
        "WORKFLOW",
    ]
    module = documents[1]
    assert module["payload"]["constraint_refs"][0]["obligation_id"] == "C1"
    spec = module["payload"]["verification_spec"]
    assert {item["standard_rule_ref"]["rule_id"] for item in spec["quality_checks"]} == {
        "M1",
        "M2",
        "M3",
        "M4",
        "M5",
    }
    assert all(
        item["blocking"]
        for field in (
            "requirement_checks",
            "constraint_checks",
            "interface_checks",
            "quality_checks",
        )
        for item in spec[field]
    )
    workflow = documents[-1]["payload"]
    assert (
        workflow["modules"][0]["module_contract_ref"] == ContractRef.from_document(module).to_json()
    )
    reopened = WorkflowPlanner(tmp_path)
    assert reopened.get(snapshot["session_id"])["review"] == frozen["review"]
    assert len(reopened.store.list_events()) == 1
    assert "NOT_VERIFIED" in " ".join(reopened.assess(snapshot["session_id"])["unknowns"])


def test_incomplete_planning_is_inspectable_and_has_no_fake_execution(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = planner.start(publish(planner.store, fixture("project")), actor_id=ACTOR)
    assert planner.assess(snapshot["session_id"])["issues"]
    with pytest.raises(IntegrityError):
        review(planner, snapshot)
    assert planner.store.list_events()[0]["contract_type"] == "PROJECT"


def test_outside_ranking_choice_preserves_the_original_recommendations(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    original = deepcopy(snapshot["draft"]["decisions"]["runtime"]["payload"]["ai_recommendations"])
    snapshot = edit(
        planner,
        snapshot,
        action="select_technology",
        decision_id="runtime",
        selected_option={
            "source": "HUMAN",
            "technology": "Another supplied runtime",
            "feasibility_rationale": "The owner supplied a bounded compatibility assessment.",
        },
        decision_rationale="The owner chose the explicitly assessed outside option.",
    )
    frozen = review(planner, snapshot)
    assert frozen["review"]["documents"][0]["payload"]["ai_recommendations"] == original
    assert frozen["review"]["documents"][0]["payload"]["selected_option"]["source"] == "HUMAN"
    snapshot = frozen
    changed = deepcopy(snapshot["draft"]["decisions"]["runtime"]["payload"])
    changed["ai_recommendations"][0]["technology"] = "Retroactively changed ranking"
    with pytest.raises(IntegrityError, match="original recommendations"):
        edit(planner, snapshot, action="upsert_technology", decision_id="runtime", payload=changed)


def test_zero_viable_technology_options_block_review_without_publication(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    payload = fixture("technology-decision")["payload"]
    payload.update(ai_recommendations=[], selected_option=None)
    snapshot = edit(planner, snapshot, action="remove_technology", decision_id="runtime")
    snapshot = edit(
        planner,
        snapshot,
        action="upsert_technology",
        decision_id="blocked-runtime",
        payload=payload,
    )
    snapshot = edit(
        planner,
        snapshot,
        action="set_module_technology",
        module_id="greeting",
        decision_ids=["blocked-runtime"],
    )
    with pytest.raises(IntegrityError, match="viable options"):
        review(planner, snapshot)
    assert len(planner.store.list_events()) == 1


def test_missing_mandatory_quality_coverage_cannot_be_frozen(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    spec = deepcopy(snapshot["draft"]["modules"]["greeting"]["verification_spec"])
    spec["quality_checks"] = [
        item for item in spec["quality_checks"] if item["standard_rule_ref"]["rule_id"] != "M3"
    ]
    snapshot = edit(
        planner, snapshot, action="set_verification", module_id="greeting", verification_spec=spec
    )
    with pytest.raises(IntegrityError, match="five Commandments"):
        review(planner, snapshot)


@pytest.mark.parametrize(
    "fault", ["module_cycle", "checkpoint_cycle", "missing_coverage", "unknown_provider"]
)
def test_planning_graph_and_coverage_failures_publish_nothing(tmp_path, fault):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    if fault == "module_cycle":
        module = snapshot["draft"]["modules"]["greeting"]
        snapshot = edit(
            planner,
            snapshot,
            action="upsert_module",
            module_id="greeting",
            purpose_and_boundaries=module["purpose_and_boundaries"],
            requirement_ids=["R1"],
            depends_on=["greeting"],
        )
    elif fault in {"checkpoint_cycle", "missing_coverage"}:
        checkpoint = deepcopy(next(iter(snapshot["draft"]["checkpoints"].values())))
        checkpoint["depends_on"] = (
            [checkpoint["checkpoint_id"]] if fault == "checkpoint_cycle" else []
        )
        if fault == "missing_coverage":
            checkpoint["requirement_ids"] = []
        snapshot = edit(planner, snapshot, action="upsert_checkpoint", checkpoint=checkpoint)
    else:
        snapshot = edit(
            planner,
            snapshot,
            action="set_consumed_interfaces",
            module_id="greeting",
            interfaces=[
                {
                    "provider_module_id": "missing-provider",
                    "interface_id": "call",
                    "required_interface_revision": "r1",
                }
            ],
        )
    with pytest.raises(IntegrityError):
        review(planner, snapshot)
    assert len(planner.store.list_events()) == 1


def test_changed_project_base_blocks_frozen_planning(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    old = fixture("project")
    changed = deepcopy(old)
    changed["metadata"].update(
        revision_id="changed-project-r2",
        version=2,
        supersedes=ContractRef.from_document(old).to_json(),
    )
    changed["payload"]["vision"] = "An independently approved changed product vision."
    publish(planner.store, changed)
    with pytest.raises(ConflictError, match="Project Contract changed"):
        review(planner, snapshot)


def test_exact_unchanged_sources_are_reused_for_bounded_checkpoint_replan(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner, second_checkpoint=True)
    frozen = review(planner, snapshot)
    for document in frozen["review"]["documents"]:
        publish(planner.store, document)
    workflow = frozen["review"]["documents"][-1]
    revised = planner.revise(
        ContractRef.from_document(workflow), "A checkpoint dependency is clarified.", actor_id=ACTOR
    )
    with pytest.raises(ConflictError, match="Unchanged"):
        review(planner, revised)
    checkpoints = list(revised["draft"]["checkpoints"].values())
    target = next(item for item in checkpoints if item["checkpoint_id"] == "checkpoint-second")
    target["depends_on"] = [
        item["checkpoint_id"]
        for item in checkpoints
        if item["checkpoint_id"] != "checkpoint-second"
    ]
    revised = edit(planner, revised, action="upsert_checkpoint", checkpoint=target)
    delegated = review(planner, revised, approval_kind="DELEGATED")
    assert [item["metadata"]["contract_type"] for item in delegated["review"]["documents"]] == [
        "WORKFLOW"
    ]
    document = delegated["review"]["documents"][0]
    assert document["metadata"]["supersedes"] == ContractRef.from_document(workflow).to_json()
    assert document["metadata"]["approval"]["kind"] == "DELEGATED"
    assert document["payload"]["modules"] == workflow["payload"]["modules"]
    assert len(planner.store.list_events()) == 4


def test_invalid_edit_does_not_poison_a_resumable_session(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    with pytest.raises(IntegrityError):
        edit(
            planner,
            snapshot,
            action="set_provided_interfaces",
            module_id="greeting",
            interfaces=[{"interface_id": "incomplete"}],
        )
    assert planner.get(snapshot["session_id"])["version"] == snapshot["version"]
    assert planner.assess(snapshot["session_id"])["issues"] == []


def paired_modules(planner):
    snapshot = planner.start(publish(planner.store, fixture("project")), actor_id=ACTOR)
    boundaries = fixture("module")["payload"]["purpose_and_boundaries"]
    for identifier in ("provider", "consumer"):
        snapshot = edit(
            planner,
            snapshot,
            action="upsert_module",
            module_id=identifier,
            purpose_and_boundaries=boundaries,
            requirement_ids=["R1"],
        )
    decision = fixture("technology-decision")["payload"]
    decision["decision_scope"]["module_ids"] = ["provider", "consumer"]
    snapshot = edit(
        planner, snapshot, action="upsert_technology", decision_id="runtime", payload=decision
    )
    for identifier in ("provider", "consumer"):
        snapshot = edit(
            planner,
            snapshot,
            action="set_module_technology",
            module_id=identifier,
            decision_ids=["runtime"],
        )
    snapshot = edit(
        planner,
        snapshot,
        action="set_provided_interfaces",
        module_id="provider",
        interfaces=[
            {
                "interface_id": "greet",
                "interface_revision": "r1",
                "interface_type": "FUNCTION",
                "inputs": ["name: text"],
                "outputs": ["greeting: text"],
                "errors": ["Reject an empty name."],
                "side_effects": [],
                "behavioral_guarantees": ["Return the greeting for the supplied name."],
            }
        ],
    )
    snapshot = edit(
        planner,
        snapshot,
        action="set_consumed_interfaces",
        module_id="consumer",
        interfaces=[
            {
                "provider_module_id": "provider",
                "interface_id": "greet",
                "required_interface_revision": "r1",
            }
        ],
    )
    for identifier, dependencies in (("provider", []), ("consumer", ["provider-step"])):
        snapshot = edit(
            planner,
            snapshot,
            action="upsert_checkpoint",
            checkpoint={
                "checkpoint_id": identifier + "-step",
                "title": identifier + " implementation",
                "objective": "Implement the exact greeting obligation.",
                "module_ids": [identifier],
                "requirement_ids": ["R1"],
                "depends_on": dependencies,
                "deliverables": ["Module implementation, focused tests and user documentation."],
                "completion_criteria": [
                    {
                        "criterion_id": identifier + "-ready",
                        "criterion": "Observe the specified greeting and invalid-input results.",
                    }
                ],
                "verification_plan": ["Run focused tests and review the documented interface."],
            },
        )
    return snapshot


def test_provider_consumer_plan_binds_exact_contract_and_interface_revisions(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = paired_modules(planner)
    frozen = review(planner, snapshot)
    documents = frozen["review"]["documents"]
    assert [item["payload"].get("module_id") for item in documents[1:-1]] == [
        "provider",
        "consumer",
    ]
    provider, consumer = documents[1:3]
    link = consumer["payload"]["consumed_interfaces"][0]
    assert link["provider_contract_ref"] == ContractRef.from_document(provider).to_json()
    assert link["required_interface_revision"] == "r1"
    assert documents[-1]["payload"]["modules"][0]["module_id"] in {"consumer", "provider"}
    row = next(
        item for item in documents[-1]["payload"]["modules"] if item["module_id"] == "consumer"
    )
    assert row["depends_on"] == ["provider"]
    for document in documents:
        publish(planner.store, document)
    assert len(planner.store.list_events()) == 5


def test_checkpoint_cannot_outrun_its_interface_provider(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = paired_modules(planner)
    checkpoint = deepcopy(snapshot["draft"]["checkpoints"]["consumer-step"])
    checkpoint["depends_on"] = []
    snapshot = edit(planner, snapshot, action="upsert_checkpoint", checkpoint=checkpoint)
    with pytest.raises(IntegrityError, match="provider"):
        review(planner, snapshot)


def test_same_interface_revision_cannot_silently_change_its_definition(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = paired_modules(planner)
    frozen = review(planner, snapshot)
    for document in frozen["review"]["documents"]:
        publish(planner.store, document)
    revised = planner.revise(
        ContractRef.from_document(frozen["review"]["documents"][-1]),
        "Clarify an interface.",
        actor_id=ACTOR,
    )
    interfaces = deepcopy(revised["draft"]["modules"]["provider"]["provided_interfaces"])
    interfaces[0]["inputs"] = ["A changed input obligation under the same revision."]
    revised = edit(
        planner,
        revised,
        action="set_provided_interfaces",
        module_id="provider",
        interfaces=interfaces,
    )
    with pytest.raises(IntegrityError, match="cannot be redefined"):
        review(planner, revised)


def test_partial_publication_reuses_only_the_exact_known_committed_sources(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    frozen = review(planner, snapshot)
    technology = frozen["review"]["documents"][0]
    technology_ref = publish(planner.store, technology)
    recovered = deepcopy(frozen)
    recovered.update(
        state="READY_FOR_REVIEW",
        review=None,
        authorization_version=None,
        published_refs=[technology_ref.to_json()],
    )
    recovered = planner.repository.save(
        frozen["session_id"],
        frozen["version"],
        recovered,
        actor_id=ACTOR,
        action="SYNTHETIC_PARTIAL_RECOVERY",
    )
    again = review(planner, recovered)
    assert [item["metadata"]["contract_type"] for item in again["review"]["documents"]] == [
        "MODULE",
        "WORKFLOW",
    ]
    assert again["review"]["documents"][0]["payload"]["technology_decision_refs"] == [
        technology_ref.to_json()
    ]
    for document in again["review"]["documents"]:
        publish(planner.store, document)
    assert len(planner.store.list_events()) == 4
    assert len(planner.store.list_revisions(technology_ref.contract_id)) == 1


def test_an_unrelated_publication_cannot_be_adopted_as_partial_recovery(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    frozen = review(planner, snapshot)
    publish(planner.store, frozen["review"]["documents"][0])
    with pytest.raises(ConflictError, match="identity is already used"):
        review(planner, frozen)


def test_global_constraints_cannot_have_no_owner_even_with_local_explanations(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    module = snapshot["draft"]["modules"]["greeting"]
    snapshot = edit(
        planner,
        snapshot,
        action="upsert_module",
        module_id="greeting",
        purpose_and_boundaries=module["purpose_and_boundaries"],
        requirement_ids=["R1"],
        constraint_ids=[],
        constraint_exemptions={"C1": "Proposed local non-applicability for human review."},
    )
    with pytest.raises(IntegrityError, match="without a responsible module"):
        review(planner, snapshot)


def test_revising_an_existing_plan_preserves_a_valid_milestone_source_order(tmp_path):
    planner = WorkflowPlanner(tmp_path)
    snapshot = ready(planner)
    checkpoint_id = next(iter(snapshot["draft"]["checkpoints"]))
    for identifier, dependencies in (
        ("z-first", []),
        ("a-child", ["z-first"]),
        ("m-independent", []),
    ):
        snapshot = edit(
            planner,
            snapshot,
            action="upsert_milestone",
            milestone={
                "milestone_id": identifier,
                "title": "A planned usable greeting",
                "objective": "Plan the greeting scenario.",
                "depends_on": dependencies,
                "required_checkpoint_ids": [checkpoint_id],
                "test_scope": {"included": ["The greeting scenario"], "excluded": []},
                "test_scenarios": ["Supply Ada and observe the greeting."],
                "readiness_criteria": [
                    {
                        "criterion_id": identifier + "-criterion",
                        "criterion": "All required independent gates have admissible results.",
                    }
                ],
            },
        )
    frozen = review(planner, snapshot)
    documents = deepcopy(frozen["review"]["documents"])
    milestones = {
        item["milestone_id"]: item for item in documents[-1]["payload"]["playtest_milestones"]
    }
    documents[-1]["payload"]["playtest_milestones"] = [
        milestones[key] for key in ("z-first", "a-child", "m-independent")
    ]
    for document in documents:
        publish(planner.store, document)
    revised = planner.revise(
        ContractRef.from_document(documents[-1]), "Inspect an existing valid plan.", actor_id=ACTOR
    )
    with pytest.raises(ConflictError, match="Unchanged"):
        review(planner, revised)
