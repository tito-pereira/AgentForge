# SPDX-License-Identifier: MPL-2.0
"""Exercise the real guided CLI while keeping production approval unavailable."""

import json
import os
import subprocess
import sys
from copy import deepcopy

import pytest
from test_project_manager import _published_prr

from corinthos.cli import main
from corinthos.contracts import ContractRef, IntegrityError
from corinthos.project_manager.cli import _linked, _show_request
from corinthos.project_manager.presentation import render_review, safe_text
from corinthos.project_manager.service import ProjectManager


def run_project(root, *arguments, answers=""):
    return subprocess.run(
        [sys.executable, "-m", "corinthos", "project", "--root", str(root), *arguments],
        input=answers,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
        timeout=20,
    )


def complete_draft_answers():
    return "\n".join(
        [
            "Build a local greeting for Inês.",
            "2",
            "1",
            "Greeting output for a supplied name",
            "",
            "3",
            "1",
            "Print a greeting for the supplied name.",
            "Input Inês produces Hello, Inês.",
            "",
            "4",
            "1",
            "Run offline.",
            "5",
            "1",
            "A fresh installation reproduces the documented greeting.",
            "6",
            "1",
            "2",
            "Keep greeting generation local.",
            "",
            "1",
            "1",
            "",
            "6",
            "3",
            "1",
            "1",
            "Accept local generation.",
            "Respect the offline constraint.",
            "9",
            "11",
            "",
        ]
    )


def test_guided_project_can_be_reviewed_and_resumed_without_json(tmp_path):
    result = run_project(tmp_path, "start", answers=complete_draft_answers())
    assert result.returncode == 0, result.stderr + result.stdout
    assert "PROJECT CONTRACT REVIEW" in result.stdout
    assert "Canonical SHA-256" in result.stdout
    assert "Run offline." in result.stdout
    assert "Respect the offline constraint." in result.stdout
    assert "Published Project Contract" not in result.stdout
    manager = ProjectManager(tmp_path)
    sessions = manager.list()
    assert len(sessions) == 1
    saved = sessions[0]
    assert saved["state"] == "DEFERRED"
    assert len(saved["payload"]["requirements"]) == 1
    assert saved["payload"]["requirements"][0]["acceptance_criteria"][0]["criterion"] == (
        "Input Inês produces Hello, Inês."
    )
    proposal = next(iter(saved["proposals"].values()))
    assert proposal["status"] == "ACCEPTED"
    assert proposal["proposal"]["kind"] == "REQUIREMENT"
    original_id = saved["payload"]["requirements"][0]["requirement_id"]
    resumed = run_project(tmp_path, "resume", saved["session_id"], answers="8\n11\n")
    assert resumed.returncode == 0, resumed.stderr + resumed.stdout
    assert original_id in resumed.stdout
    assert len(manager.list()) == 1
    assert manager.get(saved["session_id"])["session_id"] == saved["session_id"]
    assert manager.store.list_events() == []


def test_scripted_approval_cannot_publish_a_real_session(tmp_path):
    result = run_project(tmp_path, "start", answers=complete_draft_answers())
    assert result.returncode == 0, result.stderr
    manager = ProjectManager(tmp_path)
    session = manager.list()[0]
    denied = run_project(tmp_path, "approve", session["session_id"], answers="yes\nAPPROVE\n")
    assert denied.returncode == 1
    assert "interactive terminal" in denied.stderr
    assert manager.store.list_events() == []
    assert manager.get(session["session_id"])["published_ref"] is None


@pytest.mark.parametrize("final_answer", ["", "invalid choice\n"])
def test_eof_retains_the_last_accepted_idea(tmp_path, final_answer):
    result = run_project(tmp_path, "start", answers="Organize a small garden.\n" + final_answer)
    assert result.returncode == 130
    assert "Accepted changes are saved" in result.stdout
    assert "Traceback" not in result.stderr
    manager = ProjectManager(tmp_path)
    session = manager.list()[0]
    assert session["payload"]["vision"] == "Organize a small garden."
    assert manager.store.list_events() == []


def test_empty_and_large_answers_are_reprompted_before_persisting(tmp_path):
    result = run_project(tmp_path, "start", answers="\n" + "x" * 8193 + "\nA modest project.\n11\n")
    assert result.returncode == 0, result.stderr
    assert "Enter an answer" in result.stdout
    assert "8192 characters" in result.stdout
    assert ProjectManager(tmp_path).list()[0]["payload"]["vision"] == "A modest project."


def test_ctrl_c_preserves_accepted_state_without_publication(tmp_path, monkeypatch, capsys):
    answers = iter(["Keep a daily reading list."])

    def interrupt_after_idea(prompt):
        try:
            return next(answers)
        except StopIteration:
            raise KeyboardInterrupt from None

    monkeypatch.setattr("builtins.input", interrupt_after_idea)
    assert main(["project", "start", "--root", str(tmp_path)]) == 130
    assert "Accepted changes are saved" in capsys.readouterr().out
    manager = ProjectManager(tmp_path)
    assert manager.list()[0]["payload"]["vision"] == "Keep a daily reading list."
    assert manager.store.list_events() == []


def test_incomplete_review_reports_clarification_without_publishing(tmp_path):
    started = run_project(tmp_path, "start", answers="A project needing more detail.\n11\n")
    assert started.returncode == 0
    manager = ProjectManager(tmp_path)
    session = manager.list()[0]
    result = run_project(tmp_path, "review", session["session_id"])
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert manager.store.list_events() == []


