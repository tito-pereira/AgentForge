# SPDX-License-Identifier: MPL-2.0
"""Actual local subprocesses and explicitly synthetic contract/reviewer fixtures."""

import json
import sys
import threading
from pathlib import Path

import pytest

from corinthos.cli import main
from corinthos.contracts import (
    AuthorityError,
    ContractStore,
    IntegrityError,
    PublishContext,
    approval_request,
)
from corinthos.validation.planning import ValidationPlanner
from corinthos.validation.procedures import digest, file_hash, validate_binding
from corinthos.validation.runtime import ValidationRunner

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = (
    "from pathlib import Path;import sys;"
    "text=(Path(sys.argv[1])/'README.md').read_text(encoding='utf-8');"
    "print('AUDIT_PASS' if text=='approved' else 'AUDIT_VIOLATION');"
    "sys.exit(text!='approved')"
)


@pytest.fixture
def audit(tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    store = ContractStore(root)
    refs = {}
    for name in ("project", "technology-decision", "module", "workflow"):
        document = json.loads(
            (_ROOT / "examples" / "contracts" / f"{name}.json").read_text(encoding="utf-8")
        )
        metadata = document["metadata"]
        receipt = approval_request(document) if metadata["approval"] is not None else None
        provenance = metadata["provenance"]
        refs[name] = store.publish(
            document,
            context=PublishContext(
                provenance["engine"],
                provenance["actor_id"],
                lambda actual: actual == receipt,
            ),
        )
    planner = ValidationPlanner(
        store, _ROOT / "policies/standard.yaml", _ROOT / "schemas/standard.schema.json"
    )
    draft = planner.derive(refs["project"], "PRODUCT")
    executable = str(Path(sys.executable).resolve(strict=True))
    bindings = {}
    reviews = {}
    for row in draft["obligations"]:
        identifier = row["check_id"]
        binding = {
            "method": next(iter(row["verification_methods"]), "TEST"),
            "required_evidence": row["required_evidence"],
            "description": "Read the test candidate and compare its actual greeting criterion marker.",
            "review_paths": ["README.md"] if row["review_required"] else [],
            "command": {
                "argv": [executable, "-I", "-B", "-c", _SCRIPT, "{candidate}"],
                "timeout": 15,
                "inputs": {executable: file_hash(executable)},
                "success_line": "AUDIT_PASS",
                "failure_line": "AUDIT_VIOLATION",
            },
        }
        bindings[identifier] = binding
        reviews[identifier] = {
            "actor_id": "synthetic-adequacy-reviewer",
            "criterion_sha256": digest(
                {"source_ref": row["source_ref"], "criterion": row["criterion"]}
            ),
            "binding_sha256": digest(binding),
            "rationale": "Synthetic evaluator assessment for the isolated contract machinery fixture.",
        }
    ref = planner.publish(draft, bindings, reviews, actor_id="synthetic-plan-publisher")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "README.md").write_text("approved", encoding="utf-8")
    return ValidationRunner(store), ref, candidate


def _review(request):
    return {
        "evaluator": request["evaluator"],
        "artifact_identity": request["artifact_identity"],
        "inspected": request["paths"],
        "status": "CONFORMANT",
        "rationale": "Synthetic independent review for the test fixture only.",
    }


def test_exact_result_failure_and_distinct_revalidation(audit):
    runner, plan, candidate = audit
    options = {"evaluator": "synthetic-run-evaluator", "reviewer": _review}
    original = runner.run(plan, candidate, **options)
    result = runner.store.get(original)["payload"]
    assert result["gate_assessment"]["state"] == "SATISFIED"
    assert result["coverage_summary"]["sufficient"]
    observed = result["target_and_execution"]
    assert runner.repository.is_published_run(plan, original, observed["validation_run_id"])
    assert runner.publish_frozen(observed["validation_run_id"]) == original

    (candidate / "README.md").write_text("contradiction", encoding="utf-8")
    with pytest.raises(IntegrityError, match="differs"):
        runner.run(plan, candidate, expected_identity=observed["artifact_identity"], **options)
    failed = runner.run(plan, candidate, previous_run_id=observed["validation_run_id"], **options)
    rejected = runner.store.get(failed)["payload"]
    assert rejected["validation_plan_ref"] == result["validation_plan_ref"] == plan.to_json()
    assert rejected["gate_assessment"]["state"] == "BLOCKED"
    assert rejected["coverage_summary"]["sufficient"]
    assert {c["status"] for c in rejected["check_results"]} == {"NONCONFORMANT"}
    assert set(e["evidence_id"] for e in rejected["evidence_refs"]).isdisjoint(
        e["evidence_id"] for e in result["evidence_refs"]
    )
    record = rejected["evidence_refs"][0]
    runner.store.verify_artifact(record["path"], record["sha256"])
    path = runner.store.database_path.parent / "artifacts" / record["path"]
    path.write_bytes(b"altered evidence")
    with pytest.raises(IntegrityError, match="digest"):
        runner.store.verify_artifact(record["path"], record["sha256"])


