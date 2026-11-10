# SPDX-License-Identifier: MPL-2.0
"""Synthetic actors exercise real independent Workflow/Validation integration."""

import json
import subprocess
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_validation_planning import _assess, _bindings
from test_workflow_runtime import SyntheticAdapter, _accept, _publish, _seed, _spec, _write_code

from corinthos.cli import main
from corinthos.contracts import ConflictError, ContractRef, IntegrityError
from corinthos.validation.planning import ValidationPlanner
from corinthos.validation.runtime import ValidationRunner
from corinthos.workflow.runtime import WorkflowRunner
from corinthos.workflow.verification import AuditExpectation, workspace_snapshot

_ROOT = Path(__file__).resolve().parents[1]


def _publish_plan(store, workflow, level, target_ref, ids, review_paths=("greeting.py",)):
    planner = ValidationPlanner(
        store, _ROOT / "policies/standard.yaml", _ROOT / "schemas/standard.schema.json"
    )
    project = ContractRef.from_json(store.get(workflow)["payload"]["project_contract_ref"])
    draft = planner.derive(project, level, target_ref=target_ref, target_ids=ids)
    bindings = _bindings(draft)
    for binding in bindings.values():
        binding["review_paths"] = list(review_paths)
    return planner.publish(
        draft, bindings, _assess(draft, bindings), actor_id="synthetic-validation-planner"
    )


def test_git_worktree_metadata_is_excluded_but_exact_commit_is_retained(tmp_path):
    repo, worktree = tmp_path / "repo", tmp_path / "worktree"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    git("init", "--quiet")
    git(
        "-c",
        "user.name=Synthetic test",
        "-c",
        "user.email=tests@example.invalid",
        "commit",
        "--quiet",
        "--allow-empty",
        "-m",
        "Test candidate source",
    )
    git("worktree", "add", "--quiet", "--detach", str(worktree))
    (worktree / "source.txt").write_text("Candidate content", encoding="utf-8")
    (worktree / "nested").mkdir()
    assert (worktree / ".git").is_file()
    snapshot = workspace_snapshot(worktree)
    assert set(snapshot["files"]) == {"source.txt"}
    assert snapshot["artifact_identity"]["commit"] == git("rev-parse", "HEAD")
    assert "commit" not in workspace_snapshot(worktree / "nested")["artifact_identity"]


