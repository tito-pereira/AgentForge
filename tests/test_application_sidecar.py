# SPDX-License-Identifier: MPL-2.0
"""Exercise the exact wire schemas and real sidecar stdio."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from corinthos.application import sidecar

_SCHEMAS = Path(__file__).resolve().parents[1] / "schemas" / "rpc" / "v1"


def _request(method, request_id=1, **params):
    message = {"jsonrpc": "2.0", "method": method, "params": params}
    if request_id is not None:
        message["id"] = request_id
    return message


def _frame(message):
    return json.dumps(message).encode("utf-8") + b"\n"


def _frames(*messages):
    return b"".join(map(_frame, messages))


def _handshake():
    return _request("system.handshake", "initial", protocol_version=1)


def _transcript(data):
    output, diagnostics = io.BytesIO(), io.StringIO()
    sidecar.serve(io.BytesIO(data), output, diagnostics)
    return [json.loads(line) for line in output.getvalue().splitlines()], diagnostics.getvalue()


@pytest.fixture
def validate_wire():
    schemas = {
        file.name.removesuffix(".schema.json"): json.loads(file.read_text("utf-8"))
        for file in _SCHEMAS.glob("*.schema.json")
    }
    assert set(schemas) == {
        "request",
        "response",
        "error",
        "notification",
        "handshake-result",
        "version-result",
        "project-status-result",
        "provider-status-result",
        "shutdown-result",
    }
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )

    def validate(name, message):
        Draft202012Validator(schemas[name], registry=registry).validate(message)

    return validate


def test_long_lived_sidecar_preserves_wire_ids_events_and_read_only_state(
    tmp_path, monkeypatch, validate_wire
):
    user = tmp_path / "global-state"
    monkeypatch.setattr("corinthos.user_state.state_root", lambda: user)
    requests = [
        _handshake(),
        _request("system.version", 27),
        _request("project.status", "line\nbreak", root=str(tmp_path)),
        _request("providers.status", -3, root=str(tmp_path)),
        _request("system.version", None),
        _request("system.shutdown", 44),
    ]
    for request in requests:
        validate_wire("request", request)

    output, diagnostics = _transcript(_frames(*requests))
    assert diagnostics == ""
    assert output[0]["method"] == "system.ready"
    assert output[-1]["method"] == "system.stopping"
    validate_wire("notification", output[0])
    validate_wire("notification", output[-1])
    responses = output[1:-1]
    assert [response["id"] for response in responses] == ["initial", 27, "line\nbreak", -3, 44]
    for response, schema in zip(
        responses,
        ["handshake", "version", "project-status", "provider-status", "shutdown"],
        strict=True,
    ):
        validate_wire("response", response)
        validate_wire(f"{schema}-result", response["result"])
    assert responses[2]["result"]["exists"] and not responses[2]["result"]["initialized"]
    assert all(
        provider["observation"] == "NOT_OBSERVED"
        for provider in responses[3]["result"]["providers"]
    )
    assert list(tmp_path.iterdir()) == []


def test_sidecar_recovers_from_invalid_messages_and_incompatible_handshake(validate_wire):
    first = _frames(
        _request("system.version", 1),
        _request("system.handshake", 2, protocol_version=99),
    )
    invalid = (
        b'{"jsonrpc":"2.0","method":"system.version","id":NaN}\n'
        b'{"jsonrpc":"2.0","method":"system.version","id":1,"id":2}\n'
        b"\xff\n"
        b"[]\n"
        + _frame(_request("system.version", True))
        + _frame(_request("system.version", 2**53))
    )
    last = _frames(
        _handshake(),
        _request("project.status", "bad-root", root="\x00"),
        _request("project.status", "missing-root"),
        _request("does.not.exist", "unknown"),
        _request("does.not.exist", None),
        _request("system.shutdown", None),
        _request("system.version", "usable"),
    )
    output, diagnostics = _transcript(first + invalid + last)
    assert diagnostics == ""
    for response in output[1:]:
        validate_wire("response", response)
        if "error" in response:
            validate_wire("error", response["error"])
    assert [(m["id"], m["error"]["code"]) for m in output[1:] if "error" in m] == [
        (1, -32001),
        (2, -32001),
        (None, -32700),
        (None, -32700),
        (None, -32700),
        (None, -32600),
        (None, -32600),
        (None, -32600),
        ("bad-root", -32602),
        ("missing-root", -32602),
        ("unknown", -32601),
    ]
    assert output[-1]["id"] == "usable"


def test_frames_are_bounded_and_recover_at_line_boundaries():
    frame = _frame(_request("system.version", "exact"))
    exact_limit = frame[:-1].ljust(sidecar.MAX_FRAME_BYTES, b" ") + b"\n"
    oversized = b"x" * (sidecar.MAX_FRAME_BYTES * 2) + b"\n"
    output, diagnostics = _transcript(
        _frame(_handshake()) + exact_limit + oversized + frame + b"incomplete"
    )
    assert diagnostics == ""
    assert [message.get("id") for message in output] == [
        None,
        "initial",
        "exact",
        None,
        "exact",
        None,
    ]
    assert output[3]["error"]["code"] == output[5]["error"]["code"] == -32600


def test_result_size_bound_keeps_id_and_omits_private_content(monkeypatch):
    def oversized(_root):
        from corinthos.application import ProviderStatus

        return [ProviderStatus("fixture", False, "global", "私" * 4096, "NOT_OBSERVED", None)] * 32

    monkeypatch.setattr(sidecar, "providers_status", oversized)
    output, diagnostics = _transcript(_frames(_handshake(), _request("providers.status", 27)))
    assert diagnostics == ""
    assert output[-1] == {
        "jsonrpc": "2.0",
        "id": 27,
        "error": {"code": -32002, "message": "Requested state unavailable"},
    }


def test_sidecar_hides_invalid_registry_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr("corinthos.user_state.state_root", lambda: tmp_path)
    private = b'{"private":"do not disclose"}'
    registry = tmp_path / "providers.json"
    registry.write_bytes(private)
    output, diagnostics = _transcript(_frames(_handshake(), _request("providers.status", 3)))
    assert diagnostics == ""
    assert output[-1]["error"]["code"] == -32002
    assert "do not disclose" not in json.dumps(output)
    assert registry.read_bytes() == private


@pytest.mark.parametrize("shutdown", [False, True])
def test_real_process_stdout_is_protocol_only_and_shutdown_or_eof_exits(tmp_path, shutdown):
    appdata = tmp_path / "private-user"
    project = tmp_path / "missing"
    requests = [
        _handshake(),
        _request("project.status", 2, root=str(project)),
        _request("providers.status", 3),
    ]
    if shutdown:
        requests.append(_request("system.shutdown", 4))
    env = os.environ | {"LOCALAPPDATA": str(appdata), "XDG_STATE_HOME": str(appdata)}
    process = subprocess.run(
        [sys.executable, "-B", "-m", "corinthos.application.sidecar"],
        input=_frames(*requests),
        capture_output=True,
        env=env,
        timeout=15,
        check=True,
    )
    output = [json.loads(line) for line in process.stdout.splitlines()]
    assert not process.stderr
    assert output[0]["method"] == "system.ready"
    assert output[2]["result"]["exists"] is False
    assert output[3]["result"]["providers"]
    assert len(output) == (6 if shutdown else 4)
    assert (output[-1].get("method") == "system.stopping") is shutdown
    assert list(tmp_path.iterdir()) == []
