# SPDX-License-Identifier: MPL-2.0
"""Explicit synthetic snapshots exercise composition, not production certification."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from corinthos.contracts import (
    ContractRef,
    ContractStore,
    IntegrityError,
    PublishContext,
    validate_schema,
)
from corinthos.contracts.model import canonical_json
from corinthos.contracts.semantics import validate_semantics
from corinthos.report.composition import compose
from corinthos.report.rendering import safe_prose
from corinthos.report.service import ReportService

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples/contracts"


def _load(name):
    return json.loads((_EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def _ref(document):
    return ContractRef.from_document(document).to_json()


@pytest.fixture
def snapshot():
    documents = [
        _load(name)
        for name in (
            "project",
            "technology-decision",
            "module",
            "workflow",
            "validation",
            "validation-result",
        )
    ]
    project, _, _, _, plan, result = documents
    return {
        "project": project,
        "documents": documents,
        "active": {
            document["metadata"]["contract_id"]: _ref(document) for document in documents[:-1]
        },
        "selected_results": [result],
        "supporting_results": [],
        "gates": [
            {
                "plan_ref": _ref(plan),
                "result_ref": _ref(result),
                "recorded_state": "BLOCKED",
                "eligibility": "BLOCKED",
                "reason": "The explicitly synthetic interrupted source retains a blocked gate.",
            }
        ],
        "evidence": [],
        "operations": [],
        "gaps": [],
        "artifact_identity": {"snapshot_id": "demo-snapshot"},
        "as_of": "2026-01-02T00:00:00+00:00",
        "captured_at": "2026-01-02T00:00:00+00:00",
        "mode": "CURRENT",
        "watermark": "synthetic-watermark",
        "manifest": {},
    }


def _wrapped(payload):
    document = _load("evidence-report")
    document["metadata"]["created_at"] = "2026-01-03T00:00:00+00:00"
    document["metadata"]["provenance"]["source"] = "Explicit synthetic report composition test"
    document["payload"] = payload
    return document


def _verify(payload, snapshot):
    document = _wrapped(payload)
    validate_schema(document)
    documents = {ContractRef.from_document(item): item for item in snapshot["documents"]}
    validate_semantics(
        document,
        documents.get,
        lambda identifier: next(
            (item for ref, item in documents.items() if ref.contract_id == identifier), None
        ),
        history=lambda *_: list(documents.values()),
        verify_artifact=lambda *_: None,  # Synthetic trusted observation, never production proof.
    )


@pytest.mark.parametrize("kind", ["CHECKPOINT", "MILESTONE", "PRODUCT", "HISTORY", "EVOLUTION"])
def test_five_kinds_compose_the_existing_wire_shape_and_exact_gate(kind, snapshot):
    request = {"kind": kind}
    plan = snapshot["documents"][-2]
    if kind == "CHECKPOINT":
        request["checkpoint_ids"] = ["CP1"]
        plan["payload"]["validation_scope"].update(
            level="CHECKPOINT",
            target_ids=["CP1"],
            target_contract_ref=_ref(snapshot["documents"][3]),
        )
        plan["payload"]["gate_policy"]["gate"] = "CHECKPOINT"
    elif kind == "MILESTONE":
        request["milestone_id"] = "milestone-1"
        plan["payload"]["validation_scope"].update(
            level="PLAYTEST_MILESTONE",
            target_ids=["milestone-1"],
            target_contract_ref=_ref(snapshot["documents"][3]),
        )
        plan["payload"]["gate_policy"]["gate"] = "PLAYTEST_READINESS"
    before = canonical_json(snapshot)
    payload = compose(snapshot, request)
    assert len(payload) == 9
    assert payload["version_and_delivery_lineage"]["technical_validation"] == "BLOCKED"
    assert payload["version_and_delivery_lineage"]["acceptance"] == "NOT_REVIEWED"
    assert payload["feedback_and_acceptance"] == {"review_approval_id": None, "feedback": []}
    assert canonical_json(snapshot) == before
    _verify(payload, snapshot)


def test_no_result_report_explains_gaps_without_inventing_product_identity(snapshot):
    snapshot.update(selected_results=[], gates=[], evidence=[])
    payload = compose(snapshot, {"kind": "PRODUCT"})
    lineage = payload["version_and_delivery_lineage"]
    assert lineage["technical_validation"] == "NOT_VERIFIED"
    assert lineage["product_version"] == "UNRECORDED"
    assert lineage["delivery"] == "NOT_DELIVERED" and lineage["availability"] is False
    assert payload["execution_and_validation_digest"]["validation_result_refs"] == []
    assert payload["risks_metrics_and_next_actions"]["metrics"] == []
    assert all(value["gaps"] for value in payload["engineering_quality_and_documentation"].values())
    _verify(payload, snapshot)


def test_individual_checkpoint_results_cannot_cover_a_combined_report(snapshot):
    plan = snapshot["documents"][-2]
    plan["payload"]["validation_scope"].update(
        level="CHECKPOINT", target_ids=["CP1"], target_contract_ref=_ref(snapshot["documents"][3])
    )
    with pytest.raises(IntegrityError, match="exact gate scope"):
        compose(snapshot, {"kind": "CHECKPOINT", "checkpoint_ids": ["CP1", "CP2"]})


@pytest.mark.parametrize("change", ["project", "artifact", "source_revision"])
def test_incompatible_digest_sources_are_rejected(change, snapshot):
    result = snapshot["selected_results"][0]
    if change == "project":
        result["metadata"]["project_id"] = "another-project"
    elif change == "artifact":
        result["payload"]["target_and_execution"]["artifact_identity"]["snapshot_id"] = (
            "other-snapshot"
        )
    else:
        plan = snapshot["documents"][-2]
        old_project = deepcopy(snapshot["project"])
        old_project["metadata"]["revision_id"] = "old-project-r1"
        snapshot["documents"].append(old_project)
        plan["payload"]["source_contract_refs"][0] = _ref(old_project)
    with pytest.raises(IntegrityError):
        compose(snapshot, {"kind": "PRODUCT"})


def test_different_candidate_history_retains_its_own_identity_outside_the_digest(snapshot):
    old = deepcopy(snapshot["selected_results"][0])
    old["metadata"].update(contract_id="historic-result", revision_id="historic-result-r1")
    old["payload"]["target_and_execution"].update(
        validation_run_id="historic-run", artifact_identity={"snapshot_id": "faulty-snapshot"}
    )
    snapshot["documents"].append(old)
    payload = compose(snapshot, {"kind": "HISTORY"})
    assert payload["execution_and_validation_digest"]["validation_result_refs"] == [
        _ref(snapshot["selected_results"][0])
    ]
    history = payload["decisions_and_change_history"]
    assert _ref(old) in history["change_refs"]
    assert any("faulty-snapshot" in note and "historic-run" in note for note in history["notes"])
    _verify(payload, snapshot)


def test_current_inadmissibility_is_unverified_without_invented_validation_blockers(snapshot):
    result = snapshot["selected_results"][0]
    result["payload"]["gate_assessment"].update(state="SATISFIED", blocking_check_ids=[])
    snapshot["gates"][0].update(
        recorded_state="SATISFIED",
        eligibility="NOT_VERIFIED",
        reason="A required proof is unavailable.",
    )
    payload = compose(snapshot, {"kind": "PRODUCT"})
    assert payload["version_and_delivery_lineage"]["technical_validation"] == "NOT_VERIFIED"
    assert payload["execution_and_validation_digest"]["blocked_check_ids"] == []
    assert "A required proof is unavailable." in payload["risks_metrics_and_next_actions"]["risks"]
    _verify(payload, snapshot)


def _add_commandment_evidence(snapshot):
    result = snapshot["selected_results"][0]
    check = next(
        item
        for item in result["payload"]["check_results"]
        if item["check_id"] == "verify-greeting-M3"
    )
    evidence = {
        "evidence_id": "synthetic-M3-evidence",
        "evidence_kind": "Independent review record",
        "check_id": check["check_id"],
        "source_ref": deepcopy(check["source_ref"]),
        "artifact_identity": deepcopy(snapshot["artifact_identity"]),
        "execution_context": {
            "validation_run_id": result["payload"]["target_and_execution"]["validation_run_id"],
            "validation_plan_ref": result["payload"]["validation_plan_ref"],
        },
        "verification_method": check["verification_method"],
        "evaluator_ref": "demo-validation",
        "path": "synthetic/evidence.txt",
        "sha256": "0" * 64,
    }
    check.update(
        status="NONCONFORMANT",
        evidence_ids=[evidence["evidence_id"]],
        rationale="The synthetic edge case contradicts the exact obligation.",
    )
    result["payload"]["evidence_refs"] = [evidence]
    snapshot["evidence"] = [
        {"ref": evidence, "state": "VERIFIED", "reason": "Synthetic verified source."}
    ]
    return evidence


def test_commandments_use_exact_module_mapping_and_show_adverse_outcomes(snapshot):
    evidence = _add_commandment_evidence(snapshot)
    payload = compose(snapshot, {"kind": "PRODUCT"})
    observation = payload["engineering_quality_and_documentation"]["M3"]
    assert observation["evidence_ids"] == [evidence["evidence_id"]]
    assert any("NONCONFORMANT" in gap for gap in observation["gaps"])
    assert payload["artifact_and_evidence_index"] == [evidence]
    _verify(payload, snapshot)


def test_wrong_commandment_evidence_cannot_be_silently_reassigned(snapshot):
    evidence = _add_commandment_evidence(snapshot)
    evidence["source_ref"] = {
        "standard_rule_ref": {"standard_id": "nukytera-standard", "version": "0.1", "rule_id": "M1"}
    }
    with pytest.raises(IntegrityError, match="different sources"):
        compose(snapshot, {"kind": "PRODUCT"})


def test_metrics_keep_actual_vrc_denominators_and_no_universal_quality_score(snapshot):
    payload = compose(snapshot, {"kind": "PRODUCT"})
    metrics = payload["risks_metrics_and_next_actions"]["metrics"]
    result = snapshot["selected_results"][0]
    count = len(result["payload"]["check_results"])
    assert all(
        item["source_ref"] == _ref(result) and item["denominator"] == count for item in metrics
    )
    assert next(item for item in metrics if item["name"] == "not_verified_checks")["value"] == count
    assert not any("quality" in item["name"] or "token" in item["name"] for item in metrics)


def test_optional_nonapplicability_remains_visible_in_its_actual_denominator(snapshot):
    check = snapshot["selected_results"][0]["payload"]["check_results"][0]
    check.update(status=None, not_applicable_reason="Explicit synthetic optional nonapplicability.")
    metrics = compose(snapshot, {"kind": "PRODUCT"})["risks_metrics_and_next_actions"]["metrics"]
    metric = next(item for item in metrics if item["name"] == "not_applicable_checks")
    assert metric["value"] == 1
    assert metric["denominator"] == len(snapshot["selected_results"][0]["payload"]["check_results"])


def test_delivery_and_availability_require_provenance_and_preserve_acceptance(snapshot):
    snapshot["delivery"] = {
        "product_version": "1.2",
        "delivery": "DELIVERED",
        "availability": True,
        "previous_version": "1.1",
        "provenance": {"record_sha256": "1" * 64},
        "gaps": [],
    }
    payload = compose(snapshot, {"kind": "PRODUCT"})
    lineage = payload["version_and_delivery_lineage"]
    assert lineage["product_version"] == "1.2" and lineage["delivery"] == "DELIVERED"
    assert lineage["technical_validation"] == "BLOCKED" and lineage["acceptance"] == "NOT_REVIEWED"
    snapshot["delivery"]["provenance"] = None
    with pytest.raises(IntegrityError, match="provenance"):
        compose(snapshot, {"kind": "PRODUCT"})


def test_requests_cannot_invent_acceptance_or_feedback(snapshot):
    for field, value in (("acceptance", "ACCEPTED"), ("feedback", [{"feedback_id": "invented"}])):
        with pytest.raises(IntegrityError, match="authority claims"):
            compose(snapshot, {"kind": "PRODUCT", field: value})


def test_projected_prose_redacts_secrets_paths_and_preserves_recovery_facts(snapshot):
    snapshot["operations"] = [
        {
            "type": "WORKFLOW_EVENT",
            "kind": "CHECKS_COMPLETED",
            "sequence": 7,
            "details": {
                "summary": "password=hunter2",
                "checks": [{"observed_log_summary": {"unittest_tests": 20}}],
            },
        }
    ]
    snapshot["gaps"] = ["Investigate C:\\Users\\Example\\private.log"]
    payload = compose(snapshot, {"kind": "PRODUCT", "objective": "token=abcdefghijk secret=hidden"})
    text = canonical_json(payload)
    assert "hunter2" not in text and "abcdefghijk" not in text and "hidden" not in text
    assert "C:\\\\Users" not in text
    assert "unittest_tests" in text and "20" in text


def test_capture_clock_does_not_create_unrelated_content_changes(snapshot):
    first = compose(snapshot, {"kind": "PRODUCT"})
    snapshot["as_of"] = "2026-01-02T01:00:00+00:00"
    snapshot["captured_at"] = snapshot["as_of"]
    second = compose(snapshot, {"kind": "PRODUCT"})
    second["report_scope"]["as_of"] = first["report_scope"]["as_of"]
    assert first == second


def test_versioned_documentation_has_source_identity_without_becoming_validation_evidence(snapshot):
    snapshot["manifest"]["candidate"] = {
        "inventory": {"files": {"docs/storage.md": {"sha256": "9" * 64, "size": 200}}}
    }
    payload = compose(snapshot, {"kind": "PRODUCT"})
    notes = payload["decisions_and_change_history"]["notes"]
    assert any("docs/storage.md" in note and "9" * 64 in note for note in notes)
    assert payload["artifact_and_evidence_index"] == []


def test_effective_result_facts_and_full_candidate_identity_are_visible(snapshot):
    snapshot["artifact_identity"]["commit"] = "1" * 40
    result = snapshot["selected_results"][0]
    execution = result["payload"]["target_and_execution"]
    execution["artifact_identity"] = deepcopy(snapshot["artifact_identity"])
    execution["finished_at"] = "2026-01-01T00:00:01+00:00"
    payload = compose(snapshot, {"kind": "PRODUCT"})
    assert canonical_json(snapshot["artifact_identity"]) in " ".join(
        payload["report_scope"]["boundaries"]
    )
    notes = " ".join(payload["decisions_and_change_history"]["notes"])
    assert "Effective VRC" in notes and execution["validation_run_id"] in notes
    assert result["metadata"]["created_at"] in notes
    assert execution["started_at"] in notes and execution["finished_at"] in notes
    assert execution["status"] in notes and "scope PRODUCT" in notes


def test_executable_check_observations_are_not_pooled_or_called_independent_processes(snapshot):
    _add_commandment_evidence(snapshot)
    snapshot["evidence"][0]["observation"] = {
        "command_backed": True,
        "command_shared": True,
        "review_observed": True,
    }
    payload = compose(snapshot, {"kind": "PRODUCT"})
    notes = " ".join(payload["decisions_and_change_history"]["notes"])
    count = len(snapshot["selected_results"][0]["payload"]["check_results"])
    assert f"1/{count} checks with command-backed observations" in notes
    assert "explicitly shared same-run command observations is 1" in notes
    assert "not a count of independent command executions" in notes


def test_recorded_revision_request_keeps_typed_ref_and_source_backed_inconsistency(snapshot):
    request = _load("project-revision-request")
    snapshot["documents"].append(request)
    payload = compose(snapshot, {"kind": "HISTORY"})
    history = payload["decisions_and_change_history"]
    assert _ref(request) in payload["source_refs"] and _ref(request) in history["change_refs"]
    notes = " ".join(history["notes"])
    assert request["payload"]["request_id"] in notes
    assert request["payload"]["inconsistencies"][0]["description"] in notes
    assert request["payload"]["inconsistencies"][0]["uncertainties"][0] in notes
    assert "approval or adoption is not inferred" in notes
    assert payload["version_and_delivery_lineage"]["acceptance"] == "NOT_REVIEWED"
    _verify(payload, snapshot)


def test_conflicting_contract_revisions_remain_hashed_history_outside_gate_sources(snapshot):
    historical = []
    for current in snapshot["documents"][:4]:
        old = deepcopy(current)
        old["metadata"].update(
            revision_id=current["metadata"]["revision_id"] + "-older",
            created_at="2025-12-31T00:00:00Z",
        )
        current["metadata"].update(version=2, supersedes=_ref(old))
        historical.append(old)
    historical[0]["payload"]["negotiated_decisions"][0].update(
        decision_id="earlier-owner-decision", decision="Keep the recorded earlier project choice."
    )
    historical[0]["metadata"]["approval"]["approval_id"] = "earlier-human-publication"
    snapshot["documents"].extend(historical)
    payload = compose(snapshot, {"kind": "EVOLUTION"})
    notes = " ".join(payload["decisions_and_change_history"]["notes"])
    for document in historical:
        assert _ref(document) not in payload["source_refs"]
        assert canonical_json(_ref(document)) in notes
        assert sha256(canonical_json(document).encode("utf-8")).hexdigest() in notes
    assert "earlier-owner-decision" in notes and "earlier-human-publication" in notes
    assert "Keep the recorded earlier project choice." in notes
    assert "supersedes" in notes and "2025-12-31T00:00:00Z" in notes
    assert payload["version_and_delivery_lineage"]["technical_validation"] == "BLOCKED"
    _verify(payload, snapshot)


def test_revision_request_revisions_are_all_readable_but_only_latest_is_typed(snapshot):
    earlier = _load("project-revision-request")
    latest = deepcopy(earlier)
    latest["metadata"].update(revision_id="demo-request-r2", version=2, supersedes=_ref(earlier))
    latest["payload"]["inconsistencies"][0]["description"] = "Updated recorded conflict."
    snapshot["documents"].extend([latest, earlier])
    payload = compose(snapshot, {"kind": "HISTORY"})
    assert _ref(latest) in payload["source_refs"] and _ref(earlier) not in payload["source_refs"]
    notes = " ".join(payload["decisions_and_change_history"]["notes"])
    assert canonical_json(_ref(earlier)) in notes and canonical_json(_ref(latest)) in notes
    assert "Updated recorded conflict." in notes
    _verify(payload, snapshot)


def test_revision_history_prose_is_safe_while_exact_references_remain_unchanged(snapshot):
    request = _load("project-revision-request")
    request["payload"]["inconsistencies"][0]["description"] = "token=privatecredential123"
    snapshot["documents"].append(request)
    payload = compose(snapshot, {"kind": "HISTORY"})
    assert "privatecredential123" not in canonical_json(payload)
    assert _ref(request) in payload["source_refs"]


@pytest.mark.parametrize("acceptance", ["ACCEPTED", "WITH_RESERVATIONS"])
def test_prior_human_report_review_is_frozen_history_not_new_acceptance(acceptance, snapshot):
    reviewed = _load("evidence-report")
    reviewed["metadata"]["approval"] = {
        "kind": "HUMAN",
        "approval_id": "prior-exact-review",
        "actor_id": "prior-owner",
    }
    reviewed["payload"]["version_and_delivery_lineage"].update(
        acceptance=acceptance, delivery="DELIVERED", product_version="prior-product-version"
    )
    reviewed["payload"]["report_scope"]["target_id"] = "prior-candidate-snapshot"
    reviewed["payload"]["feedback_and_acceptance"] = {
        "review_approval_id": "prior-exact-review",
        "feedback": [
            {
                "feedback_id": "prior-feedback",
                "build_id": "prior-build",
                "milestone_id": "prior-milestone",
                "status": "Owner retained the recorded reservation.",
            }
        ],
    }
    snapshot["review_documents"] = [reviewed]
    payload = compose(snapshot, {"kind": "HISTORY"})
    notes = " ".join(payload["decisions_and_change_history"]["notes"])
    assert canonical_json(_ref(reviewed)) in notes
    assert sha256(canonical_json(reviewed).encode("utf-8")).hexdigest() in notes
    assert all(
        value in notes
        for value in (
            acceptance,
            "prior-exact-review",
            "prior-product-version",
            "prior-candidate-snapshot",
            "prior-feedback",
        )
    )
    assert payload["version_and_delivery_lineage"]["acceptance"] == "NOT_REVIEWED"
    assert payload["version_and_delivery_lineage"]["product_version"] == "UNRECORDED"
    assert payload["feedback_and_acceptance"] == {"review_approval_id": None, "feedback": []}
    assert "prior-exact-review" not in payload["decisions_and_change_history"]["decision_ids"]
    assert not any(
        "No supported Feedback Tracker" in risk
        for risk in payload["risks_metrics_and_next_actions"]["risks"]
    )
    _verify(payload, snapshot)


@pytest.mark.parametrize("change", ["authority", "review_id", "acceptance", "project"])
def test_inexact_or_unreviewed_report_cannot_become_human_review_history(change, snapshot):
    reviewed = _load("evidence-report")
    reviewed["metadata"]["approval"] = {
        "kind": "HUMAN",
        "approval_id": "prior-exact-review",
        "actor_id": "prior-owner",
    }
    reviewed["payload"]["version_and_delivery_lineage"].update(
        acceptance="ACCEPTED", delivery="DELIVERED"
    )
    reviewed["payload"]["feedback_and_acceptance"]["review_approval_id"] = "prior-exact-review"
    if change == "authority":
        reviewed["metadata"]["approval"]["kind"] = "DELEGATED"
    elif change == "review_id":
        reviewed["payload"]["feedback_and_acceptance"]["review_approval_id"] = "another-review"
    elif change == "acceptance":
        reviewed["payload"]["version_and_delivery_lineage"]["acceptance"] = "NOT_REVIEWED"
    else:
        reviewed["metadata"]["project_id"] = "another-project"
    snapshot["review_documents"] = [reviewed]
    with pytest.raises(IntegrityError, match="recorded human authority"):
        compose(snapshot, {"kind": "HISTORY"})


def test_valid_long_source_decision_generates_a_bounded_frozen_report(tmp_path):
    project = _load("project")
    project["payload"]["negotiated_decisions"][0]["rationale"] = (
        "A valid lengthy project rationale. " * 160
    )
    store = ContractStore(tmp_path)
    provenance = project["metadata"]["provenance"]
    reference = store.publish(
        project,
        context=PublishContext(
            provenance["engine"],
            provenance["actor_id"],
            verify_approval=lambda _: True,  # Explicit synthetic exact-publication fixture.
        ),
    )
    service = ReportService(store)
    draft = service.generate(reference, artifact_identity={"snapshot_id": "synthetic-candidate"})
    notes = draft["document"]["payload"]["decisions_and_change_history"]["notes"]
    assert all(safe_prose(note) == note for note in notes)
    assert any("[source prose truncated]" in note for note in notes)
    identity = next(note for note in notes if "Contract lineage" in note)
    assert canonical_json(reference.to_json()) in identity
    assert sha256(canonical_json(project).encode("utf-8")).hexdigest() in identity
    published = service.publish(draft["draft_id"])
    assert service.get(published) == draft["document"]
