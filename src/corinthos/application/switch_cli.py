# SPDX-License-Identifier: MPL-2.0
"""Explicit provider continuation through the shared session application."""

import json
import sys
from pathlib import Path

from corinthos.application.sessions import SessionApplication, session_view
from corinthos.contracts import ContractError
from corinthos.providers import SUPPORTED_PROVIDERS


def configure(commands):
    command = commands.add_parser("switch", help="Continue a Work Item with another provider.")
    actions = command.add_subparsers(dest="switch_action", required=True)
    for action in ("start", "status"):
        parser = actions.add_parser(action)
        parser.add_argument("--root", default=str(Path.cwd()))
        parser.add_argument("--session", dest="source_session_id", required=True)
        parser.add_argument(
            "--provider", dest="target_provider", choices=SUPPORTED_PROVIDERS, required=True
        )
        parser.add_argument("--generation", dest="source_generation", type=int)
        parser.set_defaults(handler=_run)


def _run(arguments):
    app = SessionApplication()
    operation = app.switch_execute if arguments.switch_action == "start" else app.switch_status
    try:
        result = operation(
            arguments.root,
            arguments.source_session_id,
            arguments.target_provider,
            arguments.source_generation,
        )
        print(json.dumps(result), flush=True)
        if arguments.switch_action == "start" and result["stage"] == "TARGET_SESSION_ACTIVE":
            session = app.supervisor.wait(arguments.root, result["target_session_id"])
            print(json.dumps(session_view(session)), flush=True)
        return int(result["stage"] == "BLOCKED")
    except KeyboardInterrupt:
        return 130
    except (ContractError, OSError, RuntimeError, ValueError):
        print("The requested provider switch operation is unavailable.", file=sys.stderr)
        return 1
    finally:
        app.supervisor.close()
