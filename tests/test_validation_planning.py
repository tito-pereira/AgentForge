# SPDX-License-Identifier: MPL-2.0
"""Synthetic exact approvals and method assessments exercise plan machinery only."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from corinthos.contracts import (
    AuthorityError,
    ConflictError,
    ContractStore,
    IntegrityError,
    PublishContext,
    approval_request,
)
from corinthos.validation.planning import ValidationPlanner
from corinthos.validation.procedures import digest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def planner(tmp_path):
    store = ContractStore(tmp_path)
    refs = {}
    for name in ("project", "technology-decision", "module", "workflow"):
        document = json.loads(
            (_ROOT / "examples" / "contracts" / f"{name}.json").read_text(encoding="utf-8")
        )
        metadata = document["metadata"]
        if name == "workflow":
            first = {
                "milestone_id": "early",
                "title": "Early review",
                "objective": "Exercise the isolated greeting.",
                "depends_on": [],
                "required_checkpoint_ids": ["greet"],
                "test_scope": {"included": ["Local greeting"], "excluded": []},
                "test_scenarios": ["Run the greeting for Ada."],
                "readiness_criteria": [
                    {"criterion_id": "early-ready", "criterion": "Greeting runs."}
                ],
            }
            second = deepcopy(first)
            second.update(milestone_id="later", title="Later review", depends_on=["early"])
            second["readiness_criteria"][0]["criterion_id"] = "later-ready"
            document["payload"]["playtest_milestones"] = [first, second]
            metadata["approval"] = {
                "kind": "HUMAN",
                "approval_id": "synthetic-validation-test-milestones",
                "actor_id": "demo-owner",
            }
        receipt = approval_request(document) if metadata["approval"] is not None else None
        provenance = metadata["provenance"]
        refs[name] = store.publish(
            document,
            context=PublishContext(
                provenance["engine"], provenance["actor_id"], lambda actual: actual == receipt
            ),
        )
    return (
        ValidationPlanner(
            store, _ROOT / "policies/standard.yaml", _ROOT / "schemas/standard.schema.json"
        ),
        refs,
    )


def _assess(draft, bindings):
    return {
        row["check_id"]: {
            "actor_id": "synthetic-independent-reviewer",
            "criterion_sha256": digest(
                {"criterion": row["criterion"], "source_ref": row["source_ref"]}
            ),
            "binding_sha256": digest(bindings[row["check_id"]]),
            "rationale": "Synthetic per-check assessment for testing publication only.",
        }
        for row in draft["obligations"]
    }


def _bindings(draft):
    return {
        row["check_id"]: {
            "method": next(iter(row["verification_methods"]), "REVIEW"),
            "required_evidence": row["required_evidence"],
            "description": "Inspect the exact candidate for the cited obligation.",
            "command": None,
            "review_paths": ["README.md"],
        }
        for row in draft["obligations"]
    }


@pytest.mark.parametrize(
    ("level", "target", "targets", "gate", "local_ids"),
    [
        ("MODULE", "module", None, "CHECKPOINT", set()),
        ("INTEGRATION", "workflow", ["greeting"], "CHECKPOINT", set()),
        ("CHECKPOINT", "workflow", ["greet"], "CHECKPOINT", {"CP1"}),
        (
            "PLAYTEST_MILESTONE",
            "workflow",
            ["later"],
            "PLAYTEST_READINESS",
            {"CP1", "early-ready", "later-ready"},
        ),
        ("PRODUCT", None, None, "PRODUCT_VALIDATION", {"SC1", "CP1", "early-ready", "later-ready"}),
    ],
)
def test_derive_and_publish_exact_scopes(planner, level, target, targets, gate, local_ids):
    service, refs = planner
    draft = service.derive(refs["project"], level, target_ref=refs.get(target), target_ids=targets)
    assert draft == service.derive(
        refs["project"], level, target_ref=refs.get(target), target_ids=targets
    )
    obligations = {
        row["source_ref"].get(
            "obligation_id", row["source_ref"].get("standard_rule_ref", {}).get("rule_id")
        )
        for row in draft["obligations"]
    }
    assert {"R1", "C1", "AC1", "TC1", "M1", "M2", "M3", "M4", "M5"} | local_ids <= obligations
    assert ("SC1" in obligations) == (level == "PRODUCT")
    bindings = _bindings(draft)
    reviews = _assess(draft, bindings)
    ref = service.publish(draft, bindings, reviews, actor_id="synthetic-validation")
    document = service.store.get(ref)
    assert document["metadata"]["approval"] is None
    assert document["payload"]["gate_policy"] == {"gate": gate}
    assert service.repository.bindings(ref) == bindings
    assert service.repository.reviews(ref) == reviews


def test_omitting_global_obligation_and_unreviewed_binding_block_publication(planner):
    service, refs = planner
    draft = service.derive(refs["project"], "PRODUCT")
    modified = deepcopy(draft)
    modified["obligations"] = [
        row for row in draft["obligations"] if row["source_ref"].get("obligation_id") != "SC1"
    ]
    events = service.store.list_events()
    with pytest.raises(ConflictError, match="complete current scope"):
        service.publish(modified, {}, {}, actor_id="synthetic-validation")
    bindings = _bindings(draft)
    reviews = _assess(draft, bindings)
    first = next(iter(bindings))
    bindings[first]["description"] = "A different procedure after review."
    with pytest.raises(IntegrityError, match="unbound"):
        service.publish(draft, bindings, reviews, actor_id="synthetic-validation")
    assert service.store.list_events() == events


def test_method_cannot_substitute_command_for_required_independent_inspection(planner):
    service, refs = planner
    draft = service.derive(refs["project"], "PRODUCT")
    row = next(row for row in draft["obligations"] if "standard_rule_ref" in row["source_ref"])
    bindings = _bindings(draft)
    executable = str(Path(sys.executable).absolute())
    bindings[row["check_id"]].update(
        method="TEST",
        review_paths=[],
        command={
            "argv": [executable, "--version"],
            "inputs": {executable: "0" * 64},
            "timeout": 10,
            "success_line": "A successful command is insufficient evidence.",
            "failure_line": None,
        },
    )
    with pytest.raises(IntegrityError, match="explicit independent inspection"):
        service.publish(draft, bindings, _assess(draft, bindings), actor_id="synthetic-validation")


def test_method_cannot_label_inspection_as_an_executed_test(planner):
    service, refs = planner
    draft = service.derive(refs["project"], "PRODUCT")
    row = next(
        row for row in draft["obligations"] if row["source_ref"].get("obligation_id") == "SC1"
    )
    bindings = _bindings(draft)
    bindings[row["check_id"]]["method"] = "TEST"
    with pytest.raises(IntegrityError, match="actual executed check"):
        service.publish(draft, bindings, _assess(draft, bindings), actor_id="synthetic-validation")


def test_same_formal_plan_is_reused_and_changed_method_needs_exact_predecessor(planner):
    service, refs = planner
    draft = service.derive(refs["project"], "PRODUCT")
    bindings = _bindings(draft)
    reviews = _assess(draft, bindings)
    with pytest.raises(AuthorityError, match="its own audit plan"):
        service.publish(draft, bindings, reviews, actor_id="demo-workflow")
    ref = service.publish(draft, bindings, reviews, actor_id="synthetic-validation")
    first = next(iter(bindings))
    reviews[first]["rationale"] = "A second synthetic assessment of the same procedure."
    assert service.publish(draft, bindings, reviews, actor_id="synthetic-validation") == ref
    bindings[first]["review_paths"] = ["docs/storage.md"]
    reviews = _assess(draft, bindings)
    with pytest.raises(ConflictError, match="exact active predecessor"):
        service.publish(draft, bindings, reviews, actor_id="synthetic-validation")
    successor = service.publish(
        draft, bindings, reviews, actor_id="synthetic-validation", previous=ref
    )
    assert successor.revision_id != ref.revision_id
    assert service.store.get(successor)["metadata"]["supersedes"] == ref.to_json()
    assert (
        service.publish(draft, bindings, reviews, actor_id="synthetic-validation", previous=ref)
        == successor
    )


def test_consumer_scope_preserves_exact_compatible_terms_and_blocks_removed_provider(planner):
    service, refs = planner

    def publish_module(document):
        receipt = approval_request(document)
        return service.store.publish(
            document,
            context=PublishContext("WORKFLOW", "demo-workflow", lambda actual: actual == receipt),
        )

    module = service.store.get(refs["module"])
    check = {
        "check_id": "interface-check",
        "provider_module_id": "provider",
        "interface_id": "greet-api",
        "interface_revision": "first",
        "criterion": "Observe the exact interface for valid and invalid input.",
        "verification_methods": ["REVIEW"],
        "evidence_required": ["Independent review record"],
        "blocking": True,
    }
    terms = {
        "interface_id": "greet-api",
        "interface_revision": "first",
        "interface_type": "FUNCTION",
        "inputs": ["Name as text"],
        "outputs": ["Greeting as text"],
        "errors": ["Reject invalid names"],
        "side_effects": ["None"],
        "behavioral_guarantees": ["Return the same greeting for the same name"],
    }
    provider = deepcopy(module)
    provider["metadata"].update(
        contract_id="provider",
        revision_id="provider-first",
        approval={"kind": "HUMAN", "approval_id": "provider-approval", "actor_id": "demo-owner"},
    )
    provider["payload"].update(
        module_id="provider", technology_decision_refs=[], provided_interfaces=[terms]
    )
    provider["payload"]["verification_spec"]["interface_checks"] = [check]
    original = publish_module(provider)

    consumer = deepcopy(module)
    consumer["metadata"].update(
        contract_id="consumer",
        revision_id="consumer-first",
        approval={"kind": "HUMAN", "approval_id": "consumer-approval", "actor_id": "demo-owner"},
    )
    consumer["payload"].update(
        module_id="consumer",
        technology_decision_refs=[],
        consumed_interfaces=[
            {
                "provider_module_id": "provider",
                "provider_contract_ref": original.to_json(),
                "interface_id": "greet-api",
                "required_interface_revision": "first",
            }
        ],
    )
    consumer["payload"]["verification_spec"]["interface_checks"] = [check]
    consumer_ref = publish_module(consumer)
    draft = service.derive(refs["project"], "MODULE", target_ref=consumer_ref)
    assert original.to_json() not in draft["source_contract_refs"]
    row = next(row for row in draft["obligations"] if "interface" in row["source_context"])
    assert row["source_context"]["provider_ref"] == original.to_json()
    assert row["source_context"]["interface"] == terms
    bindings = _bindings(draft)
    plan = service.publish(
        draft, bindings, _assess(draft, bindings), actor_id="synthetic-validation"
    )

    compatible = deepcopy(provider)
    compatible["metadata"].update(
        revision_id="provider-compatible", version=2, supersedes=original.to_json()
    )
    compatible["metadata"]["approval"]["approval_id"] = "provider-compatible-approval"
    compatible["payload"]["purpose_and_boundaries"]["purpose"] = "Retain the greeting API."
    current = publish_module(compatible)
    assert service.derive(refs["project"], "MODULE", target_ref=consumer_ref) == draft
    with service.store._transaction() as connection:
        service.repository.require_current(connection, plan)

    incompatible = deepcopy(compatible)
    incompatible["metadata"].update(
        revision_id="provider-incompatible", version=3, supersedes=current.to_json()
    )
    incompatible["metadata"]["approval"]["approval_id"] = "provider-incompatible-approval"
    incompatible["payload"]["provided_interfaces"] = []
    incompatible["payload"]["verification_spec"]["interface_checks"] = []
    publish_module(incompatible)
    with pytest.raises(ConflictError, match="no longer preserves"):
        service.derive(refs["project"], "MODULE", target_ref=consumer_ref)
    with service.store._transaction() as connection:
        with pytest.raises(ConflictError, match="no longer preserves"):
            service.repository.require_current(connection, plan)
