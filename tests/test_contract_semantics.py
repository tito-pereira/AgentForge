# SPDX-License-Identifier: MPL-2.0

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from nukytera.contracts import ContractRef, IntegrityError, PublishContext, approval_request
from nukytera.contracts.store import ContractStore

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "contracts"
_ORDER = (
    "project",
    "technology-decision",
    "module",
    "workflow",
    "validation",
    "validation-result",
    "evidence-report",
    "project-revision-request",
)


@pytest.fixture
def examples():
    return {
        name: json.loads((_EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
        for name in _ORDER
    }


@pytest.fixture
def store(tmp_path):
    return ContractStore(tmp_path)


def _publish(store, document):
    """Pass a synthetic receipt for this exact test publication."""
    origin = document["metadata"]["provenance"]
    receipt = approval_request(document) if document["metadata"]["approval"] is not None else None
    context = PublishContext(origin["engine"], origin["actor_id"], lambda value: value == receipt)
    return store.publish(document, context=context)


def _seed(store, examples, before):
    for name in _ORDER[: _ORDER.index(before)]:
        _publish(store, examples[name])


def _reject(store, document, message):
    events = store.list_events()
    with pytest.raises(IntegrityError, match=message):
        _publish(store, document)
    assert store.list_events() == events
    assert store.get(ContractRef.from_document(document)) is None


def _next_revision(document):
    revision = deepcopy(document)
    metadata = revision["metadata"]
    metadata.update(
        revision_id=metadata["contract_id"] + "-next",
        version=metadata["version"] + 1,
        supersedes=ContractRef.from_document(document).to_json(),
    )
    if metadata["approval"] is not None:
        metadata["approval"]["approval_id"] += "-next"
    return revision


def test_project_rejects_ambiguous_obligation_ids(store, examples):
    project = examples["project"]
    project["payload"]["success_criteria"][0]["criterion_id"] = "R1"
    _reject(store, project, "ambiguous identifier")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("rank", "consecutive rank"),
        ("selection", "selected technology option"),
        ("driver", "decision driver"),
    ],
)
def test_technology_decision_rejects_invalid_context(store, examples, change, message):
    _seed(store, examples, "technology-decision")
    decision = examples["technology-decision"]
    payload = decision["payload"]
    if change == "rank":
        payload["ai_recommendations"][0]["rank"] = 2
    elif change == "selection":
        payload["selected_option"]["option_id"] = "unlisted-option"
    else:
        payload["decision_drivers"]["source_refs"][0]["obligation_id"] = "unknown-requirement"
    _reject(store, decision, message)


def test_module_rejects_incomplete_standard_checks(store, examples):
    _seed(store, examples, "module")
    module = examples["module"]
    module["payload"]["verification_spec"]["quality_checks"].pop()
    _reject(store, module, "five Commandments")


def _interface_check(revision):
    return {
        "check_id": "greeting-interface",
        "provider_module_id": "provider",
        "interface_id": "greeting-api",
        "interface_revision": revision,
        "criterion": "Verify the greeting input and output for the exact interface revision.",
        "verification_methods": ["TEST"],
        "evidence_required": ["Contract test result"],
        "blocking": True,
    }


def _provider(examples):
    provider = deepcopy(examples["module"])
    provider["metadata"].update(contract_id="provider", revision_id="provider-first")
    provider["metadata"]["approval"] = {
        "kind": "HUMAN",
        "approval_id": "provider-approval",
        "actor_id": "demo-owner",
    }
    payload = provider["payload"]
    payload.update(module_id="provider", technology_decision_refs=[])
    payload["provided_interfaces"] = [
        {
            "interface_id": "greeting-api",
            "interface_revision": "first",
            "interface_type": "FUNCTION",
            "inputs": ["Name as text"],
            "outputs": ["Greeting as text"],
        }
    ]
    payload["verification_spec"]["interface_checks"] = [_interface_check("first")]
    return provider


