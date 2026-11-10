# SPDX-License-Identifier: MPL-2.0
"""Bounded subprocess transport with observable, non-authoritative JSON events."""

import json
import os
import queue
import subprocess
import threading
from time import monotonic

from .model import AgentResult
from .process_control import start_process

_MAX_LINE = 1_048_576
_MAX_OUTPUT = 8_388_608
_MAX_EVENTS = 10_000


def run_process(
    provider,
    prefix,
    prompt,
    workspace,
    *,
    capabilities,
    task_id,
    attempt_id,
    timeout,
    cancel,
    on_event,
    resume=None,
    read_only=False,
):
    started = monotonic()
    state = {
        "session_id": None,
        "completed": False,
        "failed": False,
        "output": [],
        "usage": None,
        "cost_usd": None,
        "telemetry_scope": None,
        "error_code": None,
    }
    events, status, error_kind = [], None, None
    command = provider.command(prefix, resume=resume, read_only=read_only)
    try:
        managed = start_process(
            command,
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            shell=False,
        )
        process = managed.process
    except OSError as error:
        return AgentResult(
            provider.name,
            "UNAVAILABLE",
            task_id,
            attempt_id,
            version=capabilities.version,
            error_kind="PROCESS_START_FAILED",
            cleanup_confirmed=getattr(error, "cleanup_confirmed", True),
        )
    messages = queue.Queue(maxsize=64)
    stopping = threading.Event()

    def enqueue(message):
        while not stopping.is_set():
            try:
                messages.put(message, timeout=0.05)
                return
            except queue.Full:
                continue

    def read(stream, name):
        try:
            while line := stream.readline(_MAX_LINE + 1):
                enqueue((name, line))
            enqueue((name, None))
        except (OSError, ValueError):
            enqueue((name, None))

    def write():
        try:
            process.stdin.write(prompt.encode("utf-8"))
            process.stdin.close()
        except (OSError, ValueError):
            pass

    readers = [
        threading.Thread(target=read, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=read, args=(process.stderr, "stderr"), daemon=True),
    ]
    writer = threading.Thread(target=write, daemon=True)
    for thread in (*readers, writer):
        thread.start()
    streams, total = 0, 0
    cleanup = True
    try:
        while streams < 2 or process.poll() is None:
            if cancel is not None and cancel.is_set():
                status, error_kind = "CANCELLED", "CANCEL_REQUESTED"
                break
            if monotonic() - started >= timeout:
                status, error_kind = "TIMEOUT", "TIME_LIMIT"
                break
            try:
                source, line = messages.get(timeout=0.05)
            except queue.Empty:
                continue
            if line is None:
                streams += 1
                continue
            total += len(line)
            if total > _MAX_OUTPUT or len(line) > _MAX_LINE or len(events) >= _MAX_EVENTS:
                status, error_kind = "PROTOCOL_ERROR", "OUTPUT_LIMIT"
                break
            if source == "stderr":
                continue
            try:
                native = json.loads(line.decode("utf-8"))
                if not isinstance(native, dict) or not isinstance(native.get("type"), str):
                    raise ValueError
                provider.parse(native, state)
                if state["error_code"] is not None and not isinstance(state["error_code"], str):
                    raise ValueError
                event = {"sequence": len(events) + 1, "provider_type": native["type"]}
                if native["type"] in {"turn.completed", "result"}:
                    event["kind"] = "completed" if state["completed"] else "failed"
                else:
                    event["kind"] = "progress"
                events.append(event)
                if on_event is not None:
                    try:
                        on_event(dict(event))
                    except Exception:
                        status, error_kind = "FAILED", "EVENT_CALLBACK_FAILED"
                        break
            except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
                status, error_kind = "PROTOCOL_ERROR", "MALFORMED_EVENT"
                break
    finally:
        cleanup = managed.finish()
        stopping.set()
        for stream in (process.stdin, process.stdout, process.stderr):
            if not cleanup:
                continue
            try:
                stream.close()
            except OSError:
                pass
        for thread in (*readers, writer):
            thread.join(timeout=0.2)
    if status is None:
        if process.returncode != 0 or state["failed"]:
            status, error_kind = "FAILED", "PROCESS_OR_PROVIDER_FAILURE"
        elif not state["completed"]:
            status, error_kind = "PROTOCOL_ERROR", "MISSING_COMPLETION"
        else:
            status = "COMPLETED"
    if state["error_code"] in {
        "invalid_api_key",
        "authentication_error",
        "unauthorized",
        "not_authenticated",
        "auth_required",
    }:
        error_kind = "AUTHENTICATION_REQUIRED"
    elif state["error_code"] in {
        "insufficient_quota",
        "rate_limit_exceeded",
        "rate_limit_error",
        "usage_limit_exceeded",
        "quota_exhausted",
    }:
        error_kind = "QUOTA_OR_RATE_LIMIT"
    return AgentResult(
        provider.name,
        status,
        task_id,
        attempt_id,
        version=capabilities.version,
        exit_code=process.returncode,
        session_id=state["session_id"],
        events=tuple(events),
        output="\n".join(state["output"]),
        usage=state["usage"],
        cost_usd=state["cost_usd"],
        telemetry_scope=state["telemetry_scope"],
        error_kind=error_kind,
        duration_seconds=monotonic() - started,
        cleanup_confirmed=cleanup,
    )
