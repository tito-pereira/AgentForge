# SPDX-License-Identifier: MPL-2.0
"""Verify frozen v1 and the shared Phase 2 CLI and RPC operations."""

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from corinthos.application import sidecar, workspace
from corinthos.bootstrap import initialize
from corinthos.cli import main
from corinthos.contracts import ContractStore

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS = _ROOT / "schemas/rpc"


def _call(method, request_id, **params):
    msg = {"jsonrpc": "2.0", "method": method, "params": params}
    if request_id is not None:
        msg["id"] = request_id
    return msg


def _transcript(requests):
    source = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in requests))
    output, diagnostics = io.BytesIO(), io.StringIO()
    sidecar.serve(source, output, diagnostics)
    assert diagnostics.getvalue() == ""
    assert all(len(line) <= sidecar.MAX_FRAME_BYTES for line in output.getvalue().splitlines())
    return [json.loads(line) for line in output.getvalue().splitlines()]


@pytest.fixture
def wire():
    schemas = {
        (file.parent.name, file.name.removesuffix(".schema.json")): json.loads(
            file.read_text("utf-8")
        )
        for file in _SCHEMAS.glob("v*/*.schema.json")
    }
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )

    def validate(name, data):
        Draft202012Validator(schemas["v2", name], registry=registry).validate(data)

    return validate


@pytest.fixture
def initialized_root(tmp_path, monkeypatch):
    monkeypatch.setattr("corinthos.user_state.state_root", lambda: tmp_path / "user")
    root = tmp_path / "project"
    initialize(root)
    return str(root)