def test_interface_revision_cannot_be_redefined_or_used_as_another_revision(store, examples):
    _seed(store, examples, "module")
    provider = _provider(examples)
    provider_ref = _publish(store, provider)
    revision = _next_revision(provider)
    revision["payload"]["provided_interfaces"][0]["outputs"] = ["Greeting as an integer"]
    _reject(store, revision, "interface revision cannot be redefined")

    consumer = examples["module"]
    consumer["metadata"]["approval"] = {
        "kind": "HUMAN",
        "approval_id": "consumer-approval",
        "actor_id": "demo-owner",
    }
    consumer["payload"]["consumed_interfaces"] = [
        {
            "provider_module_id": "provider",
            "provider_contract_ref": provider_ref.to_json(),
            "interface_id": "greeting-api",
            "required_interface_revision": "unknown",
        }
    ]
    consumer["payload"]["verification_spec"]["interface_checks"] = [_interface_check("unknown")]
    _reject(store, consumer, "provider interface revision")
    consumer["payload"]["consumed_interfaces"][0]["required_interface_revision"] = "first"
    consumer["payload"]["verification_spec"]["interface_checks"] = [_interface_check("first")]
    assert _publish(store, consumer) == ContractRef.from_document(consumer)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("depends_on", ["greet"], "Circular checkpoint"),
        ("depends_on", ["unknown-checkpoint"], "checkpoint dependency"),
        ("module_ids", ["unknown-module"], "checkpoint module"),
        ("requirement_ids", ["unknown-requirement"], "checkpoint requirement"),
        ("requirement_ids", [], "omit approved global requirements"),
    ],
)
def test_workflow_rejects_invalid_checkpoint_graph(store, examples, field, value, message):
    _seed(store, examples, "workflow")
    workflow = examples["workflow"]
    workflow["payload"]["checkpoints"][0][field] = value
    _reject(store, workflow, message)


def test_workflow_rejects_missing_binding_decision(store, examples):
    _seed(store, examples, "workflow")
    workflow = examples["workflow"]
    workflow["payload"]["technology_decisions"] = []
    _reject(store, workflow, "exact approved technology decisions")


def test_milestone_cannot_depend_on_a_later_milestone(store, examples):
    _seed(store, examples, "workflow")
    workflow = examples["workflow"]
    workflow["metadata"]["approval"] = {
        "kind": "HUMAN",
        "approval_id": "milestone-plan-approval",
        "actor_id": "demo-owner",
    }
    first = {
        "milestone_id": "early",
        "title": "Early playtest",
        "objective": "Review the first local greeting.",
        "depends_on": ["later"],
        "required_checkpoint_ids": ["greet"],
        "test_scope": {"included": ["Local greeting"], "excluded": []},
        "test_scenarios": ["Run the greeting for Ada."],
        "readiness_criteria": [{"criterion_id": "milestone-one", "criterion": "Greeting runs."}],
    }
    second = deepcopy(first)
    second.update(milestone_id="later", title="Later playtest", depends_on=[])
    second["readiness_criteria"][0]["criterion_id"] = "milestone-two"
    workflow["payload"]["playtest_milestones"] = [first, second]
    _reject(store, workflow, "earlier milestone dependency")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("revision_id", "missing-revision", "could not be resolved"),
        ("project_id", "unrelated-project", "project boundary"),
    ],
)
def test_publication_rejects_bad_exact_references(store, examples, field, value, message):
    _seed(store, examples, "workflow")
    workflow = examples["workflow"]
    workflow["payload"]["project_contract_ref"][field] = value
    _reject(store, workflow, message)


