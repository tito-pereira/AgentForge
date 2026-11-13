# SPDX-License-Identifier: MPL-2.0
"""Separate native commands and event normalization for Codex and Claude Code."""

import re
from decimal import Decimal
from math import isfinite
from uuid import UUID


def session_id(value):
    if not isinstance(value, str):
        raise ValueError
    return str(UUID(value))


def usage(value):
    if not isinstance(value, dict):
        return None
    observed = {
        key: item
        for key, item in value.items()
        if key
        in {
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        }
        and type(item) is int
        and item >= 0
    }
    return observed or None


_MAX_INT = 2**53 - 1
_NATIVE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+ -]{0,127}\Z")


def _label(value):
    return value if isinstance(value, str) and _NATIVE_LABEL.fullmatch(value) else None


def _reported_cost(value):
    if type(value) is int:
        value = Decimal(value)
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        return None
    if value == 0:
        return "0"
    digits = value.as_tuple()
    if len(digits.digits) > 32 or not -24 <= digits.exponent <= 20 or value.adjusted() > 20:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _usage(values, cached_key):
    if not isinstance(values, dict):
        return None
    normalized = {
        key: candidate
        for key, candidate in (
            ("input_tokens", values.get("input_tokens")),
            ("output_tokens", values.get("output_tokens")),
            ("cached_tokens", values.get(cached_key)),
        )
        if type(candidate) is int and 0 <= candidate <= _MAX_INT
    }
    return normalized or None


def _event(kind, native, payload):
    return {"kind": kind, "provider_type": _label(native), "payload": payload}


def _text(value):
    return "".join(c if c.isprintable() or c in "\t\n" else "\ufffd" for c in value[:768])


def _observations(event, state, *, cached_key, exact_cost=False):
    values = _usage(event.get("usage"), cached_key)
    if values:
        snapshot = dict(state["normalized_usage"] or {})
        snapshot.update(values)
        state["normalized_usage"] = snapshot
    cost = _reported_cost(event.get("total_cost_usd")) if exact_cost else None
    if cost is not None:
        state["reported_cost"] = cost
        state["reported_cost_currency"] = "USD"
    payload = {**(values or {})}
    if cost is not None:
        payload.update(reported_cost=cost, reported_cost_currency="USD")
    return _event("USAGE", event["type"], payload) if payload else None


def _output(event, text):
    return _event("OUTPUT", event["type"], {"text": _text(text)})


class CodexAdapter:
    name = "codex"
    projection_heading = "## Frozen Corinthos context (JSON)"

    @staticmethod
    def capabilities(probe, general):
        help_text = probe(("exec", "--help")) or ""
        resume_help = probe(("exec", "resume", "--help")) or ""
        return (
            "--json" in help_text,
            "stdin" in help_text,
            all(term in resume_help for term in ("--json", "SESSION_ID", "stdin")),
            "--sandbox" in general and "read-only" in general,
        )

    @staticmethod
    def instruction_path(workspace):
        override = workspace / "AGENTS.override.md"
        return override if override.exists() or override.is_symlink() else workspace / "AGENTS.md"

    @staticmethod
    def session_events(event, state):
        kind = event["type"]
        model = _label(event.get("model"))
        if model and kind in {"thread.started", "turn.started", "turn.completed"}:
            state["model"] = model
        if kind == "thread.started":
            return [_event("OUTPUT", kind, {"message": "Native session opened."})]
        if kind == "turn.completed":
            observed = _observations(event, state, cached_key="cached_input_tokens")
            return [observed] if observed else []
        if kind in {"turn.failed", "error"}:
            return [_event("ERROR", kind, {"message": "The provider reported an error."})]
        if kind in {"item.started", "item.completed"}:
            item = event.get("item")
            if isinstance(item, dict):
                name = item.get("type")
                if kind == "item.completed" and name == "agent_message":
                    return [_output(event, item["text"])]
                if name in {"command_execution", "file_change", "mcp_tool_call", "web_search"}:
                    return [_event("TOOL_ACTIVITY", kind, {"tool": name})]
        return []

    @staticmethod
    def command(prefix, *, resume=None, read_only=False):
        arguments = [*prefix]
        if read_only:
            arguments.extend(("--sandbox", "read-only"))
        arguments.append("exec")
        if resume is not None:
            arguments.extend(("resume", session_id(resume)))
        arguments.extend(("--json", "-"))
        return arguments

    @staticmethod
    def parse(event, state):
        kind = event["type"]
        if kind == "thread.started":
            state["session_id"] = session_id(event["thread_id"])
        elif kind == "turn.completed":
            state["completed"] = True
            state["usage"] = usage(event.get("usage"))
            state["telemetry_scope"] = "turn"
        elif kind in {"turn.failed", "error"}:
            state["failed"] = True
            error = event.get("error", event)
            state["error_code"] = error.get("code") if isinstance(error, dict) else None
        elif kind == "item.completed":
            item = event["item"]
            if item["type"] == "agent_message":
                if not isinstance(item["text"], str):
                    raise ValueError
                state["output"].append(item["text"])