def test_phase_one_rpc_schema_freeze():
    record = (_ROOT / "docs/v0.1/rpc-v1.sha256").read_text("ascii").splitlines()
    expected = {name: digest for digest, name in (line.split() for line in record)}
    assert len(expected) == len(record) == 9
    # Git records LF bytes. A Windows checkout may materialize CRLF.
    actual = {
        file.name: hashlib.sha256(file.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for file in (_SCHEMAS / "v1").iterdir()
        if file.is_file()
    }
    assert actual == expected


def test_connection_version_cannot_change_or_grant_v2_by_notification(initialized_root):
    root = initialized_root
    output = _transcript(
        [
            _call("system.handshake", None, protocol_version=2),
            _call("projects.list", 1),
            _call("system.handshake", 2, protocol_version=1),
            _call("project.summary", 3, root=root),
            _call("system.handshake", 4, protocol_version=2),
            _call("system.version", 5),
        ]
    )
    assert output[0]["params"] == {"protocol_version": 1}
    assert output[1]["error"]["code"] == -32001
    assert output[2]["result"]["methods"] == [
        "system.handshake",
        "system.version",
        "project.status",
        "providers.status",
        "system.shutdown",
    ]
    assert output[3]["error"]["code"] == -32601
    assert output[4]["error"]["code"] == -32001
    assert output[5]["result"]["version"]


def test_v2_create_and_read_use_real_backend_and_schemas(initialized_root, wire):
    root = initialized_root
    assert workspace.projects_list()["projects"] == []
    requests = [
        _call("system.handshake", 1, protocol_version=2),
        _call("project.open", 2, root=root),
        _call("projects.list", 3, limit=10, offset=0),
        _call(
            "work.create",
            4,
            root=root,
            scope_level="CHANGE",
            objective="Durable goal",
            acceptance_criteria=["Verifiable criterion"],
            affected_modules=["unresolved-module"],
        ),
        _call("work.list", 5, root=root, scope_level="CHANGE"),
        _call("work.tree", 6, root=root),
        _call("project.summary", 7, root=root),
        _call("system.shutdown", 8),
    ]
    result_schemas = (
        "handshake-result",
        "project-summary-result",
        "projects-list-result",
        "work-item-result",
        "work-list-result",
        "work-tree-result",
        "project-summary-result",
        "shutdown-result",
    )
    messages = _transcript(requests)
    wire("notification", messages[0])
    wire("notification", messages[-1])
    for request, response, schema in zip(requests, messages[1:-1], result_schemas, strict=True):
        wire("request", request)
        wire("response", response)
        assert response["id"] == request["id"]
        wire(schema, response["result"])
    handshake = messages[1]["result"]
    assert {"projects.list", "project.summary", "work.create"} <= set(handshake["methods"])
    wire("handshake-result", {**handshake, "methods": handshake["methods"] + ["future.optional"]})
    assert messages[2]["result"]["initialized"]
    assert messages[3]["result"]["projects"][0]["root"] == root
    item = messages[4]["result"]
    assert item["affected_modules"][0]["module_ref"] is None
    assert messages[5]["result"]["items"] == [item]
    assert messages[6]["result"]["nodes"][0]["work_item_id"] == item["work_item_id"]
    summary = messages[7]["result"]
    assert summary["schema_version"] == 9
    assert summary["active_project"] is None
    assert summary["work_items"]["total"] == 1


def test_large_unicode_pages_continue_without_losing_items(monkeypatch):
    @dataclass
    class RegistryRow:
        root: str

    records = [RegistryRow(str(index) + "é😀" * 2000) for index in range(15)]

    class Registry:
        def list(self, *, limit, offset):
            return records[offset : offset + limit]

    monkeypatch.setattr("corinthos.project_registry.ProjectRegistryService", Registry)
    seen = []
    offset = 0
    while offset is not None:
        _, _, response = _transcript(
            [
                _call("system.handshake", "h", protocol_version=2),
                _call("projects.list", "😀" * 128, limit=10, offset=offset),
            ]
        )
        result = response["result"]
        seen.extend(item["root"] for item in result["projects"])
        offset = result["next_offset"]
        assert offset is None or offset == len(seen)
    assert seen == [row.root for row in records]


def test_v2_status_update_dependency_reads_and_failures(initialized_root, wire):
    root = initialized_root
    fields = {
        "root": root,
        "scope_level": "TASK",
        "objective": "Goal",
        "acceptance_criteria": ["Proof"],
    }
    one = workspace.work_create(**fields)
    two = workspace.work_create(**fields, depends_on=[one["work_item_id"]])
    key = {"root": root, "work_item_id": two["work_item_id"]}
    mutation = _call("work.create", None, **fields)
    with pytest.raises(ValidationError):
        wire("request", mutation)
    requests = [
        _call("system.handshake", "h", protocol_version=2),
        mutation,
        _call("work.get", "get", **key),
        _call("work.dependencies", "deps", **key),
        _call("work.status", "move", **key, status="ACTIVE", expected_updated_at=two["updated_at"]),
        _call("work.update", "update", **key, objective="New objective"),
        _call(
            "work.status", "stale", **key, status="BLOCKED", expected_updated_at=two["updated_at"]
        ),
        _call("work.list", "bad", root=root, limit=True),
        _call("project.open", "missing", root=root + "-missing"),
        _call("work.status", "bad-status", **key, status={"secret": "not echoed"}),
    ]
    messages = _transcript(requests)
    get, deps, status, updated, stale, bad, missing, bad_status = messages[2:]
    for response in messages[1:]:
        wire("response", response)
    for response in (get, status, updated):
        wire("work-item-result", response["result"])
    wire("work-dependencies-result", deps["result"])
    assert deps["result"]["dependency_ids"] == [one["work_item_id"]]
    assert status["result"]["status"] == "ACTIVE"
    assert updated["result"]["objective"] == "New objective"
    assert stale["error"]["code"] in {-32002, -32602}
    assert [bad["error"]["code"], missing["error"]["code"], bad_status["error"]["code"]] == [
        -32602,
        -32002,
        -32602,
    ]
    assert "not echoed" not in json.dumps(messages)
    assert workspace.work_list(root)["items"][0]
    assert len(workspace.work_list(root)["items"]) == 2


def test_cli_operations_match_application_without_passive_writes(initialized_root, capsys):
    root = initialized_root

    def cli(*args):
        assert main(list(args)) == 0
        return json.loads(capsys.readouterr().out)

    assert cli("projects", "list") == workspace.projects_list()
    assert cli("project", "summary", root) == workspace.project_summary(root)
    assert not (Path(root) / ".corinthos/state.db").exists()
    assert cli("project", "--root", root, "open") == workspace.project_summary(root)
    item = cli(
        "work",
        "create",
        "--root",
        root,
        "--scope",
        "CRITICAL",
        "--objective",
        "Operational record",
        "--criterion",
        "Keep this exact",
    )
    key = item["work_item_id"]
    assert cli("work", "show", key, "--root", root) == item
    assert cli("work", "list", "--root", root, "--scope", "CRITICAL")["items"] == [item]
    assert cli("work", "status", key, "ACTIVE", "--root", root)["status"] == "ACTIVE"
    assert cli("work", "tree", "--root", root)["nodes"][0]["work_item_id"] == key
    assert cli("work", "dependencies", key, "--root", root)["dependency_ids"] == []
    assert cli("work", "update", key, "--root", root, "--clear-modules")["affected_modules"] == []
    assert ContractStore(root).list_events() == []