def test_workflow_retains_unchanged_module_and_rejects_changed_obligation(store, examples):
    _seed(store, examples, "workflow")
    original_project = examples["project"]
    new_project = _next_revision(original_project)
    new_project["payload"]["vision"] += " Document the setup."
    new_project_ref = _publish(store, new_project)
    workflow = examples["workflow"]
    workflow["payload"]["project_contract_ref"] = new_project_ref.to_json()
    _publish(store, workflow)
    assert store.get(ContractRef.from_document(examples["module"])) == examples["module"]

    changed_project = _next_revision(new_project)
    changed_project["metadata"]["revision_id"] += "-again"
    changed_project["payload"]["requirements"][0]["description"] += " Use a different result."
    changed_ref = _publish(store, changed_project)
    updated_workflow = _next_revision(workflow)
    updated_workflow["metadata"]["approval"] = {
        "kind": "HUMAN",
        "approval_id": "reconciled-workflow-approval",
        "actor_id": "demo-owner",
    }
    updated_workflow["payload"]["project_contract_ref"] = changed_ref.to_json()
    _reject(store, updated_workflow, "changed or removed Project obligation")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing-check", "omits mandatory"),
        ("downgrade", "downgrade a mandatory"),
        ("missing-workflow", "active Workflow Contract"),
        ("weak-evidence", "required evidence kind"),
    ],
)
def test_validation_plan_rejects_missing_or_weakened_obligations(store, examples, change, message):
    _seed(store, examples, "validation")
    plan = examples["validation"]
    payload = plan["payload"]
    matrix = payload["verification_matrix"]
    if change == "missing-check":
        matrix.pop(0)
    elif change == "downgrade":
        matrix[0]["gate_classification"] = "OPTIONAL"
    elif change == "missing-workflow":
        payload["source_contract_refs"] = [
            item for item in payload["source_contract_refs"] if item["contract_type"] != "WORKFLOW"
        ]
    else:
        module_check = next(item for item in matrix if item["check_id"] == "verify-greeting-req")
        module_check["required_evidence"] = ["Different evidence kind"]
    _reject(store, plan, message)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("gate", "Gate assessment contradicts"),
        ("missing-check", "each exact plan check"),
        ("mandatory-na", "cannot be marked not applicable"),
        ("untrusted-evaluator", "trusted Validation publisher"),
        ("implementation-evaluator", "implementation publisher as evaluator"),
        ("before-plan", "starts before its exact plan"),
        ("future-run", "after result publication"),
    ],
)
def test_validation_result_rejects_fabricated_progress(store, examples, change, message):
    _seed(store, examples, "validation-result")
    result = examples["validation-result"]
    payload = result["payload"]
    if change == "gate":
        payload["gate_assessment"]["state"] = "SATISFIED"
    elif change == "missing-check":
        payload["check_results"].pop()
    elif change == "mandatory-na":
        payload["check_results"][0].update(
            status=None, not_applicable_reason="A claimed exception."
        )
    elif change == "untrusted-evaluator":
        payload["target_and_execution"]["evaluator_ref"] = "untrusted-evaluator"
    elif change == "before-plan":
        payload["target_and_execution"]["started_at"] = "2025-12-31T00:00:00Z"
    elif change == "future-run":
        payload["target_and_execution"]["started_at"] = "2026-01-02T00:00:00Z"
    else:
        actor = examples["workflow"]["metadata"]["provenance"]["actor_id"]
        result["metadata"]["provenance"]["actor_id"] = actor
        payload["target_and_execution"]["evaluator_ref"] = actor
    _reject(store, result, message)


def _completed_result(examples, directory):
    result = deepcopy(examples["validation-result"])
    payload = result["payload"]
    plan = examples["validation"]["payload"]
    execution = payload["target_and_execution"]
    execution.update(status="COMPLETED", finished_at=execution["started_at"])
    execution["artifact_identity"]["commit"] = "a" * 40
    directory.mkdir(parents=True, exist_ok=True)
    checks = {item["check_id"]: item for item in plan["verification_matrix"]}
    for check_result in payload["check_results"]:
        check_result["status"] = "CONFORMANT"
        planned = checks[check_result["check_id"]]
        for kind in planned["required_evidence"]:
            identifier = f"proof-{len(payload['evidence_refs'])}"
            filename = f"{identifier}.txt"
            data = f"Synthetic evidence {identifier} for {planned['check_id']} and {kind}.".encode()
            (directory / filename).write_bytes(data)
            payload["evidence_refs"].append(
                {
                    "evidence_id": identifier,
                    "check_id": planned["check_id"],
                    "source_ref": deepcopy(planned["source_ref"]),
                    "artifact_identity": deepcopy(execution["artifact_identity"]),
                    "execution_context": {
                        "validation_run_id": execution["validation_run_id"],
                        "validation_plan_ref": payload["validation_plan_ref"],
                    },
                    "evidence_kind": kind,
                    "verification_method": planned["verification_method"],
                    "evaluator_ref": execution["evaluator_ref"],
                    "path": filename,
                    "sha256": sha256(data).hexdigest(),
                }
            )
            check_result["evidence_ids"].append(identifier)
    payload["coverage_summary"].update(
        covered_check_ids=list(checks), unverified_check_ids=[], sufficient=True
    )
    payload["gate_assessment"].update(state="SATISFIED", blocking_check_ids=[])
    return result


def _relabelled_run(first):
    replay = deepcopy(first)
    replay["metadata"].update(contract_id="replay-result", revision_id="replay-result-first")
    payload = replay["payload"]
    payload["target_and_execution"]["validation_run_id"] = "replay-run"
    for evidence in payload["evidence_refs"]:
        evidence["evidence_id"] += "-relabelled"
        evidence["execution_context"]["validation_run_id"] = "replay-run"
    for check in payload["check_results"]:
        check["evidence_ids"] = [identifier + "-relabelled" for identifier in check["evidence_ids"]]
    return replay


