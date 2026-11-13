# SPDX-License-Identifier: MPL-2.0
"""Bounded JSON-RPC 2.0 over UTF-8 JSON Lines on standard streams."""

import json
import sys
from dataclasses import asdict
from typing import BinaryIO, TextIO

from corinthos.application import project_status, providers_status, version
from corinthos.contracts import ContractError

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 65_536
_MAX_ID = 2**53 - 1
_METHODS = (
    "system.handshake",
    "system.version",
    "project.status",
    "providers.status",
    "system.shutdown",
)
_ERROR_MESSAGES = {
    -32700: "Parse error",
    -32600: "Invalid Request",
    -32601: "Method not found",
    -32602: "Invalid params",
    -32603: "Internal error",
    -32001: "Compatible protocol handshake required",
    -32002: "Requested state unavailable",
}


class _RpcError(Exception):
    def __init__(self, code: int):
        self.code = code


def _json_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate keys.")
    return result


def _reject_constant(_value):
    raise ValueError("Non-JSON constant.")


def _request_id(value):
    return (type(value) is int and -_MAX_ID <= value <= _MAX_ID) or (
        isinstance(value, str)
        and len(value) <= 128
        and all(not "\ud800" <= char <= "\udfff" for char in value)
    )


def _parse(frame: bytes) -> dict:
    try:
        message = json.loads(
            frame.decode("utf-8"),
            object_pairs_hook=_json_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError):
        raise _RpcError(-32700) from None
    if (
        not isinstance(message, dict)
        or message.keys() - {"jsonrpc", "id", "method", "params"}
        or message.get("jsonrpc") != "2.0"
        or not isinstance(message.get("method"), str)
        or not 0 < len(message["method"]) <= 64
        or ("id" in message and not _request_id(message["id"]))
    ):
        raise _RpcError(-32600)
    return message


def _params(message: dict, *, required=(), optional=()) -> dict:
    params = message.get("params", {})
    if (
        not isinstance(params, dict)
        or not set(required) <= params.keys()
        or params.keys() - set(required) - set(optional)
    ):
        raise _RpcError(-32602)
    return params


def _dispatch(message: dict, negotiated: bool) -> tuple[dict, bool, bool]:
    method = message["method"]
    if method not in _METHODS:
        raise _RpcError(-32601)
    if method == "system.handshake":
        received = _params(message, required=("protocol_version",))["protocol_version"]
        if type(received) is not int:
            raise _RpcError(-32602)
        if received != PROTOCOL_VERSION:
            raise _RpcError(-32001)
        return (
            {
                "protocol_version": PROTOCOL_VERSION,
                "version": version().version,
                "methods": list(_METHODS),
            },
            "id" in message or negotiated,
            False,
        )
    if not negotiated:
        raise _RpcError(-32001)
    if method in {"project.status", "providers.status"}:
        params = (
            _params(message, required=("root",))
            if method == "project.status"
            else _params(message, optional=("root",))
        )
        root = params.get("root")
        if "root" in params and not isinstance(root, str):
            raise _RpcError(-32602)
        try:
            if method == "project.status":
                return asdict(project_status(root)), negotiated, False
            providers = [asdict(provider) for provider in providers_status(root)]
            return {"providers": providers}, negotiated, False
        except ContractError:
            raise _RpcError(-32002) from None
        except ValueError:
            raise _RpcError(-32602) from None
    _params(message)
    if method == "system.version":
        return asdict(version()), negotiated, False
    return {"stopping": True}, negotiated, "id" in message


def _error(code: int, request_id=None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": _ERROR_MESSAGES[code]},
    }


def _write(output: BinaryIO, message: dict) -> None:
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(data) > MAX_FRAME_BYTES:
        data = json.dumps(_error(-32002, message.get("id")), separators=(",", ":")).encode()
    output.write(data + b"\n")
    output.flush()


def _notify(output: BinaryIO, method: str, params: dict) -> None:
    _write(output, {"jsonrpc": "2.0", "method": method, "params": params})


def serve(source: BinaryIO, output: BinaryIO, diagnostics: TextIO) -> None:
    """Serve one local peer until EOF or an identified shutdown request."""
    _notify(output, "system.ready", {"protocol_version": PROTOCOL_VERSION})
    negotiated = False
    while frame := source.readline(MAX_FRAME_BYTES + 2):
        if len(frame) > MAX_FRAME_BYTES + 1 or not frame.endswith(b"\n"):
            _write(output, _error(-32600))
            # Discard the rest of an oversized frame without growing memory.
            # A peer that keeps streaming a single huge line loses the connection.
            for _ in range(16):
                if not frame or frame.endswith(b"\n"):
                    break
                frame = source.readline(MAX_FRAME_BYTES + 2)
            else:
                if frame and not frame.endswith(b"\n"):
                    return
            continue
        try:
            message = _parse(frame)
        except _RpcError as error:
            _write(output, _error(error.code))
            continue
        try:
            result, negotiated, stopping = _dispatch(message, negotiated)
            reply = {"jsonrpc": "2.0", "id": message.get("id"), "result": result}
        except _RpcError as error:
            reply = _error(error.code, message.get("id"))
            stopping = False
        except (ContractError, OSError, RuntimeError):
            reply = _error(-32002, message.get("id"))
            stopping = False
        except Exception:
            print("Unexpected application operation failure.", file=diagnostics)
            reply = _error(-32603, message.get("id"))
            stopping = False
        if "id" in message:
            _write(output, reply)
        if stopping:
            _notify(output, "system.stopping", {})
            return


def main() -> int:
    try:
        serve(sys.stdin.buffer, sys.stdout.buffer, sys.stderr)
    except BrokenPipeError:
        return 0
    except OSError:
        print("Sidecar transport failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
