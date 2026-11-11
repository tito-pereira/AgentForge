# SPDX-License-Identifier: MPL-2.0
"""Thin installed CLI for explicit playtests, feedback and owned retention."""

import argparse
import sys
from pathlib import Path

from corinthos.contracts import ConflictError, ContractError
from corinthos.project_manager.presentation import render_fields, safe_text

from .playtest import PlaytestService


def _inspect(parser):
    parser.add_argument(
        "--process-stopped",
        action="store_true",
        required=True,
        help="Confirm actual process inspection found the session stopped.",
    )
    parser.add_argument(
        "--effects-inspected",
        action="store_true",
        required=True,
        help="Confirm actual inspection of application/data effects.",
    )
    parser.add_argument("--summary", required=True, help="What was actually inspected.")


def add_cli(subparsers):
    parser = subparsers.add_parser("playtest", help="Manage explicit isolated playtest sessions.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="playtest_action", required=True)
    descriptions = {
        "enable": "Explicitly enable Interactive Project Evolution.",
        "disable": "Disable after inspecting sessions and resolving pending work.",
        "status": "Read tracker, pins and feedback without running assistance.",
        "promote": "Recheck independent gates and atomically target an eligible build.",
        "cancel-pending": "Cancel an exact pending promotion with an audited reason.",
        "start": "Pin the active build with fresh isolated data; launch no process.",
        "end": "Release a session only after actual stopped-process/effect inspection.",
        "switch": "Create a successor session when every old pin permits promotion.",
        "sessions": "Read immutable session origins and current state.",
        "feedback": "Record source-bound observation; this is not product acceptance.",
        "feedback-list": "Read retained feedback and explicit treatment.",
        "triage": "Record Workflow/Validation or PM routing for explicit follow-up.",
        "retention-preview": "Read exact owned deletion targets and protected references.",
        "retention-apply": "Apply a matching preview hash, preserving manifests and evidence.",
        "operation": "Inspect a durable operation and its exact request/result.",
        "abandon": "Close inspected session preparation, retaining any existing pin.",
    }
    for name, description in descriptions.items():
        action = commands.add_parser(name, help=description, description=description)
        action.add_argument("--root", type=Path, default=argparse.SUPPRESS)
        action.set_defaults(handler=run)
        if name in {"end", "switch"}:
            action.add_argument("session_id")
            _inspect(action)
        elif name in {"triage", "operation", "abandon"}:
            action.add_argument("record_id")
        else:
            action.add_argument("project_id")
        if name in {"promote", "cancel-pending", "switch", "feedback"}:
            action.add_argument("build_id")
        if name == "start":
            action.add_argument("--build-id", help="Must be the exact currently active build.")
        if name in {"start", "end", "switch", "promote", "feedback", "retention-apply"}:
            action.add_argument(
                "--operation-id", help="Stable retry ID; changed requests conflict."
            )
        if name == "cancel-pending":
            action.add_argument("--reason", required=True)
        if name == "abandon":
            _inspect(action)
        if name == "feedback":
            content = action.add_mutually_exclusive_group(required=True)
            content.add_argument(
                "--body", help="Operator observation, never labelled human consent."
            )
            content.add_argument(
                "--interactive", action="store_true", help="Read actual human terminal input."
            )
            action.add_argument("--context", default="")
            action.add_argument("--session-id")
            action.add_argument(
                "--synthetic", action="store_true", help="Label a synthetic fixture."
            )
        if name == "triage":
            action.add_argument(
                "--category", required=True, choices=("BUG", "REQUIREMENT", "OBSERVATION")
            )
            action.add_argument("--reason", required=True)
            action.add_argument(
                "--state", default="TRIAGED", choices=("TRIAGED", "RESOLVED", "DISMISSED")
            )
            action.add_argument("--related-id", action="append", default=[])
            action.add_argument("--expected-version", type=int)
        if name in {"retention-preview", "retention-apply"}:
            action.add_argument("--keep-previous", type=int, default=1)
        if name == "retention-apply":
            action.add_argument(
                "--plan-sha256", required=True, help="Exact hash observed in the preview."
            )
            action.add_argument(
                "--recover", action="store_true", help="Recover a previously reserved deletion."
            )
            action.add_argument("--process-stopped", action="store_true")
            action.add_argument("--effects-inspected", action="store_true")
            action.add_argument("--summary")


def run(arguments):
    try:
        service = PlaytestService(arguments.root)
        action = arguments.playtest_action
        project = getattr(arguments, "project_id", None)
        operation = getattr(arguments, "operation_id", None)
        if action in {"enable", "disable"}:
            result = service.configure(project, enabled=action == "enable")
        elif action == "status":
            result = service.status(project)
        elif action == "promote":
            result = service.promote(project, arguments.build_id, operation_id=operation)
        elif action == "cancel-pending":
            result = service.cancel_pending(project, arguments.build_id, reason=arguments.reason)
        elif action == "start":
            result = service.start(project, build_id=arguments.build_id, operation_id=operation)
        elif action in {"end", "switch"}:
            inspection = {
                "process_stopped": arguments.process_stopped,
                "effects_inspected": arguments.effects_inspected,
                "summary": arguments.summary,
            }
            if action == "end":
                result = service.end(
                    arguments.session_id, inspection=inspection, operation_id=operation
                )
            else:
                result = service.switch(
                    arguments.session_id,
                    arguments.build_id,
                    inspection=inspection,
                    operation_id=operation,
                )
        elif action in {"sessions", "feedback-list"}:
            result = service.repository.list(
                "SESSION" if action == "sessions" else "FEEDBACK", project
            )
        elif action == "operation":
            result = service.repository.get("OPERATION", arguments.record_id)
        elif action == "abandon":
            result = service.abandon_operation(
                arguments.record_id,
                inspection={
                    "process_stopped": arguments.process_stopped,
                    "effects_inspected": arguments.effects_inspected,
                    "summary": arguments.summary,
                },
            )
        elif action == "feedback":
            if arguments.interactive:
                if arguments.synthetic or arguments.context:
                    raise ConflictError(
                        "Interactive feedback derives its actual observer and context."
                    )
                result = service.feedback_from_terminal(
                    project,
                    arguments.build_id,
                    session_id=arguments.session_id,
                    operation_id=operation,
                )
            else:
                result = service.feedback(
                    project,
                    arguments.build_id,
                    arguments.body,
                    context=arguments.context,
                    session_id=arguments.session_id,
                    operation_id=operation,
                    synthetic=arguments.synthetic,
                )
        elif action == "triage":
            result = service.triage(
                arguments.record_id,
                category=arguments.category,
                reason=arguments.reason,
                state=arguments.state,
                related_ids=arguments.related_id,
                expected_version=arguments.expected_version,
            )
        elif action == "retention-preview":
            result = service.retention_preview(project, keep_previous=arguments.keep_previous)
        else:
            inspection = None
            if arguments.recover:
                if not operation:
                    raise ConflictError(
                        "Recovery requires the exact durable retention operation ID."
                    )
                saved = service.repository.get("OPERATION", operation)
                if (
                    saved["project_id"] != project
                    or saved["origin"].get("operation") != "PLAYTEST_RETENTION"
                ):
                    raise ConflictError("Recover the actual same-project retention operation.")
                plan = saved["origin"]["request"]["plan"]
                inspection = {
                    "process_stopped": arguments.process_stopped,
                    "effects_inspected": arguments.effects_inspected,
                    "summary": arguments.summary,
                }
            else:
                plan = service.retention_preview(project, keep_previous=arguments.keep_previous)
            if plan["plan_sha256"] != arguments.plan_sha256:
                raise ConflictError("The exact retention preview changed; inspect it again.")
            result = service.retention_apply(plan, operation_id=operation, inspection=inspection)
        print(render_fields(result))
        return 0
    except (ContractError, OSError, ValueError) as error:
        print("Playtest operation failed. " + safe_text(error), file=sys.stderr)
        return 1
