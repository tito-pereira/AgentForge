# SPDX-License-Identifier: MPL-2.0
"""Exercise the eight packaged wire schemas with the documented examples."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from nukytera.contracts import ContractType, SchemaError, load_schema, validate_schema

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "contracts"


def example(kind: str) -> dict:
    return json.loads((EXAMPLES / f"{kind}.json").read_text(encoding="utf-8"))


@pytest.fixture
def result_with_evidence():
    document = example("validation-result")
    payload = document["payload"]
    run = payload["target_and_execution"]
    check = example("validation")["payload"]["verification_matrix"][0]
    payload["evidence_refs"] = [
        {
            "evidence_id": "example-evidence",
            "evidence_kind": check["required_evidence"][0],
            "check_id": check["check_id"],
            "source_ref": check["source_ref"],
            "artifact_identity": run["artifact_identity"],
            "execution_context": {
                "validation_run_id": run["validation_run_id"],
                "validation_plan_ref": payload["validation_plan_ref"],
            },
            "verification_method": check["verification_method"],
            "evaluator_ref": run["evaluator_ref"],
            "path": "checks/test-result.json",
            "sha256": "0" * 64,
        }
    ]
    validate_schema(document)
    return document


@pytest.mark.parametrize("contract_type", list(ContractType))
def test_packaged_schema_accepts_its_example(contract_type):
    schema = load_schema(contract_type)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == f"urn:nukytera:contracts:1.0:{contract_type.lower().replace('_', '-')}"
    validate_schema(example(contract_type.lower().replace("_", "-")))


@pytest.mark.parametrize(
    ("kind", "location", "value"),
    [
        ("project", ("payload", "requirements"), []),
        ("workflow", ("payload", "execution_policy", "validation_policy"), "SKIP_GATES"),
        (
            "module",
            ("payload", "verification_spec", "quality_checks"),
            [{"check_id": "empty-check", "category": "Maintainability"}],
        ),
        ("technology-decision", ("payload", "selected_option"), {"source": "AGENT"}),
        (
            "validation",
            ("payload", "validation_scope", "target_contract_ref", "contract_type"),
            "VALIDATION_RESULT",
        ),
        ("validation-result", ("payload", "gate_assessment", "state"), "ACCEPTED"),
        (
            "evidence-report",
            ("payload", "engineering_quality_and_documentation", "M5"),
            {"evidence_ids": [], "gaps": []},
        ),
        ("project-revision-request", ("payload", "base_contract_version"), "latest"),
    ],
)
def test_rejects_invalid_shape_for_each_contract(kind, location, value):
    document = example(kind)
    container = document
    for field in location[:-1]:
        container = container[field]
    container[location[-1]] = value
    with pytest.raises(SchemaError):
        validate_schema(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2.0"),
        ("created_at", "2026-02-30T12:00:00Z"),
        ("revision_id", "revision\n"),
        ("version", 2**63),
        ("status", "ACTIVE"),
        ("standard_ref", {"standard_id": "nukytera-standard", "version": "disabled"}),
    ],
)
def test_rejects_invalid_universal_metadata(field, value):
    document = example("project")
    document["metadata"][field] = value
    with pytest.raises(SchemaError):
        validate_schema(document)


def test_rejects_missing_field_and_added_runtime_state():
    document = example("workflow")
    del document["payload"]["project_contract_ref"]
    with pytest.raises(SchemaError):
        validate_schema(document)

    document = example("workflow")
    document["payload"]["checkpoints"][0]["status"] = "COMPLETED"
    with pytest.raises(SchemaError):
        validate_schema(document)


def test_rejects_incomplete_nested_reference():
    document = example("workflow")
    del document["payload"]["project_contract_ref"]["revision_id"]
    with pytest.raises(SchemaError):
        validate_schema(document)


def test_interface_verification_identifies_the_exact_revision():
    document = example("module")
    payload = document["payload"]
    payload["provided_interfaces"] = [
        {"interface_id": "task-reader", "interface_revision": "v1", "interface_type": "FUNCTION"}
    ]
    check = {
        "check_id": "verify-task-reader-v1",
        "provider_module_id": payload["module_id"],
        "interface_id": "task-reader",
        "interface_revision": "v1",
        "criterion": "The reader returns a task for a known identifier.",
        "verification_methods": ["contract-test"],
        "evidence_required": ["test-log"],
        "blocking": True,
    }
    payload["verification_spec"]["interface_checks"] = [check]
    validate_schema(document)

    del check["interface_revision"]
    with pytest.raises(SchemaError):
        validate_schema(document)


def test_incomplete_technology_decision_can_only_be_a_draft():
    document = example("technology-decision")
    document["metadata"]["status"] = "DRAFT"
    document["metadata"]["approval"] = None
    document["payload"]["ai_recommendations"] = []
    document["payload"]["selected_option"] = None
    validate_schema(document)

    document["metadata"]["status"] = "PUBLISHED"
    with pytest.raises(SchemaError):
        validate_schema(document)


def test_rejects_more_than_five_technology_options():
    document = example("technology-decision")
    options = document["payload"]["ai_recommendations"]
    document["payload"]["ai_recommendations"] = [options[0]] * 6
    with pytest.raises(SchemaError):
        validate_schema(document)


@pytest.mark.parametrize(
    "path", ["../private.json", "/private.json", "C:/private.json", "x/../secret"]
)
def test_rejects_unsafe_evidence_path(result_with_evidence, path):
    document = result_with_evidence
    document["payload"]["evidence_refs"][0]["path"] = path
    with pytest.raises(SchemaError):
        validate_schema(document)


def test_rejects_evidence_without_run_and_plan_identity(result_with_evidence):
    document = result_with_evidence
    del document["payload"]["evidence_refs"][0]["execution_context"]["validation_run_id"]
    with pytest.raises(SchemaError):
        validate_schema(document)


def test_not_applicable_requires_an_explicit_justification():
    document = example("validation-result")
    result = document["payload"]["check_results"][0]
    result["status"] = None
    with pytest.raises(SchemaError):
        validate_schema(document)

    result["not_applicable_reason"] = "This optional check does not apply to the recorded target."
    validate_schema(document)


def test_schema_returned_to_caller_cannot_disable_validation():
    schema = load_schema("PROJECT")
    schema.clear()

    document = example("project")
    document["payload"]["extra"] = "An undefined top-level concept."
    with pytest.raises(SchemaError):
        validate_schema(document)
