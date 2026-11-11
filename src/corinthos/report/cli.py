# SPDX-License-Identifier: MPL-2.0
"""Thin terminal commands over frozen Report Engine snapshots."""

import argparse
import json
import sys
from pathlib import Path

from corinthos.contracts import ContractError, ContractRef, IntegrityError

from .rendering import export_report, render_json, render_markdown, safe_prose, verify_export

_KINDS = ("CHECKPOINT", "MILESTONE", "PRODUCT", "HISTORY", "EVOLUTION")


def configure_parser(commands):
    parser = commands.add_parser("report", help="generate and inspect exact audit reports")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="existing Core project root")
    actions = parser.add_subparsers(dest="action", required=True)

    def action(name, help):
        command = actions.add_parser(name, help=help)
        command.add_argument("--root", type=Path, default=argparse.SUPPRESS)
        command.set_defaults(handler=_handle)
        return command

    generate = action("generate", "collect sources and freeze a report draft")
    generate.add_argument("project", help="published Project contract identifier")
    generate.add_argument("--kind", choices=_KINDS, default="PRODUCT")
    generate.add_argument("--candidate", type=Path, help="exact candidate directory to inventory")
    generate.add_argument("--snapshot-id")
    generate.add_argument("--commit")
    generate.add_argument("--build-id")
    generate.add_argument("--as-of", help="explicit historical UTC cutoff")
    generate.add_argument("--checkpoint-id", action="append", default=[])
    generate.add_argument("--milestone-id")
    generate.add_argument("--delivery-record", type=Path)
    generate.add_argument("--report-id")
    generate.add_argument("--previous", help="exact preceding logical Report contract")
    generate.add_argument("--previous-revision")
    generate.add_argument("--reason", help="reason for a corrected or updated snapshot")
    generate.add_argument("--audience", default="Project owner")
    generate.add_argument("--objective")
    generate.add_argument("--actor", default="report-cli")
    action("drafts", "list frozen draft summaries")
    draft = action("show-draft", "inspect a frozen draft before publication")
    draft.add_argument("draft")
    draft.add_argument("--format", choices=("json", "markdown"), default="markdown")
    publish = action("publish", "publish the exact frozen report through the Kernel")
    publish.add_argument("draft")
    publish.add_argument("--actor")
    recover = action("recover", "reconcile publication of an existing frozen draft")
    recover.add_argument("draft")
    listing = action("list", "list published reports for a project")
    listing.add_argument("project_id", help="project_id from contract metadata")
    history = action("history", "list immutable revisions of one Report contract")
    history.add_argument("report")
    for name, description in (
        ("show", "reopen an exact published report"),
        ("verify", "observe present report evidence integrity separately"),
        ("export", "write or recover a private JSON/Markdown export bundle"),
    ):
        command = action(name, description)
        command.add_argument("report")
        command.add_argument("--revision")
        if name == "show":
            command.add_argument("--format", choices=("json", "markdown"), default="markdown")
        if name == "export":
            command.add_argument("--destination", type=Path, required=True)
            command.add_argument("--format", choices=("both", "json", "markdown"), default="both")
    compare = action("compare", "compare exact report snapshots and candidate identities")
    compare.add_argument("left")
    compare.add_argument("right")
    compare.add_argument("--left-revision")
    compare.add_argument("--right-revision")
    check = action("verify-export", "check bundle bytes against its exact stored ERC")
    check.add_argument("destination", type=Path)


def _display(value):
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _reference(service, identifier, revision=None):
    if revision is None:
        return ContractRef.from_document(service.latest(identifier))
    for document in service.history(identifier):
        if document["metadata"]["revision_id"] == revision:
            return ContractRef.from_document(document)
    raise IntegrityError("The exact published report revision was not found.")


def _show(document, format):
    if format == "json":
        print(render_json(document), end="")
    else:
        print(render_markdown(document), end="")


def _handle(arguments):
    from .service import ReportService

    try:
        service = ReportService(arguments.root)
        action = arguments.action
        if action == "generate":
            identity = {
                key: value
                for key, value in (
                    ("snapshot_id", arguments.snapshot_id),
                    ("commit", arguments.commit),
                    ("build_id", arguments.build_id),
                )
                if value is not None
            }
            if arguments.candidate is not None and identity:
                raise IntegrityError("Choose a candidate directory or explicit artifact identity.")
            if arguments.previous_revision and not arguments.previous:
                raise IntegrityError("A preceding revision needs its Report contract identifier.")
            previous = (
                _reference(service, arguments.previous, arguments.previous_revision)
                if arguments.previous
                else None
            )
            view = service.generate(
                arguments.project,
                kind=arguments.kind,
                candidate=arguments.candidate,
                artifact_identity=identity or None,
                as_of=arguments.as_of,
                checkpoint_ids=tuple(arguments.checkpoint_id),
                milestone_id=arguments.milestone_id,
                delivery_record=arguments.delivery_record,
                report_id=arguments.report_id,
                previous=previous,
                reason=arguments.reason,
                audience=arguments.audience,
                objective=arguments.objective,
                actor_id=arguments.actor,
            )
            _display(
                {
                    "draft_id": view["draft_id"],
                    "report_ref": view["report_ref"],
                    "as_of": view["document"]["payload"]["report_scope"]["as_of"],
                    "states": view["document"]["payload"]["version_and_delivery_lineage"],
                    "next_action": "Inspect with show-draft, then publish this draft under the same root.",
                }
            )
        elif action == "drafts":
            _display(service.drafts())
        elif action == "show-draft":
            _show(service.draft(arguments.draft)["document"], arguments.format)
        elif action in {"publish", "recover"}:
            reference = (
                service.publish(arguments.draft, actor_id=arguments.actor)
                if action == "publish"
                else service.recover(arguments.draft)
            )
            _display(reference.to_json())
        elif action == "list":
            _display(service.list(arguments.project_id))
        elif action == "history":
            documents = service.history(arguments.report)
            for document in documents:
                render_json(document)
            _display(documents)
        elif action == "compare":
            left = _reference(service, arguments.left, arguments.left_revision)
            right = _reference(service, arguments.right, arguments.right_revision)
            _display(service.compare(left, right))
        elif action == "verify-export":
            observed = verify_export(arguments.destination)
            reference = ContractRef.from_json(observed["report_ref"])
            observed = verify_export(
                arguments.destination,
                document=service.get(reference),
                manifest=service.manifest(reference),
            )
            _display(observed)
            return int(observed["state"] != "COMPLETE")
        else:
            reference = _reference(service, arguments.report, arguments.revision)
            if action == "verify":
                observed = service.verify(reference)
                _display(observed)
                return int(observed["complete"] is not True)
            document = service.get(reference)
            if action == "show":
                _show(document, arguments.format)
            else:
                _display(
                    export_report(
                        document,
                        arguments.destination,
                        manifest=service.manifest(reference),
                        format=arguments.format,
                    )
                )
    except (ContractError, OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        print("report: " + safe_prose(str(error) or "Interrupted."), file=sys.stderr)
        return 1
    return 0
