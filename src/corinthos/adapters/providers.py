# SPDX-License-Identifier: MPL-2.0
"""Separate native commands and event normalization for Codex and Claude Code."""

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


class CodexAdapter:
    name = "codex"

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
