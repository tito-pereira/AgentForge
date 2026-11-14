# SPDX-License-Identifier: MPL-2.0
"""Scriptable scope policy and adaptive workflow operations."""

import json
import sys
from pathlib import Path

from corinthos.application import adaptive
from corinthos.application.cli import _workspace
from corinthos.application.sessions import SessionApplication
from corinthos.contracts import ContractError
from corinthos.providers import SUPPORTED_PROVIDERS
from corinthos.work import ScopeLevel


def configure(commands):
    scope = commands.add_parser("scope", help="Inspect or explicitly change Work Item scope.")
    flow = commands.add_parser("flow", help="Run or inspect the applicable Work Item flow.")
    for parent, operations in (
        (scope, {"assess": adaptive.scope_assess, "set": adaptive.scope_set}),
        (flow, {"status": adaptive.flow_status, "start": None, "complete": adaptive.flow_complete}),
    ):
        actions = parent.add_subparsers(dest=f"{parent.prog.split()[-1]}_action", required=True)
        for name, operation in operations.items():
            parser = actions.add_parser(name)
            parser.add_argument("--root", default=str(Path.cwd()))
            parser.add_argument("--work", dest="work_item_id", required=True)
            fields = ["root", "work_item_id"]
            if name in {"set", "complete"}:
                parser.add_argument("--expected-updated-at", required=True)
                fields.append("expected_updated_at")
            if name == "set":
                parser.add_argument(
                    "--scope", dest="scope_level", choices=tuple(ScopeLevel), required=True
                )
                parser.add_argument("--confirm-downgrade", action="store_true")
                fields.extend(("scope_level", "confirm_downgrade"))
            if name == "start":
                parser.add_argument("--provider", choices=SUPPORTED_PROVIDERS, required=True)
                parser.add_argument("--instruction", default="")
                parser.add_argument("--timeout", dest="timeout_seconds", type=int, default=120)
                parser.add_argument("--read-only", action="store_true")
                parser.set_defaults(handler=_start)
            else:
                parser.set_defaults(handler=_workspace, operation=operation, arguments=fields)


def _start(arguments):
    app = SessionApplication()
    try:
        result = app.flow_start(
            arguments.root,
            arguments.work_item_id,
            arguments.provider,
            instruction=arguments.instruction,
            timeout_seconds=arguments.timeout_seconds,
            read_only=arguments.read_only,
        )
        print(json.dumps(result), flush=True)
        app.supervisor.wait(arguments.root, result["latest_session"]["session_id"])
        print(json.dumps(adaptive.flow_status(arguments.root, arguments.work_item_id)), flush=True)
        return 0
    except KeyboardInterrupt:
        return 130
    except (ContractError, OSError, RuntimeError):
        print("The requested adaptive start is unavailable.", file=sys.stderr)
        return 1
    finally:
        app.supervisor.close()
