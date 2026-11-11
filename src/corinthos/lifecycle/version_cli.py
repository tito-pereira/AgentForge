# SPDX-License-Identifier: MPL-2.0
"""Installed delivered-version and selective-evolution commands."""

import argparse
import sys
from pathlib import Path

from corinthos.contracts import ContractError
from corinthos.project_manager.presentation import render_fields, safe_text
from corinthos.validation.cli import _reference
from corinthos.workflow.reconciliation import RevisionReconciler

from .versions import VersionService


def add_cli(commands):
    parser = commands.add_parser(
        "version", help="Retain delivered versions and start bounded evolution."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    actions = parser.add_subparsers(dest="version_action", required=True)
    for name in (
        "list",
        "show",
        "verify",
        "deliver",
        "adopt-delivery",
        "evolve",
        "evolution",
        "impact",
        "negotiate",
    ):
        command = actions.add_parser(name)
        command.add_argument("--root", type=Path, default=argparse.SUPPRESS)
        command.set_defaults(handler=_handle)
        command.add_argument("identity")
        if name == "deliver":
            command.add_argument("plan")
            command.add_argument("product_version")
            command.add_argument("--revision")
            command.add_argument("--package", action="append", required=True)
            command.add_argument("--documentation", action="append", default=[])
            command.add_argument("--previous-version")
        elif name == "adopt-delivery":
            command.add_argument("--revision")
            command.add_argument("--candidate", type=Path, required=True)
            command.add_argument("--delivery-record", type=Path, required=True)
        elif name == "evolve":
            command.add_argument(
                "change_class",
                choices=("OPERATIONAL", "INTERNAL_REPLAN", "BINDING_PLAN", "PROJECT_CHANGE"),
            )
            command.add_argument("--reason", required=True)
            command.add_argument("--request-id")


def _handle(arguments):
    try:
        service = VersionService(arguments.root)
        action, identity = arguments.version_action, arguments.identity
        if action == "list":
            result = service.list(identity)
        elif action == "show":
            result = service.get(identity)
        elif action == "verify":
            result = service.require_delivered(identity)
        elif action == "deliver":
            result = service.deliver(
                identity,
                _reference(service.store, arguments.plan, arguments.revision),
                arguments.product_version,
                package_paths=arguments.package,
                documentation_paths=arguments.documentation,
                previous_version_id=arguments.previous_version,
            )
        elif action == "adopt-delivery":
            result = service.adopt_delivery(
                _reference(service.store, identity, arguments.revision),
                arguments.candidate,
                arguments.delivery_record,
            )
        elif action == "evolve":
            result = service.evolve(
                identity, arguments.change_class, arguments.reason, request_id=arguments.request_id
            )
        elif action == "evolution":
            result = service.repository.get("EVOLUTION", identity)
        elif action == "negotiate":
            result = service.negotiate(identity)
        else:
            record = service.repository.get("EVOLUTION", identity)
            result = RevisionReconciler(service.store).inspect(record["origin"]["workflow_ref"])
        print(render_fields(result))
        return 0
    except (ContractError, OSError, ValueError) as error:
        print(safe_text(str(error)), file=sys.stderr)
        return 1