def test_session_selection_and_history_work_after_restart(tmp_path):
    run_project(tmp_path, "start", answers="First idea.\n11\n")
    result = run_project(tmp_path, "show", answers="1\n")
    assert result.returncode == 0, result.stderr
    assert "First idea." in result.stdout
    assert "PRELIMINARY ASSESSMENT" in result.stdout
    listing = run_project(tmp_path, "sessions")
    assert "DEFERRED" in listing.stdout
    session = ProjectManager(tmp_path).list()[0]
    history = run_project(tmp_path, "history", session["session_id"])
    assert history.returncode == 0
    assert "First idea." in history.stdout


def test_review_renders_every_field_full_diff_and_visible_terminal_controls():
    previous = {"metadata": {"revision_id": "old"}, "payload": {"vision": "Original vision"}}
    candidate = deepcopy(previous)
    candidate["metadata"] = {"revision_id": "new", "approval": {"approval_id": "receipt-1"}}
    candidate["payload"] = {
        "vision": "Changed vision\x1b[2J\u202eAPPROVED\nHidden heading",
        "scope": {"included": ["Visible scope"], "excluded": [], "assumptions": [], "risks": []},
        "requirements": [
            {
                "requirement_id": "R1",
                "acceptance_criteria": [
                    {"criterion_id": "AC1", "criterion": "Observe the output."}
                ],
            }
        ],
        "constraints": [{"constraint_id": "C1", "description": "Offline"}],
        "success_criteria": [{"criterion_id": "SC1", "criterion": "Repeatable"}],
        "structural_proposals": [{"proposal_id": "P1", "kind": "REQUIREMENT"}],
        "negotiated_decisions": [{"decision_id": "D1", "rationale": "User supplied reason"}],
    }
    rendered = render_review(
        candidate,
        base_document=previous,
        sha256="exact-digest",
        expires_at=1800000000,
        warnings=["Feasibility NOT_VERIFIED"],
    )
    assert "\x1b" not in rendered and "\u202e" not in rendered
    assert "\\u001b" in rendered and "\\u202e" in rendered and "\\u000aHidden heading" in rendered
    for value in [
        "R1",
        "AC1",
        "C1",
        "SC1",
        "P1",
        "D1",
        "receipt-1",
        "Visible scope",
        "User supplied reason",
    ]:
        assert value in rendered
    assert "-    Original vision" in rendered
    assert "+    Changed vision" in rendered
    assert "exact-digest" in rendered and "Feasibility NOT_VERIFIED" in rendered
    assert candidate["payload"]["vision"].endswith("\nHidden heading")
    assert safe_text("Inês") == "Inês"


def test_existing_proposal_links_can_be_kept_replaced_or_cleared(monkeypatch):
    items = [
        {"requirement_id": "R1", "description": "First requirement"},
        {"requirement_id": "R2", "description": "Second requirement"},
    ]
    answers = iter(["", "2", "/clear"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert _linked(items, "requirement_id", existing=["R1"]) == ["R1"]
    assert _linked(items, "requirement_id", existing=["R1"]) == ["R2"]
    assert _linked(items, "requirement_id", existing=["R1"]) == []


def test_prr_details_precede_triage_and_are_available_on_resume_and_show(tmp_path):
    manager = ProjectManager(tmp_path)
    _, reference = _published_prr(manager)  # Synthetic trusted Kernel fixture only.
    result = run_project(tmp_path, "request", reference.contract_id, answers="1\n1\n11\n")
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.index("A deployment target without Python") < result.stdout.index(
        "1. STRUCTURAL"
    )
    for content in [
        "Portable where the runtime is available",
        "Hosts without Python remain unsupported.",
        "The target decision remains open.",
        "The selected runtime and its installation requirement",
    ]:
        assert content in result.stdout
    session = manager.list()[0]
    shown = run_project(tmp_path, "show", session["session_id"])
    assert "Hosts without Python remain unsupported." in shown.stdout
    resumed = run_project(tmp_path, "resume", session["session_id"], answers="11\n")
    assert "The target decision remains open." in resumed.stdout
    reviewed = run_project(tmp_path, "review", session["session_id"])
    assert "A deployment target without Python" in reviewed.stdout


@pytest.mark.parametrize("action", ["show", "resume", "approve", "history"])
def test_corrupt_session_fails_without_traceback_private_text_or_publication(tmp_path, action):
    manager = ProjectManager(tmp_path)
    session = manager.start("A saved project.", actor_id="synthetic-test-actor")
    malformed = {
        "session_id": session["session_id"],
        "project_id": session["project_id"],
        "version": session["version"],
        "private": "PRIVATE-MALFORMED-CONTENT",
    }
    with manager.store._transaction() as connection:
        connection.execute(
            "UPDATE pm_sessions SET snapshot=? WHERE session_id=?",
            (json.dumps(malformed), session["session_id"]),
        )
    result = run_project(tmp_path, action, session["session_id"])
    assert result.returncode == 1
    assert "Project operation failed" in result.stderr
    assert "Traceback" not in result.stderr
    assert "PRIVATE-MALFORMED-CONTENT" not in result.stdout + result.stderr
    assert manager.store.list_events() == []


def test_missing_source_revision_request_fails_instead_of_rendering_null(tmp_path, capsys):
    manager = ProjectManager(tmp_path)
    reference = ContractRef("missing", "missing-r1", "PROJECT_REVISION_REQUEST", "project")
    with pytest.raises(IntegrityError, match="source revision request is unavailable"):
        _show_request(manager, reference)
    assert "(none)" not in capsys.readouterr().out