def test_validation_cannot_reuse_evidence_for_a_new_artifact(store, examples, tmp_path):
    _seed(store, examples, "validation-result")
    first = _completed_result(examples, tmp_path / ".nukytera" / "artifacts")
    wrong_target = deepcopy(first)
    wrong_target["payload"]["target_and_execution"]["artifact_identity"]["commit"] = "b" * 40
    _reject(store, wrong_target, "different validation run, plan, or artifact")
    first_ref = _publish(store, first)
    assert store.get(first_ref) == first

    replay = _relabelled_run(first)
    replay["payload"]["target_and_execution"]["artifact_identity"]["commit"] = "b" * 40
    for evidence in replay["payload"]["evidence_refs"]:
        evidence["artifact_identity"]["commit"] = "b" * 40
    _reject(store, replay, "Historical evidence cannot be reused")


def test_published_evidence_path_cannot_be_rebound_to_a_new_digest(store, examples, tmp_path):
    _seed(store, examples, "validation-result")
    directory = tmp_path / ".nukytera" / "artifacts"
    first = _completed_result(examples, directory)
    first_ref = _publish(store, first)
    replay = _relabelled_run(first)
    evidence = replay["payload"]["evidence_refs"][0]
    evidence["path"] = evidence["path"].upper()
    data = b"Different evidence contents at the retained path."
    (directory / evidence["path"]).write_bytes(data)
    evidence["sha256"] = sha256(data).hexdigest()
    _reject(store, replay, "evidence path is already bound to a different digest")
    assert store.get(first_ref) == first


def test_nonconformant_mandatory_check_blocks_gate_despite_complete_evidence(
    store, examples, tmp_path
):
    _seed(store, examples, "validation-result")
    result = _completed_result(examples, tmp_path / ".nukytera" / "artifacts")
    check = result["payload"]["check_results"][0]
    check["status"] = "NONCONFORMANT"
    _reject(store, result, "Gate assessment contradicts")
    result["payload"]["gate_assessment"].update(
        state="BLOCKED", blocking_check_ids=[check["check_id"]]
    )
    assert _publish(store, result) == ContractRef.from_document(result)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("invented-gate", "without a matching satisfied gate"),
        ("different-build", "another build or artifact"),
        ("invented-decision", "reported decision or approval"),
    ],
)
def test_report_cannot_rewrite_its_sources(store, examples, change, message):
    _seed(store, examples, "evidence-report")
    report = examples["evidence-report"]
    payload = report["payload"]
    if change == "invented-gate":
        payload["version_and_delivery_lineage"]["technical_validation"] = "VALIDATED"
    elif change == "different-build":
        payload["report_scope"]["target_id"] = "another-snapshot"
    else:
        payload["decisions_and_change_history"]["decision_ids"] = ["invented-approval"]
    _reject(store, report, message)


def test_report_cannot_reuse_a_gate_for_a_different_project_revision(store, examples):
    _seed(store, examples, "evidence-report")
    updated = _next_revision(examples["project"])
    updated["payload"]["requirements"][0]["description"] += " Use a different result."
    updated_ref = _publish(store, updated)
    report = examples["evidence-report"]
    sources = report["payload"]["source_refs"]
    original = sources[0]
    sources[0] = updated_ref.to_json()
    _reject(store, report, "without a matching source result")
    sources[0] = original
    assert _publish(store, report) == ContractRef.from_document(report)


def test_report_metric_requires_declared_source(store, examples):
    _seed(store, examples, "evidence-report")
    report = examples["evidence-report"]
    report["payload"]["risks_metrics_and_next_actions"]["metrics"] = [
        {
            "name": "Recorded implementation language decisions",
            "definition": "Count of decisions in the chosen snapshot.",
            "value": 1,
            "denominator": 1,
            "source_ref": ContractRef.from_document(examples["technology-decision"]).to_json(),
        }
    ]
    _reject(store, report, "report metric source")


def test_report_cannot_accept_an_undelivered_version(store, examples):
    _seed(store, examples, "evidence-report")
    report = examples["evidence-report"]
    report["metadata"]["approval"] = {
        "kind": "HUMAN",
        "approval_id": "acceptance-proof",
        "actor_id": "demo-owner",
    }
    report["payload"]["version_and_delivery_lineage"]["acceptance"] = "ACCEPTED"
    report["payload"]["feedback_and_acceptance"]["review_approval_id"] = "acceptance-proof"
    _reject(store, report, "requires a delivered version")


def test_revision_request_rejects_stale_base_without_mutating_project(store, examples):
    _seed(store, examples, "project-revision-request")
    project = _next_revision(examples["project"])
    project["payload"]["vision"] += " Add approved documentation."
    active = _publish(store, project)
    _reject(store, examples["project-revision-request"], "no longer active")
    assert store.resolve_active(active.contract_id) == project
