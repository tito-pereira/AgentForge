# SPDX-License-Identifier: MPL-2.0
"""Project Completion follows structural review readiness without invoking advice."""

from unittest.mock import Mock

import pytest
from test_project_manager import _ACTOR, _edit, _published_prr, _ready

from corinthos.contracts import ConflictError, IntegrityError
from corinthos.project_manager.presentation import render_completion
from corinthos.project_manager.service import ProjectManager


def test_completion_counts_required_fields_and_reopens_without_advice(tmp_path):
    assistance = Mock()
    manager = ProjectManager(tmp_path, assistance=assistance)
    snapshot = manager.start("Create an offline greeting tool.", actor_id=_ACTOR)
    assert manager.completion(snapshot) == 20
    assert render_completion(20) == "Project Completion\n  [██░░░░░░░░] 20%"

    snapshot = _edit(
        manager, snapshot, action="set_scope", section="included", items=["Local greeting output"]
    )
    assert manager.completion(snapshot) == 40
    snapshot = _edit(
        manager,
        snapshot,
        action="upsert_requirement",
        description="Render a greeting.",
        acceptance_criteria=[{"criterion": "Input Ada produces Hello, Ada."}],
    )
    assert manager.completion(snapshot) == 60
    snapshot = _edit(
        manager,
        snapshot,
        action="upsert_success_criterion",
        criterion="A clean environment reproduces the greeting.",
    )
    reopened = ProjectManager(tmp_path, assistance=assistance)
    assert reopened.get(snapshot["session_id"]) == snapshot
    assert reopened.completion(snapshot) == 100
    assert render_completion(100) == "Project Completion\n  [██████████] 100%"
    assert reopened.assess(snapshot["session_id"], include_assistance=False)["issues"] == []
    assert reopened.get(snapshot["session_id"]) == snapshot
    reviewed = reopened.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    assert reviewed["review"]["document"]["payload"] == snapshot["payload"]
    assert reopened.store.list_events() == []
    assistance.assert_not_called()


def test_completion_withholds_final_points_until_questions_and_proposals_are_resolved(tmp_path):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    question = "Should the greeting run offline?"
    snapshot = _edit(manager, snapshot, action="set_question", text=question)
    snapshot = _edit(
        manager,
        snapshot,
        action="propose",
        kind="SUGGESTION",
        description="Offer remote greetings.",
        requirement_ids=[],
        constraint_ids=[],
    )
    assert manager.completion(snapshot) == 80
    with pytest.raises(IntegrityError, match="clarification"):
        manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    snapshot = _edit(
        manager,
        snapshot,
        action="set_question",
        question_id=snapshot["questions"][0]["question_id"],
        text=question,
        answer="Yes.",
    )
    assert manager.completion(snapshot) == 80
    snapshot = _edit(
        manager,
        snapshot,
        action="decide_proposal",
        proposal_id=next(iter(snapshot["proposals"])),
        status="REJECTED",
        decision="Keep greetings local.",
        rationale="Remote greetings are outside scope.",
    )
    assert manager.completion(snapshot) == 100


@pytest.mark.parametrize("criteria", [[], [{"criterion": "TBD"}]])
def test_every_requirement_needs_observable_criteria_for_completion(tmp_path, criteria):
    manager = ProjectManager(tmp_path)
    snapshot = _edit(
        manager,
        _ready(manager),
        action="upsert_requirement",
        description="Handle invalid input.",
        acceptance_criteria=criteria,
    )
    assert manager.completion(snapshot) == 60
    assert manager.structural_issues(snapshot)


def test_complete_fields_do_not_override_revision_or_prr_review_rules(tmp_path):
    manager = ProjectManager(tmp_path)
    _, prr_ref = _published_prr(manager)
    snapshot = manager.receive_prr(prr_ref, "STRUCTURAL", actor_id=_ACTOR)
    assert manager.completion(snapshot) == 80
    with pytest.raises(ConflictError, match="Unchanged negotiation"):
        manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)

    snapshot = _edit(
        manager,
        snapshot,
        action="upsert_requirement",
        description="Render a second greeting.",
        acceptance_criteria=[{"criterion": "Input Grace produces Hello, Grace."}],
    )
    assert manager.completion(snapshot) == 80
    with pytest.raises(IntegrityError, match="clarification"):
        manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
