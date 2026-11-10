# SPDX-License-Identifier: MPL-2.0
"""Real planning CLI journeys use synthetic published fixtures, never human consent."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from test_project_manager import _synthetic_publish

from corinthos.workflow.cli import _consumed, _provided
from corinthos.workflow.presentation import render_plan_review
from corinthos.workflow.service import WorkflowPlanner


def seed_project(root):
    planner = WorkflowPlanner(root)
    path = Path(__file__).resolve().parents[1] / "examples" / "contracts" / "project.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    reference = _synthetic_publish(planner, document)  # Test-only trusted synthetic proof.
    return planner, reference


def run_workflow(root, *arguments, answers=""):
    return subprocess.run(
        [sys.executable, "-m", "corinthos", "workflow", "--root", str(root), *arguments],
        input=answers,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
        timeout=30,
    )


def planning_answers():
    return "\n".join(
        [
            "1",  # Explicit published Project revision selection.
            "1",
            "1",
            "Format greetings for Inês.",
            "Format a local greeting.",
            "",
            "",
            "1",
            "",
            "2",
            "1",
            "Greeting runtime",
            "Support the approved offline greeting.",
            "1",
            "1,2,3",
            "Reproducible local execution",
            "",
            "1",
            "Python 3.12",
            "1",
            "The approved environment supports the runtime.",
            "Available in the approved environment",
            "",
            "Runtime installation required",
            "",
            "Unsupported hosts need separate review",
            "",
            "Supports the offline constraint",
            "",
            "4",
            "Choose a runtime compatible with the documented environment.",
            "Python 3.12 runtime",
            "",
            "A fresh environment runs the greeting example.",
            "",
            "2",
            "2",
            "1",
            "1",
            "1",
            "Select the evaluated compatible local runtime.",
            "5",
            "1",
            "1",
            "7",
            "1",
            "Implement greeting",
            "Deliver the specified greeting behavior.",
            "1",
            "1",
            "Source, regression tests and setup instructions",
            "",
            "Input Ada produces Hello, Ada in a clean environment.",
            "",
            "Run positive and negative tests and review the setup documentation.",
            "",
            "10",
            "12",
            "",
        ]
    )


def test_guided_technology_module_checkpoint_review_and_restart_without_json(tmp_path):
    planner, project_ref = seed_project(tmp_path)
    result = run_workflow(tmp_path, "plan", project_ref.contract_id, answers=planning_answers())
    assert result.returncode == 0, result.stderr + result.stdout
    assert "WORKFLOW PLANNING REVIEW" in result.stdout
    assert "TECHNOLOGY DECISION CONTRACT REVIEW" in result.stdout
    assert "MODULE CONTRACT REVIEW" in result.stdout
    assert "WORKFLOW CONTRACT REVIEW" in result.stdout
    snapshot = planner.list()[0]
    assert snapshot["state"] == "DEFERRED"
    assert len(snapshot["draft"]["modules"]) == 1
    decision = next(iter(snapshot["draft"]["decisions"].values()))
    assert decision["payload"]["selected_option"]["source"] == "RECOMMENDED"
    assert decision["payload"]["ai_recommendations"][0]["technology"] == "Python 3.12"
    module = next(iter(snapshot["draft"]["modules"].values()))
    assert len(module["verification_spec"]["quality_checks"]) >= 5
    assert all(check["blocking"] for check in module["verification_spec"]["quality_checks"])
    assert snapshot["draft"]["playtest_milestones"] == {}
    resumed = run_workflow(tmp_path, "resume", snapshot["session_id"], answers="9\n12\n")
    assert resumed.returncode == 0, resumed.stderr
    assert module["module_id"] in resumed.stdout
    assert "NOT_VERIFIED" in resumed.stdout
    assert len(planner.list()) == 1
    assert len(planner.store.list_events()) == 1  # Only the synthetic Project was published.


def test_planning_publication_rejects_piped_approval(tmp_path):
    planner, reference = seed_project(tmp_path)
    result = run_workflow(tmp_path, "plan", reference.contract_id, answers=planning_answers())
    assert result.returncode == 0, result.stderr
    snapshot = planner.list()[0]
    denied = run_workflow(tmp_path, "publish", snapshot["session_id"], answers="APPROVE\nyes\n")
    assert denied.returncode == 1
    assert "terminal" in denied.stderr.lower()
    assert len(planner.store.list_events()) == 1


def test_a_mandate_id_cannot_substitute_for_recorded_authority(tmp_path):
    planner, reference = seed_project(tmp_path)
    prepared = run_workflow(tmp_path, "plan", reference.contract_id, answers=planning_answers())
    assert prepared.returncode == 0, prepared.stderr
    session = planner.list()[0]
    denied = run_workflow(
        tmp_path, "publish", session["session_id"], "--mandate", "invented-mandate"
    )
    assert denied.returncode == 1
    assert "Traceback" not in denied.stderr
    assert len(planner.store.list_events()) == 1


@pytest.mark.parametrize("action", ["show", "resume", "review", "history", "publish"])
def test_malformed_saved_plan_is_rejected_without_private_text_or_traceback(tmp_path, action):
    planner, reference = seed_project(tmp_path)
    session = planner.start(reference, actor_id="synthetic-test-actor")
    malformed = {
        "session_id": session["session_id"],
        "project_id": session["project_id"],
        "version": session["version"],
        "private": "PRIVATE-PLANNING-CONTENT",
    }
    with planner.store._transaction() as connection:
        connection.execute(
            "UPDATE wf_sessions SET snapshot=? WHERE session_id=?",
            (json.dumps(malformed), session["session_id"]),
        )
    result = run_workflow(tmp_path, action, session["session_id"])
    assert result.returncode == 1
    assert "Planning operation failed" in result.stderr
    assert "Traceback" not in result.stderr
    assert "PRIVATE-PLANNING-CONTENT" not in result.stdout + result.stderr
    assert len(planner.store.list_events()) == 1


def test_eof_retains_planning_identity_and_reports_resume(tmp_path):
    planner, reference = seed_project(tmp_path)
    result = run_workflow(tmp_path, "plan", reference.contract_id, answers="1\n")
    assert result.returncode == 130
    assert "Accepted planning choices are saved" in result.stdout
    assert "Traceback" not in result.stderr
    assert planner.list()[0]["project_ref"] == reference.to_json()


def test_workflow_help_preserves_explicit_a_to_d_boundary(tmp_path):
    result = run_workflow(tmp_path, "--help")
    assert result.returncode == 0
    for command in ("plan", "review", "publish", "resume", "history"):
        assert command in result.stdout
    denied = run_workflow(tmp_path, "run")
    assert denied.returncode == 2


def test_interface_editor_generates_revisions_and_selects_exact_provider_links(monkeypatch):
    module = {
        "module_id": "provider",
        "provided_interfaces": [],
        "consumed_interfaces": [],
        "purpose_and_boundaries": {"purpose": "Greeting provider"},
    }
    answers = iter(
        [
            "1",
            "Python callable",
            "A display name",
            "",
            "A greeting",
            "",
            "",
            "",
            "Offline output",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    operation = _provided(module)
    interface = operation["interfaces"][0]
    assert interface["interface_type"] == "Python callable"
    assert interface["interface_id"] and interface["interface_revision"]
    module["provided_interfaces"] = operation["interfaces"]
    consumer = {"module_id": "consumer", "consumed_interfaces": []}
    snapshot = {"draft": {"modules": {"provider": module, "consumer": consumer}}}
    answers = iter(["1", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    consumed = _consumed(snapshot, consumer)["interfaces"][0]
    assert consumed == {
        "provider_module_id": "provider",
        "interface_id": interface["interface_id"],
        "required_interface_revision": interface["interface_revision"],
    }


def test_full_plan_review_includes_scope_explanations_digests_differences_and_safe_text():
    base = {
        "metadata": {
            "contract_id": "module-contract",
            "revision_id": "r1",
            "contract_type": "MODULE",
        },
        "payload": {"purpose": "Original"},
    }
    candidate = deepcopy(base)
    candidate["metadata"]["revision_id"] = "r2"
    candidate["payload"] = {
        "purpose": "Changed\x1b[2J\u202eFAKE",
        "checks": ["M1", "M2", "M3", "M4", "M5"],
    }
    snapshot = {
        "session_id": "session",
        "version": 2,
        "project_ref": {"revision_id": "project-r1"},
        "review": {
            "documents": [candidate],
            "sha256": "whole-set-digest",
            "expires_at": 1800000000,
        },
        "compiled_refs": [{"revision_id": "r2"}],
        "draft": {
            "modules": {"module": {"constraint_exemptions": {"C2": "Explicit module scope reason"}}}
        },
    }
    rendered = render_plan_review(
        snapshot, previous=[base], warnings=["Feasibility requires human review"]
    )
    assert "whole-set-digest" in rendered and "project-r1" in rendered
    assert "Explicit module scope reason" in rendered
    assert "-    Original" in rendered and "+    Changed" in rendered
    assert "\x1b" not in rendered and "\u202e" not in rendered
    assert "\\u001b" in rendered and "\\u202e" in rendered
    for rule in ("M1", "M2", "M3", "M4", "M5"):
        assert rule in rendered
