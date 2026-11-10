# SPDX-License-Identifier: MPL-2.0
"""Real CLI configuration and handoff tests use synthetic published contract fixtures."""

import io
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_workflow_planning import publish
from test_workflow_reconciliation import published_plan, successor
from test_workflow_runtime import SyntheticAdapter, _accept, _seed, _spec, _write_code

from corinthos.cli import main
from corinthos.contracts import AuthorityError, ContractRef
from corinthos.workflow.execution_repository import ExecutionRepository
from corinthos.workflow.reconciliation import RevisionReconciler
from corinthos.workflow.runtime import WorkflowRunner
from corinthos.workflow.runtime_cli import _carry_completed, _technical_review


def run_cli(root, *arguments, answers=""):
    return subprocess.run(
        [sys.executable, "-m", "corinthos", "workflow", "--root", str(root), *arguments],
        input=answers,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
        timeout=30,
        cwd=Path(__file__).resolve().parents[1],
    )


def configuration_answers(workflow):
    answers = ["1"]
    for checkpoint in workflow["payload"]["checkpoints"]:
        for _ in checkpoint["verification_plan"]:
            answers.extend(["1", sys.executable, "-c", "print('actual verification')", "", ""])
        paths = []
        for index, _ in enumerate(checkpoint["deliverables"]):
            name = f"{checkpoint['checkpoint_id']}-artifact-{index}.txt"
            paths.append(name)
            answers.extend([name, ""])
        answers.extend([*paths, ""])
    return "\n".join([*answers, ""])


def test_guided_runtime_configuration_and_status_need_no_json_or_agent(tmp_path):
    planner, workflow, _ = published_plan(tmp_path)
    result = run_cli(
        tmp_path,
        "configure",
        workflow["metadata"]["contract_id"],
        answers=configuration_answers(workflow),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "CHECKPOINT EXECUTION CONFIGURATION" in result.stdout
    repository = ExecutionRepository(planner.store)
    execution = repository.list()[0]
    assert execution["workflow_ref"] == ContractRef.from_document(workflow).to_json()
    for checkpoint in workflow["payload"]["checkpoints"]:
        bound = execution["bindings"]["checkpoints"][checkpoint["checkpoint_id"]]
        assert bound["commands"][0]["argv"][0] == sys.executable
        assert set(bound["deliverables"]) == set(checkpoint["deliverables"])
    shown = run_cli(tmp_path, "status", execution["execution_id"])
    assert shown.returncode == 0, shown.stderr
    assert execution["execution_id"] in shown.stdout
    assert "RUNNING" not in shown.stdout
    listing = run_cli(tmp_path, "executions")
    assert execution["execution_id"] in listing.stdout
    assert len(planner.store.list_events()) == 4  # No new canonical contract was created.


def test_unavailable_provider_and_blocked_no_eligible_work_return_failure(tmp_path):
    planner, workflow, _ = published_plan(tmp_path)
    prepared = run_cli(
        tmp_path,
        "configure",
        workflow["metadata"]["contract_id"],
        answers=configuration_answers(workflow),
    )
    assert prepared.returncode == 0, prepared.stderr
    repository = ExecutionRepository(planner.store)
    execution = repository.list()[0]
    for _ in range(2):
        result = run_cli(
            tmp_path,
            "execute",
            execution["execution_id"],
            "--provider-executable",
            str(tmp_path / "missing-native-provider.exe"),
        )
        assert result.returncode == 1, result.stderr + result.stdout
    assert repository.get(execution["execution_id"])["state"] == "BLOCKED"


def test_finished_execution_with_no_eligible_work_returns_success(tmp_path):
    store, reference = _seed(tmp_path)
    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=_accept)
    execution = runner.configure(reference, [_spec()], actor_id="synthetic-test-operator")
    assert runner.run_next(execution["execution_id"])["state"] == "COMPLETED"
    result = run_cli(tmp_path, "execute", execution["execution_id"])
    assert result.returncode == 0, result.stderr
    assert "No eligible checkpoint was dispatched" in result.stdout