def test_unavailable_review_and_interruption_never_certify(audit):
    runner, plan, candidate = audit
    absent = runner.run(plan, candidate, evaluator="synthetic-run-evaluator")
    payload = runner.store.get(absent)["payload"]
    assert payload["gate_assessment"]["state"] == "BLOCKED"
    assert "NOT_VERIFIED" in {row["status"] for row in payload["check_results"]}
    with pytest.raises(AuthorityError, match="separate"):
        runner.run(plan, candidate, evaluator="demo-workflow")
    cancel = threading.Event()
    cancel.set()
    stopped = runner.run(plan, candidate, evaluator="synthetic-run-evaluator", cancel=cancel)
    payload = runner.store.get(stopped)["payload"]
    assert payload["target_and_execution"]["status"] == "INTERRUPTED"
    assert payload["gate_assessment"]["state"] == "BLOCKED"
    assert {row["status"] for row in payload["check_results"]} == {"NOT_VERIFIED"}


def test_candidate_drift_keeps_observed_old_evidence_and_blocks(audit):
    runner, plan, candidate = audit

    def independent_review(request):
        (candidate / "README.md").write_text("changed during review", encoding="utf-8")
        return _review(request)

    ref = runner.run(plan, candidate, evaluator="synthetic-evaluator", reviewer=independent_review)
    payload = runner.store.get(ref)["payload"]
    assert payload["target_and_execution"]["status"] == "ERROR"
    assert payload["gate_assessment"]["state"] == "BLOCKED"
    assert payload["evidence_refs"]
    assert any(check["status"] == "NOT_VERIFIED" for check in payload["check_results"])


def test_guided_cli_retains_incomplete_draft_diagnostic(audit, capsys):
    runner, plan, _ = audit
    root = str(runner.store.database_path.parent.parent)
    project = next(
        item
        for item in runner.store.get(plan)["payload"]["source_contract_refs"]
        if item["contract_type"] == "PROJECT"
    )
    assert (
        main(
            [
                "validation",
                "--root",
                root,
                "plan",
                project["contract_id"],
                "--scope",
                "PRODUCT",
                "--policy",
                str(_ROOT / "policies/standard.yaml"),
                "--policy-schema",
                str(_ROOT / "schemas/standard.schema.json"),
            ]
        )
        == 0
    )
    view = json.loads(capsys.readouterr().out)
    assert view["draft"]["plan"]["obligations"]
    assert (
        main(
            [
                "validation",
                "--root",
                root,
                "publish",
                view["draft_id"],
                "--evaluator",
                "synthetic-cli-evaluator",
            ]
        )
        == 1
    )
    assert "validation:" in capsys.readouterr().err
    assert runner.repository.get_draft(view["draft_id"])["draft"]["diagnostics"]


def test_unproduced_evidence_kind_cannot_be_bound(audit):
    runner, plan, _ = audit
    binding = next(iter(runner.repository.bindings(plan).values()))
    binding["required_evidence"] = ["Signed screenshot"]
    with pytest.raises(IntegrityError, match="no supported observation"):
        validate_binding(binding)


def test_drift_between_freeze_and_publication_leaves_only_blocked_result(audit, monkeypatch):
    runner, plan, candidate = audit
    actual_freeze = runner.repository._freeze
    drifted = False

    def freeze_then_change(connection, row, build_result, **options):
        nonlocal drifted
        frozen = actual_freeze(connection, row, build_result, **options)
        if not drifted:
            drifted = True
            (candidate / "README.md").write_text("changed before publication", encoding="utf-8")
        return frozen

    monkeypatch.setattr(runner.repository, "_freeze", freeze_then_change)
    ref = runner.run(plan, candidate, evaluator="synthetic-run-evaluator", reviewer=_review)
    payload = runner.store.get(ref)["payload"]
    assert payload["gate_assessment"]["state"] == "BLOCKED"
    assert payload["target_and_execution"]["status"] == "ERROR"
    run_id = payload["target_and_execution"]["validation_run_id"]
    assert sum(event["kind"] == "RESULT_FROZEN" for event in runner.repository.history(run_id)) == 1