class ClaudeAdapter:
    name = "claude"
    projection_heading = "Corinthos context projection follows as JSON."

    @staticmethod
    def capabilities(probe, general):
        return (
            all(term in general for term in ("--output-format", "stream-json", "--verbose")),
            "--print" in general or "-p" in general,
            "--resume" in general,
            "--tools" in general and "--disallowedTools" in general,
        )

    @staticmethod
    def instruction_path(workspace):
        return workspace / "CLAUDE.md"

    @staticmethod
    def session_events(event, state):
        kind = event["type"]
        if kind == "system" and event.get("subtype") == "init":
            state["model"] = _label(event.get("model"))
            return [_event("OUTPUT", kind, {"message": "Native session opened."})]
        if kind == "error":
            return [_event("ERROR", kind, {"message": "The provider reported an error."})]
        if kind == "result":
            result = (
                [_output(event, event["result"])] if isinstance(event.get("result"), str) else []
            )
            observed = _observations(
                event, state, cached_key="cache_read_input_tokens", exact_cost=True
            )
            if observed:
                result.append(observed)
            if state["failed"]:
                result.append(_event("ERROR", kind, {"message": "The provider reported an error."}))
            return result
        if kind == "assistant":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "tool_use" for block in content
            ):
                return [_event("TOOL_ACTIVITY", kind, {"tool": "tool_use"})]
        return []

    @staticmethod
    def command(prefix, *, resume=None, read_only=False):
        arguments = [*prefix, "--print", "--output-format", "stream-json", "--verbose"]
        if resume is not None:
            arguments.extend(("--resume", session_id(resume)))
        if read_only:
            arguments.extend(("--tools", "", "--disallowedTools", "mcp__*"))
        return arguments

    @staticmethod
    def parse(event, state):
        kind = event["type"]
        if kind == "system" and event.get("subtype") == "init":
            state["session_id"] = session_id(event["session_id"])
        elif kind == "error":
            state["failed"] = True
            error = event.get("error", event)
            state["error_code"] = error.get("code") if isinstance(error, dict) else None
        elif kind == "result":
            if "session_id" in event:
                state["session_id"] = session_id(event["session_id"])
            state["completed"] = (
                event.get("subtype") == "success" and event.get("is_error") is False
            )
            state["failed"] = state["failed"] or not state["completed"]
            state["error_code"] = (
                event.get("error", {}).get("code")
                if isinstance(event.get("error"), dict)
                else event.get("subtype")
            )
            if isinstance(event.get("result"), str):
                state["output"].append(event["result"])
            state["usage"] = usage(event.get("usage"))
            cost = event.get("total_cost_usd")
            if type(cost) in (int, float) and isfinite(cost) and cost >= 0:
                state["cost_usd"] = cost
            state["telemetry_scope"] = "provider_reported_conversation_cost_estimate"


PROVIDERS = {provider.name: provider for provider in (CodexAdapter, ClaudeAdapter)}
