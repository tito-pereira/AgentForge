# SPDX-License-Identifier: MPL-2.0
"""Installed terminal journeys for Workflow-owned isolated builds."""

import argparse
import json
import sys
from pathlib import Path

from corinthos.contracts import ContractError, IntegrityError
from corinthos.lifecycle.builds import BuildService
from corinthos.project_manager.approval import local_actor_id
from corinthos.project_manager.presentation import safe_text
from corinthos.validation.cli import _reference, _review
from corinthos.workflow.verification import CommandCheck, TechnicalReview


def add_cli(commands):
    parser = commands.add_parser(
        "build", help="Materialize, check and independently audit isolated builds."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    actions = parser.add_subparsers(dest="build_action", required=True)

    def action(name):
        command = actions.add_parser(name)
        command.add_argument("--root", type=Path, default=argparse.SUPPRESS)
        command.set_defaults(handler=_handle)
        return command

    prepare = action("prepare")
    prepare.add_argument("workflow")
    prepare.add_argument("milestone")
    prepare.add_argument("execution")
    prepare.add_argument("--revision")
    prepare.add_argument("--source", type=Path)
    prepare.add_argument("--package", action="append", default=[])
    prepare.add_argument("--operation")
    prepare.add_argument("--recipe-executable", type=Path)
    prepare.add_argument("--recipe-arg", action="append", default=[])
    prepare.add_argument("--recipe-timeout", type=float, default=60)
    action("list").add_argument("project")
    for name in ("show", "readiness", "validate", "admission"):
        command = action(name)
        command.add_argument("build")
        if name == "readiness":
            command.add_argument("--check-executable", type=Path, required=True)
            command.add_argument("--check-arg", action="append", default=[])
            command.add_argument("--check-timeout", type=float, default=60)
        if name == "validate":
            command.add_argument("plan")
            command.add_argument("--revision")
            command.add_argument("--evaluator", required=True)
            command.add_argument("--previous-run")
    action("recover").add_argument("operation")


def _display(value):
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _terminal():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise IntegrityError("Use a foreground terminal for actual review or effect inspection.")


def _readiness_review(request):
    _terminal()
    _display(request)
    for criterion in request["criteria"]:
        print(safe_text(criterion["criterion"]))
    accepted = (
        input("After inspecting the actual candidate/check evidence, enter READY or BLOCKED: ")
        == "READY"
    )
    rationale = input("Actual technical observations: ").strip()
    if not rationale:
        raise IntegrityError("Record actual criterion-specific technical observations.")
    return TechnicalReview(
        local_actor_id(),
        accepted,
        tuple(item["criterion_id"] for item in request["criteria"]),
        request["artifact_identity"],
        (rationale,),
    )


def _handle(arguments):
    try:
        service = BuildService(arguments.root)
        action = arguments.build_action
        if action == "prepare":
            recipe = ()
            if arguments.recipe_executable:
                recipe = (
                    CommandCheck(
                        "package-build",
                        "Materialize the declared package outputs",
                        (str(arguments.recipe_executable.absolute()), *arguments.recipe_arg),
                        timeout=arguments.recipe_timeout,
                    ),
                )
            elif arguments.recipe_arg:
                raise IntegrityError("Recipe arguments require an explicit native executable.")
            result = service.prepare(
                _reference(service.store, arguments.workflow, arguments.revision),
                arguments.milestone,
                arguments.execution,
                arguments.source or service.root,
                commands=recipe,
                package_paths=arguments.package,
                operation_id=arguments.operation,
            )
        elif action == "list":
            result = service.repository.list("BUILD", arguments.project)
        elif action == "show":
            result = service.get(arguments.build)
        elif action == "readiness":
            record = service.get(arguments.build)
            checks = tuple(
                CommandCheck(
                    "scenario-" + str(i + 1),
                    scenario,
                    (str(arguments.check_executable.absolute()), *arguments.check_arg),
                    timeout=arguments.check_timeout,
                )
                for i, scenario in enumerate(record["origin"]["scenarios"])
            )
            reviewer = _readiness_review if sys.stdin.isatty() and sys.stdout.isatty() else None
            result = service.readiness(arguments.build, checks=checks, reviewer=reviewer)
            _display(result)
            return int(result["snapshot"]["readiness"]["state"] != "SATISFIED")
        elif action == "validate":
            reference = service.validate(
                arguments.build,
                _reference(service.store, arguments.plan, arguments.revision),
                evaluator=arguments.evaluator,
                reviewer=_review if sys.stdin.isatty() and sys.stdout.isatty() else None,
                previous_run_id=arguments.previous_run,
            )
            document = service.store.get(reference)
            result = {
                "result_ref": reference.to_json(),
                "gate": document["payload"]["gate_assessment"],
            }
            _display(result)
            return int(result["gate"]["state"] != "SATISFIED")
        elif action == "admission":
            with service.repository.transaction() as connection:
                result = service.require_eligible(arguments.build, connection)
        else:
            _terminal()
            _display(service.repository.get("OPERATION", arguments.operation))
            inspection = {
                "process_stopped": input("Enter STOPPED after inspecting owned processes: ")
                == "STOPPED",
                "effects_inspected": input("Enter INSPECTED after examining effects: ")
                == "INSPECTED",
                "reason": input("Actual observations: ").strip(),
            }
            result = service.recover(arguments.operation, inspection)
        _display(result)
    except (ContractError, OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        print("build: " + safe_text(str(error) or "Interrupted."), file=sys.stderr)
        return 1
    return 0
