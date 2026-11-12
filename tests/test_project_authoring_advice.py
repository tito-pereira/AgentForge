# SPDX-License-Identifier: MPL-2.0
"""Exercise the assisted authoring flow with synthetic native probe results."""

import json

import pytest
from test_project_manager import _published_prr

from corinthos.adapters.model import AgentResult
from corinthos.contracts import ConflictError
from corinthos.project_manager.authoring_advice import author_with_advice
from corinthos.project_manager.service import ProjectManager

_ACTOR = "local-owner"
_IDEA = "Build a local notes CLI that creates and lists notes using SQLite."


def _response(**overrides):
    return {
        "detected": ["A local notes CLI with SQLite storage."],
        "missing": ["Observable project success criteria."],
        "scope": ["Create and list notes"],
        "requirements": [
            {
                "description": "Users can create notes.",
                "criteria": ["The listing contains a newly added note."],
            }
        ],
        "constraints": [],
        "success_criteria": [],
        "questions": ["Must notes support deletion?"],
        "alternatives": [
            {
                "topic": "Storage",
                "options": [
                    {"description": "Use SQLite.", "trade_off": "Structured queries."},
                    {"description": "Use JSON.", "trade_off": "Simpler local file format."},
                ],
                "recommendation": 1,
            }
        ],
        **overrides,
    }


def _probe(monkeypatch, output=None, *, status="COMPLETED", before_return=None):
    calls = []
    if output is None:
        output = json.dumps(_response())

    def probe(_adapter, provider, root, prompt, *, timeout):
        calls.append((provider, root, prompt, timeout))
        if before_return:
            before_return()
        return AgentResult(provider, status, "synthetic-task", "synthetic-attempt", output=output)

    monkeypatch.setattr("corinthos.adapters.service.AdapterManager.probe", probe)
    return calls


def _answer(monkeypatch, *answers):
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))


def _author(manager, snapshot):
    return author_with_advice(manager, snapshot, _ACTOR, completion=lambda *_: None)


def test_detailed_idea_is_analyzed_without_accepting_or_publishing(tmp_path, monkeypatch, capsys):
    manager = ProjectManager(tmp_path)
    started = manager.start(_IDEA, actor_id=_ACTOR)
    calls = _probe(monkeypatch, "```json\n" + json.dumps(_response()) + "\n```")
    _answer(monkeypatch, "1", "1", "1", "3", "0", "6")
    snapshot, route = _author(manager, started)

    assert route == "gaps"
    assert manager.get(started["session_id"]) == snapshot == started
    assert not manager.store.list_events()
    assert len(calls) == 1
    assert calls[0][:2] == ("codex", tmp_path)
    assert _IDEA in calls[0][2]
    output = capsys.readouterr().out
    assert "A local notes CLI with SQLite storage." in output
    assert "Observable project success criteria." in output
    assert "Must notes support deletion?" in output
    assert "Suggestion dismissed." in output


def test_accept_edit_and_back_apply_only_the_confirmed_fields(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    started = manager.start(_IDEA, actor_id=_ACTOR)
    _probe(monkeypatch)
    _answer(
        monkeypatch,
        "1",  # Codex
        "1",  # Review suggestions
        "1",
        "1",  # Add the scope item
        "1",
        "2",
        "/back",  # Abandon the first requirement edit
        "1",
        "2",
        "Users can create named notes.",
        "",
        "1",  # Keep the criterion and confirm
        "0",  # Back to main authoring
    )
    snapshot, route = _author(manager, started)

    assert route is None
    assert manager.get(started["session_id"]) == snapshot
    assert snapshot["version"] == started["version"] + 2
    payload = snapshot["payload"]
    assert payload["scope"]["included"] == ["Create and list notes"]
    (requirement,) = payload["requirements"]
    assert requirement["description"] == "Users can create named notes."
    assert requirement["acceptance_criteria"][0]["criterion"] == (
        "The listing contains a newly added note."
    )
    assert not snapshot["questions"]
    assert snapshot["review"] is None
    assert not manager.store.list_events()


def test_alternatives_and_questions_require_explicit_choices(tmp_path, monkeypatch, capsys):
    manager = ProjectManager(tmp_path)
    started = manager.start(_IDEA, actor_id=_ACTOR)
    calls = _probe(monkeypatch)
    _answer(
        monkeypatch,
        "2",  # Claude Code
        "3",
        "1",
        "3",  # Request different options for Storage
        "3",
        "1",
        "2",
        "1",  # Select JSON and add it as a constraint
        "2",
        "1",
        "No, leave deletion out of scope.",
        "1",
        "7",
    )
    snapshot, route = _author(manager, started)

    assert route == "manual"
    assert len(calls) == 2 and all(call[0] == "claude" for call in calls)
    assert "Use SQLite." in calls[1][2]
    assert "Structured queries. (agent recommendation)" in capsys.readouterr().out
    (constraint,) = snapshot["payload"]["constraints"]
    assert constraint["description"] == "Use JSON."
    (question,) = snapshot["questions"]
    assert question["answer"] == "No, leave deletion out of scope."
    assert not snapshot["payload"]["requirements"]
    assert not manager.store.list_events()


@pytest.mark.parametrize(
    ("status", "output"),
    [
        ("UNAVAILABLE", ""),
        ("COMPLETED", "Unstructured response."),
        ("COMPLETED", json.dumps(_response(action="approve"))),
        ("COMPLETED", json.dumps(_response(scope=["Do not pass\x1b controls."]))),
    ],
)
def test_unusable_provider_offers_guided_and_manual_fallback(
    tmp_path, monkeypatch, capsys, status, output
):
    manager = ProjectManager(tmp_path)
    started = manager.start(_IDEA, actor_id=_ACTOR)
    _probe(monkeypatch, output, status=status)
    _answer(monkeypatch, "1", "1")
    assert _author(manager, started) == (started, "gaps")
    assert manager.get(started["session_id"]) == started
    rendered = capsys.readouterr().out
    assert "Agent assistance" in rendered
    assert "Walk through missing information" in rendered
    assert "Configure manually" in rendered


def test_advice_becomes_stale_if_draft_changes_during_probe(tmp_path, monkeypatch):
    manager = ProjectManager(tmp_path)
    started = manager.start(_IDEA, actor_id=_ACTOR)

    def other_editor():
        manager.edit(
            started["session_id"],
            started["version"],
            {"action": "set_vision", "text": "Other editor's accepted idea."},
            actor_id=_ACTOR,
        )

    _probe(monkeypatch, before_return=other_editor)
    _answer(monkeypatch, "1")
    with pytest.raises(ConflictError, match="draft changed"):
        _author(manager, started)
    current = manager.get(started["session_id"])
    assert current["version"] == started["version"] + 1
    assert current["payload"]["vision"] == "Other editor's accepted idea."
    assert not current["payload"]["requirements"]


def test_bounded_revision_advice_keeps_approved_obligations_unchanged(
    tmp_path, monkeypatch, capsys
):
    manager = ProjectManager(tmp_path)
    base, request = _published_prr(manager)
    started = manager.receive_prr(request, "STRUCTURAL", actor_id=_ACTOR)
    events = manager.store.list_events()
    _probe(monkeypatch)
    _answer(monkeypatch, "1", "1", "3", "1", "1", "0", "6")

    assert _author(manager, started) == (started, "manual")
    assert manager.get(started["session_id"])["payload"] == base["payload"]
    assert manager.store.list_events() == events
    assert "edit the obligations covered by this request" in capsys.readouterr().out