def test_pending_unaffected_checkpoints_are_reset_without_invalid_carry(tmp_path):
    planner, workflow, _ = published_plan(tmp_path, second_checkpoint=True)
    configured = run_cli(
        tmp_path,
        "configure",
        workflow["metadata"]["contract_id"],
        answers=configuration_answers(workflow),
    )
    assert configured.returncode == 0, configured.stderr
    repository = ExecutionRepository(planner.store)
    execution = repository.list()[0]
    revised = successor(workflow)
    for row in revised["payload"]["checkpoints"]:
        if row["checkpoint_id"] == "checkpoint-second":
            row["depends_on"] = ["greet"]
    reference = publish(planner.store, revised)
    result = run_cli(
        tmp_path,
        "reconcile",
        execution["execution_id"],
        reference.contract_id,
        "--revision",
        reference.revision_id,
        answers="1\n\n\nExplicit dependency replan.\n",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "EXACT RECONCILIATION DISPOSITION" in result.stdout
    assert repository.get(execution["execution_id"])["state"] == "SUPERSEDED"
    current = next(
        item for item in repository.list() if item["execution_id"] != execution["execution_id"]
    )
    assert all(item["state"] == "PENDING" for item in current["checkpoints"].values())


def test_changed_binding_resets_completed_dependent_closure():
    old = {
        "first": {"argv": ["first"]},
        "second": {"argv": ["second"]},
        "pending": {"argv": ["pending"]},
    }
    execution = {
        "bindings": {"checkpoints": old},
        "checkpoints": {
            "first": {"state": "COMPLETED"},
            "second": {"state": "COMPLETED"},
            "pending": {"state": "PENDING"},
        },
    }
    workflow = {
        "payload": {
            "checkpoints": [
                {"checkpoint_id": "first", "depends_on": []},
                {"checkpoint_id": "second", "depends_on": ["first"]},
                {"checkpoint_id": "pending", "depends_on": []},
            ]
        }
    }
    bindings = {"checkpoints": deepcopy(old)}
    proposed = ["first", "second", "pending"]
    assert _carry_completed(execution, workflow, bindings, proposed) == ["first", "second"]
    bindings["checkpoints"]["first"] = {"argv": ["changed-check"]}
    assert _carry_completed(execution, workflow, bindings, proposed) == []


def test_verification_only_recovery_retains_nonzero_status_for_rejected_review(
    tmp_path, monkeypatch, capsys
):
    store, reference = _seed(tmp_path)

    def reviewer(request):
        return replace(
            _accept(request), accepted=False, findings=("Synthetic reservations remain.",)
        )

    runner = WorkflowRunner(
        tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=reviewer
    )
    execution = runner.configure(reference, [_spec()], actor_id="synthetic-test-operator")
    first = runner.run_next(execution["execution_id"])
    assert first["state"] == "BLOCKED"
    monkeypatch.setattr(
        "corinthos.workflow.runtime_cli._runner", lambda arguments, supplied: runner
    )
    answers = iter(
        [
            "STOPPED",
            "INSPECTED",
            "Synthetic inspection confirms stopped process and retained source.",
            "2",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    result = main(
        ["workflow", "--root", str(tmp_path), "recover", execution["execution_id"], "greet"]
    )
    assert result == 1
    assert "BLOCKED" in capsys.readouterr().out


def test_changes_cli_and_ordinary_failure_do_not_escalate_product_scope(tmp_path):
    planner, workflow, _ = published_plan(tmp_path)
    reference = workflow["metadata"]["contract_id"]
    inspected = run_cli(tmp_path, "changes", reference, answers="1\n")
    assert inspected.returncode == 0, inspected.stderr
    assert "Current" in inspected.stdout and "True" in inspected.stdout
    before = planner.store.list_events()
    ordinary = run_cli(tmp_path, "request", reference, answers="1\n2\n")
    assert ordinary.returncode == 0, ordinary.stderr
    assert "scoped repair or recovery" in ordinary.stdout
    assert planner.store.list_events() == before


def test_owner_change_cli_opens_real_pm_without_a_fake_structural_request(tmp_path):
    planner, workflow, _ = published_plan(tmp_path)
    before = planner.store.list_events()
    result = run_cli(
        tmp_path,
        "request",
        workflow["metadata"]["contract_id"],
        answers="1\n3\nThe owner wants another supported target.\n",
    )
    assert result.returncode == 0, result.stderr
    assert "Project Manager revision session" in result.stdout
    assert "corinthos project resume" in result.stdout
    assert planner.store.list_events() == before


def test_guided_structural_request_publishes_bounded_real_kernel_record(tmp_path):
    planner, workflow, _ = published_plan(tmp_path)
    answers = [
        "1",
        "1",
        "1",
        "1",
        "1",
        "2",  # Exact WF, structural type and affected IDs.
        "The planned runtime conflicts with an evidenced deployment constraint.",
        "The exact plan requires a local Python runtime.",
        "",
        "The owner's target choice is unresolved.",
        "",
        "4",
        "The exact published Workflow identifies its approved runtime decision.",
        "Synthetic test diagnosis with no executed target failure.",
        "",
        "Retain hosts with the supported runtime.",
        "Narrower supported environments",
        "",
        "Test the supported environment",
        "",
        "Document prerequisites",
        "",
        "Unsupported hosts remain excluded",
        "",
        "",
        "1",
        "1",
        "1",  # Impact modules, checkpoint and technology.
        "Retest local setup",
        "",
        "Update prerequisites after owner approval",
        "",
        "Target choice is open",
        "",
        "Keep the greeting offline",
        "",
        "REQUEST",
        "",
    ]
    result = run_cli(
        tmp_path,
        "request",
        workflow["metadata"]["contract_id"],
        "--request-id",
        "cli-structural-request",
        answers="\n".join(answers),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Published request reference" in result.stdout
    records = [
        row
        for row in planner.store.list_events()
        if row["contract_type"] == "PROJECT_REVISION_REQUEST"
    ]
    assert len(records) == 1
    row = records[0]
    request = planner.store.get(
        ContractRef(row["contract_id"], row["revision_id"], row["contract_type"], row["project_id"])
    )
    assert request["payload"]["request_id"] == "cli-structural-request"
    assert request["payload"]["evidence"][0]["evidence_ids"] == []
    assert request["metadata"]["approval"] is None
    assert RevisionReconciler(planner.store).inspect(ContractRef.from_document(workflow))["current"]


def test_missing_execution_is_a_controlled_error(tmp_path):
    published_plan(tmp_path)
    result = run_cli(tmp_path, "status", "missing-execution")
    assert result.returncode == 1
    assert "Execution operation failed" in result.stderr
    assert "Traceback" not in result.stderr


def test_scripted_input_cannot_supply_production_technical_review():
    with pytest.raises(AuthorityError, match="terminal"):
        _technical_review({})


def test_technical_review_fixture_binds_every_actual_criterion_and_artifact(monkeypatch):
    """A synthetic test terminal exercises presentation without adding a production consent path."""
    output = io.StringIO()

    class SyntheticReader:
        def readline(self, limit):
            if not hasattr(self, "answered"):
                self.answered = True
                return re.search(r"Type (ACCEPT [a-f0-9]{12})", output.getvalue()).group(1) + "\n"
            return "Reviewed the actual test output and documented boundary.\n"

    @contextmanager
    def terminal():
        yield SyntheticReader(), output

    monkeypatch.setattr("corinthos.workflow.runtime_cli._terminal", terminal)
    request = {
        "checkpoint": {
            "completion_criteria": [
                {"criterion_id": "A", "criterion": "Observed result"},
                {"criterion_id": "B", "criterion": "Observed error path"},
            ]
        },
        "artifact_identity": {"snapshot_id": "actual-observed-snapshot"},
        "checks": [{"state": "PASSED"}],
        "changed_paths": ["source.py"],
        "evidence": [],
        "deliverables": {"Source": ["source.py"]},
    }
    review = _technical_review(request)
    assert review.accepted
    assert review.criterion_ids == ("A", "B")
    assert review.artifact_identity == request["artifact_identity"]
    assert "PRELIMINARY ENGINEERING" in output.getvalue()