def test_missing_formal_plan_blocks_and_retained_request_rejects_drift(tmp_path, capsys):
    store, workflow = _seed(tmp_path)
    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=_accept)
    requirement = AuditExpectation("CHECKPOINT", workflow, ("greet",))
    spec = replace(_spec(), audit_expectations=(requirement,))
    execution = runner.configure(workflow, [spec], actor_id="synthetic-operator")
    attempt = runner.run_next(execution["execution_id"])
    assert attempt["state"] == "BLOCKED"
    assert attempt["details"]["gates"][0]["state"] == "NOT_VERIFIED"
    assert attempt["details"]["gates"][0]["validation_plan_ref"] is None
    request = runner.audit_request(attempt["attempt_id"])
    assert request["expectations"] == [requirement.to_json()]
    assert request["artifact_identity"] == attempt["details"]["artifact_identity"]
    assert main(["workflow", "--root", str(tmp_path), "audit-request", attempt["attempt_id"]]) == 0
    assert json.loads(capsys.readouterr().out) == request
    plan = _publish_plan(store, workflow, "CHECKPOINT", workflow, ("greet",))
    assert (
        main(
            [
                "validation",
                "--root",
                str(tmp_path),
                "run",
                plan.contract_id,
                "--workflow-attempt",
                attempt["attempt_id"],
                "--evaluator",
                "synthetic-cli-evaluator",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["gate"]["state"] == "BLOCKED"
    (tmp_path / "greeting.py").write_text("Changed candidate", encoding="utf-8")
    with pytest.raises(ConflictError, match="exact retained candidate"):
        runner.audit_request(attempt["attempt_id"])


def test_rejected_preliminary_review_retains_an_independent_formal_block(tmp_path):
    store, workflow = _seed(tmp_path)
    (tmp_path / "greeting.py").write_bytes(b"answer = 42\n")
    plan = _publish_plan(store, workflow, "CHECKPOINT", workflow, ("greet",))
    result = ValidationRunner(store).run(
        plan,
        tmp_path,
        evaluator="synthetic-independent-evaluator",
        reviewer=lambda request: {
            "evaluator": request["evaluator"],
            "artifact_identity": request["artifact_identity"],
            "inspected": request["paths"],
            "status": "NONCONFORMANT",
            "rationale": "Synthetic evaluator found an unmet check in the reviewed candidate.",
        },
    )
    runner = WorkflowRunner(
        tmp_path,
        SyntheticAdapter(store, effect=lambda *_: None),
        reviewer=lambda request: replace(_accept(request), accepted=False),
        auditor=lambda _: pytest.fail("A rejected review must not trigger a new formal audit."),
    )
    spec = replace(
        _spec(), audit_expectations=(AuditExpectation("CHECKPOINT", workflow, ("greet",)),)
    )
    execution = runner.configure(workflow, [spec], actor_id="synthetic-operator")
    attempt = runner.run_next(execution["execution_id"])
    assert attempt["state"] == "BLOCKED"
    assert attempt["details"]["reason"] == "TECHNICAL_REVIEW_REJECTED"
    assert attempt["details"]["technical_review"]["accepted"] is False
    (observation,) = attempt["details"]["gates"]
    assert observation["state"] == "BLOCKED"
    assert observation["result_ref"] == result.to_json()


@pytest.mark.parametrize("with_guard", [False, True])
def test_repository_completion_cannot_skip_its_current_formal_gate(tmp_path, with_guard):
    store, workflow = _seed(tmp_path)
    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=_accept)
    expectation = AuditExpectation("CHECKPOINT", workflow, ("greet",))
    spec = replace(_spec(), audit_expectations=(expectation,))
    configured = runner.configure(workflow, [spec], actor_id="synthetic-operator")
    repository, identifier = runner.repository, configured["execution_id"]
    ready = repository.prepare(identifier, "greet", configured["version"], actor_id="synthetic")
    attempt = repository.claim(
        identifier,
        "greet",
        ready["version"],
        owner_id="synthetic",
        provider="synthetic",
        context={"source_snapshot": {"snapshot_id": "synthetic"}},
    )
    attempt_id, fence = attempt["attempt_id"], attempt["fence"]
    repository.transition(
        attempt_id, fence, "VERIFYING", owner_id="synthetic", details={"observed": "fixture"}
    )
    guard = (lambda: {"gates": [], "reason": "synthetic pass"}) if with_guard else None
    with pytest.raises(ConflictError, match="Required Validation evidence"):
        repository.transition(
            attempt_id,
            fence,
            "COMPLETED",
            owner_id="synthetic",
            details={"observed": "synthetic"},
            completion_guard=guard,
        )
    assert repository.get_attempt(attempt_id)["state"] == "VERIFYING"


@pytest.mark.parametrize("level", ["MODULE", "INTEGRATION"])
def test_scope_is_due_only_after_exact_module_prerequisites(tmp_path, level):
    store, workflow = _seed(tmp_path, second=True)
    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=_accept)
    module = ContractRef.from_json(
        store.get(workflow)["payload"]["modules"][0]["module_contract_ref"]
    )
    target = module if level == "MODULE" else workflow
    requirement = AuditExpectation(level, target, ("greeting",))
    plan = _publish_plan(store, workflow, level, target, requirement.scope)
    assert runner.gates.applicable(workflow, "greet") == []
    (gate,) = runner.gates.applicable(workflow, "second")
    assert gate.validation_plan_ref == plan and gate.target_ref == target
    with pytest.raises(IntegrityError, match="due at this checkpoint"):
        runner.prepare_bindings(
            workflow, [replace(_spec(), audit_expectations=(requirement,)), _spec(second=True)]
        )
    bindings = runner.prepare_bindings(
        workflow, [_spec(), replace(_spec(second=True), audit_expectations=(requirement,))]
    )
    assert bindings["checkpoints"]["second"]["audit_expectations"] == [requirement.to_json()]


def test_managed_audit_during_verification_and_later_prerequisite_block(tmp_path):
    store, workflow = _seed(tmp_path, second=True)
    configuration = tmp_path / "greeting-config.txt"
    configuration.write_text("enabled", encoding="utf-8")
    plan = _publish_plan(
        store, workflow, "CHECKPOINT", workflow, ("greet",), ("greeting.py", configuration.name)
    )
    validator = ValidationRunner(store)
    observations = []

    def independent_inspection(request):
        path = Path(request["candidate_root"]) / "greeting.py"
        assert path.read_text(encoding="utf-8") == "answer = 42\n"
        assert path.with_name(configuration.name).read_text(encoding="utf-8") == "enabled"
        return {
            "evaluator": request["evaluator"],
            "artifact_identity": request["artifact_identity"],
            "inspected": request["paths"],
            "status": "CONFORMANT",
            "rationale": "Synthetic evaluator inspected the actual isolated greeting bytes.",
        }

    def audit(request):
        assert runner.repository.get_attempt(request["attempt_id"])["state"] == "VERIFYING"
        assert request["expectations"] == [
            AuditExpectation("CHECKPOINT", workflow, ("greet",)).to_json()
        ]
        observations.append(
            validator.run(
                plan,
                request["workspace"],
                evaluator="synthetic-independent-evaluator",
                expected_identity=request["artifact_identity"],
                reviewer=independent_inspection,
            )
        )

    adapter = SyntheticAdapter(store, effect=_write_code)
    runner = WorkflowRunner(tmp_path, adapter, reviewer=_accept, auditor=audit)
    spec = replace(
        _spec(), audit_expectations=(AuditExpectation("CHECKPOINT", workflow, ("greet",)),)
    )
    execution = runner.configure(
        workflow, [spec, _spec(second=True)], actor_id="synthetic-operator"
    )
    first = runner.run_next(execution["execution_id"])
    assert first["state"] == "COMPLETED", first["details"]
    assert first["details"]["reason"] == "FORMAL_CHECKPOINT_GATES_SATISFIED"
    (result,) = observations
    assert first["details"]["gates"][0]["result_ref"] == result.to_json()

    # Unrelated new bytes do not erase historical scope evidence; changed delivery does.
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("Separate output", encoding="utf-8")
    runner.repository.require_eligible(execution["execution_id"], "second")
    unrelated.unlink()
    configuration.write_text("disabled", encoding="utf-8")
    assert runner.run_next(execution["execution_id"]) is None
    configuration_drift = runner.repository.history(execution["execution_id"])[-1]["data"]["gates"][
        0
    ]
    assert configuration_drift["state"] == "NOT_VERIFIED"
    assert configuration_drift["artifact_identity"] != first["details"]["artifact_identity"]
    configuration.write_text("enabled", encoding="utf-8")
    greeting = tmp_path / "greeting.py"
    greeting.write_text("answer = 43\n", encoding="utf-8")
    assert runner.run_next(execution["execution_id"]) is None
    drift = runner.repository.history(execution["execution_id"])[-1]["data"]["gates"][0]
    assert drift["state"] == "NOT_VERIFIED"
    assert drift["artifact_identity"] != first["details"]["artifact_identity"]
    greeting.write_text("answer = 42\n", encoding="utf-8")

    # A bare Kernel publication cannot claim the managed runtime's authority.
    manual = deepcopy(store.get(result))
    manual["metadata"].update(
        contract_id="manual-synthetic-result",
        revision_id="manual-synthetic-result-r1",
        created_at=datetime.now(UTC).isoformat(),
    )
    payload = manual["payload"]
    run_id = "manual-synthetic-run"
    payload["target_and_execution"]["validation_run_id"] = run_id
    evidence_ids = {}
    for evidence in payload["evidence_refs"]:
        previous = evidence["evidence_id"]
        evidence["evidence_id"] = f"manual-{previous}"
        evidence_ids[previous] = evidence["evidence_id"]
        evidence["execution_context"]["validation_run_id"] = run_id
    for check in payload["check_results"]:
        check["evidence_ids"] = [evidence_ids[item] for item in check["evidence_ids"]]
    manual_ref = _publish(store, manual)
    assert runner.run_next(execution["execution_id"]) is None
    unauthenticated = runner.repository.history(execution["execution_id"])[-1]["data"]["gates"][0]
    assert unauthenticated["state"] == "NOT_VERIFIED"
    assert unauthenticated["result_ref"] == manual_ref.to_json()

    # A later real run lacks independent inspection and cannot reuse the prior PASS.
    later = validator.run(
        plan,
        tmp_path,
        evaluator="synthetic-independent-evaluator",
        expected_identity=first["details"]["artifact_identity"],
    )
    assert later != result
    assert runner.run_next(execution["execution_id"]) is None
    assert len(adapter.calls) == 1
    assert runner.repository.get_attempt(first["attempt_id"]) == first
    history = runner.repository.history(execution["execution_id"])
    assert history[-1]["data"]["reason"] == "PREREQUISITE_VALIDATION_BLOCKED"
    assert history[-1]["data"]["gates"][0]["result_ref"] == later.to_json()
