# SPDX-License-Identifier: MPL-2.0
"""Scriptable context and handoff operations over the shared application layer."""

from pathlib import Path

from corinthos.application import context
from corinthos.application.cli import _pagination, _workspace


def configure(commands):
    for name, operations in (
        (
            "context",
            {
                "create": context.context_create,
                "show": context.context_get,
                "list": context.context_list,
                "sources": context.context_sources,
                "verify": context.context_verify,
                "for-session": context.context_for_session,
            },
        ),
        (
            "handoff",
            {
                "create": context.handoff_create,
                "show": context.handoff_get,
                "list": context.handoff_list,
            },
        ),
    ):
        group = commands.add_parser(name, help=f"Audit local {name} records.")
        actions = group.add_subparsers(dest=f"{name}_action", required=True)
        for action, operation in operations.items():
            parser = actions.add_parser(action)
            parser.add_argument("--root", default=str(Path.cwd()))
            fields = ["root"]
            if action in {"list", "sources"}:
                _pagination(parser)
                fields.extend(("limit", "offset"))
            if action == "list" or (name == "context" and action == "create"):
                parser.add_argument("--work", dest="work_item_id", required=action == "create")
                fields.append("work_item_id")
            if name == "context" and action == "create":
                parser.add_argument("--provider", required=True)
                fields.append("provider")
            elif name == "context" and action in {"show", "verify", "sources"}:
                parser.add_argument("projection_id")
                fields.append("projection_id")
            elif action == "for-session":
                parser.add_argument("session_id")
                fields.append("session_id")
            elif name == "handoff" and action in {"create", "list"}:
                parser.add_argument("--session", dest="session_id", required=action == "create")
                fields.append("session_id")
            elif name == "handoff" and action == "show":
                parser.add_argument("handoff_id")
                fields.append("handoff_id")
            parser.set_defaults(handler=_workspace, operation=operation, arguments=tuple(fields))
