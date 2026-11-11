# SPDX-License-Identifier: MPL-2.0
"""CLI and terminal-origin checks; terminal fixtures are explicitly synthetic."""

import argparse
from contextlib import contextmanager
from io import StringIO

import pytest

from corinthos.contracts import AuthorityError
from corinthos.lifecycle import playtest
from corinthos.lifecycle.playtest import PlaytestService
from corinthos.lifecycle.playtest_cli import add_cli


def _parser():
    parser = argparse.ArgumentParser()
    add_cli(parser.add_subparsers(required=True))
    return parser


def _available(root):
    """Synthetic historical admission, not a claim of a real validated build."""
    service = PlaytestService(root)
    service.configure("project-test", enabled=True)
    admission = {
        "build_id": "build-test",
        "project_id": "project-test",
        "milestone_id": "m1",
        "artifact_identity": {"build_id": "build-test"},
    }
    service.repository.create("BUILD", "project-test", {}, record_id="build-test", state="SEALED")
    service.repository.event(
        "project-test", "PLAYTEST_PROMOTED", {"admission": admission}, record_id="build-test"
    )
    return service


def test_help_and_status_have_no_native_work_or_event_churn(tmp_path, monkeypatch, capsys):
    parser = _parser()
    monkeypatch.setattr(
        playtest.BuildService,
        "require_eligible",
        lambda *args: pytest.fail("Read commands cannot evaluate native admission."),
    )
    with pytest.raises(SystemExit) as result:
        parser.parse_args(["playtest", "--help"])
    assert result.value.code == 0
    assert "retention-preview" in capsys.readouterr().out
    root = tmp_path / "project"
    root.mkdir()
    service = _available(root)
    events = service.repository.events("project-test")
    args = parser.parse_args(["playtest", "status", "project-test", "--root", str(root)])
    assert args.handler(args) == 0
    assert service.repository.events("project-test") == events


def test_operator_feedback_cli_escapes_controls_and_cannot_claim_human(tmp_path, capsys):
    root = tmp_path / "project"
    root.mkdir()
    service = _available(root)
    args = _parser().parse_args(
        [
            "playtest",
            "feedback",
            "project-test",
            "build-test",
            "--root",
            str(root),
            "--body",
            "Observed\x1b[31m issue",
            "--operation-id",
            "feedback-op",
        ]
    )
    assert args.handler(args) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    feedback = service.repository.list("FEEDBACK", "project-test")[0]
    assert feedback["origin"]["body"] == "Observed\x1b[31m issue"
    assert feedback["origin"]["observer"] == "OPERATOR"
    with pytest.raises(SystemExit):
        _parser().parse_args(
            ["playtest", "feedback", "project-test", "build-test", "--human", "--body", "x"]
        )


def test_human_feedback_requires_foreground_terminal_and_no_product_acceptance(
    tmp_path, monkeypatch
):
    root = tmp_path / "project"
    root.mkdir()
    service = _available(root)

    @contextmanager
    def unavailable():
        raise AuthorityError("Synthetic fixture: no foreground terminal.")
        yield

    monkeypatch.setattr(playtest, "_terminal", unavailable)
    with pytest.raises(AuthorityError):
        service.feedback_from_terminal("project-test", "build-test")
    assert service.repository.list("FEEDBACK", "project-test") == []

    writer = StringIO()

    @contextmanager
    def synthetic_terminal():
        yield StringIO("Synthetic terminal observation.\n"), writer

    monkeypatch.setattr(playtest, "_terminal", synthetic_terminal)
    result = service.feedback_from_terminal("project-test", "build-test")
    assert result["origin"]["observer"] == "HUMAN"
    assert "not product acceptance" in writer.getvalue()
    assert service.repository.list("REVIEW", "project-test") == []
    assert service.store.list_events() == []


def test_end_parser_requires_inspection_and_retention_requires_exact_preview():
    for command in (
        ["playtest", "end", "session-test"],
        ["playtest", "retention-apply", "project-test"],
    ):
        with pytest.raises(SystemExit):
            _parser().parse_args(command)
