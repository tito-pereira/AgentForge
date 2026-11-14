# SPDX-License-Identifier: MPL-2.0
"""Verify the additive context audit wire and CLI against local state."""

import json

import pytest
from test_application_workspace import _call, _transcript
from test_application_workspace import wire as wire

from corinthos.application import context, workspace
from corinthos.bootstrap import initialize
from corinthos.cli import main
from corinthos.contracts import ContractError
from corinthos.sessions.repository import SessionRepository
from corinthos.work import WorkService


@pytest.fixture
def records(tmp_path, monkeypatch):
    monkeypatch.setattr("corinthos.user_state.state_root", lambda: tmp_path / "user")
    root = tmp_path / "workspace"
    initialize(root)
    work = WorkService(root).create(
        scope_level="TASK",
        objective="Verify an ordinary application workflow.",
        acceptance_criteria=["api_key=synthetic-only-low-entropy-fixture"],
    )
    repository = SessionRepository(root)
    session = repository.create(
        work.work_item_id,
        provider="codex",
        owner_id="test-owner",
        timeout_seconds=30,
        envelope_sha256="a" * 64,
    )
    fence = session.session_id, "test-owner", 1
    repository.running(*fence)
    repository.observe(*fence, "OUTPUT", {"text": "token=synthetic-only-session-fixture"})
    repository.finish(*fence, "SUCCEEDED")
    return str(root), work, session


def test_v2_context_and_handoff_are_additive_and_exclude_captures(records, wire):
    root, work, legacy = records
    source = {"root": root, "work_item_id": work.work_item_id, "provider": "codex"}
    binding = {"root": root, "session_id": legacy.session_id}
    legacy_output = _transcript(
        [
            _call("system.handshake", 1, protocol_version=1),
            _call("context.create", 2, **source),
            _call("system.shutdown", 3),
        ]
    )
    assert legacy_output[2]["error"]["code"] == -32601
    assert not context.context_list(root)["projections"]

    requests = [
        _call("system.handshake", 1, protocol_version=2),
        _call("context.create", 2, **source),
        _call("project.summary", 3, root=root),
        _call("context.for_session", 4, **binding),
        _call("handoff.create", 5, **binding),
        _call("handoff.list", 6, root=root),
        _call("system.shutdown", 7),
    ]
    messages = _transcript(requests)
    schemas = [
        "handshake-result",
        "context-projection",
        "project-summary-result",
        "context-for-session-result",
        "handoff-result",
        "handoff-list-result",
        "shutdown-result",
    ]
    for request, response, schema in zip(requests, messages[1:-1], schemas, strict=True):
        wire("request", request)
        wire("response", response)
        wire(schema, response["result"])
    projection = messages[2]["result"]
    assert messages[4]["result"] == {"projection": None}
    handoff = messages[5]["result"]
    assert handoff["source_session_id"] == legacy.session_id
    assert handoff["event_cutoff"] > 0
    assert "synthetic-only" not in json.dumps(messages)
    assert "context" not in messages[3]["result"]
    assert [x["method"] for x in messages if "method" in x] == ["system.ready", "system.stopping"]
    assert {"context.create", "handoff.create"} <= set(messages[1]["result"]["methods"])

    ident = {"root": root, "projection_id": projection["projection_id"]}
    second = _transcript(
        [
            _call("system.handshake", 1, protocol_version=2),
            _call("context.sources", 2, **ident),
            _call("context.verify", 3, **ident),
            _call("context.get", 4, **ident),
            _call("handoff.get", 5, root=root, handoff_id=handoff["handoff_id"]),
        ]
    )
    wire("context-sources-result", second[2]["result"])
    wire("context-verification-result", second[3]["result"])
    wire("context-projection", second[4]["result"])
    wire("handoff-result", second[5]["result"])
    assert all("capture" not in entry for entry in second[2]["result"]["sources"])
    assert any(entry["redaction"] for entry in second[2]["result"]["sources"])
    assert second[3]["result"]["verified"]
    assert "synthetic-only" not in json.dumps(second)
    assert second[4]["result"] == projection


def test_context_commands_share_application(records, capsys):
    root, work, legacy = records

    def cli(*args):
        assert main(list(args)) == 0
        return json.loads(capsys.readouterr().out)

    projection = cli(
        "context", "create", "--root", root, "--work", work.work_item_id, "--provider", "claude"
    )
    assert cli("context", "show", projection["projection_id"], "--root", root) == projection
    assert cli("context", "verify", projection["projection_id"], "--root", root)["verified"]
    handoff = cli("handoff", "create", "--root", root, "--session", legacy.session_id)
    assert cli("handoff", "show", handoff["handoff_id"], "--root", root) == handoff
    assert cli("handoff", "list", "--root", root, "--work", work.work_item_id)["handoffs"]
    assert {"context", "sessions"}.isdisjoint(workspace.project_summary(root))

    with pytest.raises(ContractError):
        context.context_create(root, work.work_item_id, "unknown-provider")
