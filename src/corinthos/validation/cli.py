# SPDX-License-Identifier: MPL-2.0
"""Guided terminal entry points for the independent Validation service."""

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from corinthos.contracts import ContractError, ContractRef, ContractStore, IntegrityError
from corinthos.workflow.execution_repository import ExecutionRepository

from .planning import ValidationPlanner
from .procedures import digest, file_hash, validate_binding
from .repository import ValidationRepository
from .runtime import ValidationRunner

_SCOPES = ("MODULE", "INTEGRATION", "CHECKPOINT", "PLAYTEST_MILESTONE", "PRODUCT")


def configure_parser(commands):
    parser = commands.add_parser("validation", help="plan and run independent scoped audits")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="existing project root")
    actions = parser.add_subparsers(dest="action", required=True)

    def action(name):
        command = actions.add_parser(name)
        command.add_argument("--root", type=Path, default=argparse.SUPPRESS)
        command.set_defaults(handler=_handle)
        return command

    plan = action("plan")
    plan.add_argument("project")
    plan.add_argument("--revision")
    plan.add_argument("--scope", choices=_SCOPES, required=True)
    plan.add_argument("--target")
    plan.add_argument("--target-revision")
    plan.add_argument("--target-id", action="append")
    plan.add_argument("--policy", type=Path, required=True)
    plan.add_argument("--policy-schema", type=Path, required=True)
    action("drafts")
    action("show-draft").add_argument("draft")
    bind = action("bind")
    bind.add_argument("draft")
    bind.add_argument("check")
    bind.add_argument("--evaluator", required=True)
    publish = action("publish")
    publish.add_argument("draft")
    publish.add_argument("--evaluator", required=True)
    publish.add_argument("--contract-id")
    publish.add_argument("--previous")
    publish.add_argument("--previous-revision")
    for name in ("show-plan", "run", "impact"):
        command = action(name)
        command.add_argument("plan")
        command.add_argument("--revision")
        if name == "run":
            command.add_argument("--candidate", type=Path)
            command.add_argument("--workflow-attempt")
            command.add_argument("--previous-run")
            command.add_argument("--evaluator", required=True)
    action("runs")
    for name in ("show-run", "history", "recover", "publish-frozen"):
        action(name).add_argument("run")


def _display(value):
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _terminal():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise IntegrityError("Use a foreground terminal for actual independent inspection.")


def _reference(store, identifier, revision=None):
    if revision is None:
        document = store.resolve_active(identifier)
        if document is not None:
            return ContractRef.from_document(document)
    else:
        for item in store.list_events():
            if item["contract_id"] == identifier and item["revision_id"] == revision:
                return ContractRef(identifier, revision, item["contract_type"], item["project_id"])
    raise IntegrityError("The requested exact published contract was not found.")


def _values(label):
    values = []
    print(label + " Enter one value per line and finish with an empty line.")
    while value := input("> ").strip():
        values.append(value)
    return values


def _bind(saved, check_id, evaluator):
    _terminal()
    draft = saved["plan"]
    row = next((item for item in draft["obligations"] if item["check_id"] == check_id), None)
    if row is None:
        raise IntegrityError("The check is outside the current draft.")
    _display(row)
    methods = row["verification_methods"]
    suggested = methods[0] if methods else ("REVIEW" if row["review_required"] else "TEST")
    method = input(f"Exact verification method [{suggested}]: ").strip() or suggested
    description = input("Procedure and criterion-specific observation: ").strip()
    paths = _values("Candidate-relative files actually inspected by the reviewer.")
    command = None
    if input("Bind a trusted independent executable procedure? [yes/no] ").strip() == "yes":
        argv = _values(
            "Absolute executable followed by its arguments. Use {candidate} or {scratch} as complete arguments."
        )
        if not argv:
            raise IntegrityError("A command needs an executable.")
        inputs = {}
        for i, arg in enumerate(argv):
            if Path(arg).is_absolute():
                argv[i] = str(Path(arg).resolve(strict=True))
                inputs[argv[i]] = file_hash(argv[i])
        command = {
            "argv": argv,
            "timeout": int(input("Maximum duration in seconds [60]: ").strip() or "60"),
            "inputs": inputs,
            "success_line": input("Exact expected success output line: "),
            "failure_line": input("Exact demonstrated-failure output line, or Enter: ") or None,
        }
    binding = validate_binding(
        {
            "method": method,
            "description": description,
            "required_evidence": row["required_evidence"],
            "command": command,
            "review_paths": paths,
        }
    )
    _display(binding)
    rationale = input(
        "After inspecting the procedure, explain the actual assertion or observation that evaluates this exact criterion: "
    ).strip()
    if not rationale:
        raise IntegrityError(
            "Record the separate evaluator's substantive method-adequacy reasoning."
        )
    saved["bindings"][check_id] = binding
    saved["reviews"][check_id] = {
        "actor_id": evaluator,
        "criterion_sha256": digest(
            {"source_ref": row["source_ref"], "criterion": row["criterion"]}
        ),
        "binding_sha256": digest(binding),
        "rationale": rationale,
    }


def _review(request):
    _terminal()
    _display(request)
    print("Inspect the listed files in the exact candidate copy. Record your actual observation.")
    status = input("CONFORMANT, NONCONFORMANT, NOT_VERIFIED or justified NOT_APPLICABLE: ").strip()
    rationale = input("Observed facts and criterion-specific rationale: ").strip()
    return {
        "evaluator": request["evaluator"],
        "artifact_identity": request["artifact_identity"],
        "inspected": request["paths"],
        "status": status,
        "rationale": rationale,
    }


def _handle(arguments):
    try:
        store = ContractStore(arguments.root)
        repository = ValidationRepository(store)
        action = arguments.action
        if action == "plan":
            planner = ValidationPlanner(store, arguments.policy, arguments.policy_schema)
            project = _reference(store, arguments.project, arguments.revision)
            target = (
                _reference(store, arguments.target, arguments.target_revision)
                if arguments.target
                else None
            )
            draft = planner.derive(
                project, arguments.scope, target_ref=target, target_ids=arguments.target_id
            )
            _display(
                repository.save_draft(
                    "draft-" + uuid4().hex,
                    {
                        "plan": draft,
                        "bindings": {},
                        "reviews": {},
                        "policy": str(arguments.policy.resolve()),
                        "policy_schema": str(arguments.policy_schema.resolve()),
                    },
                )
            )
        elif action == "drafts":
            _display(repository.list_drafts())
        elif action in {"show-draft", "bind", "publish"}:
            view = repository.get_draft(arguments.draft)
            saved = view["draft"]
            if action == "show-draft":
                _display(view)
            elif action == "bind":
                _bind(saved, arguments.check, arguments.evaluator)
                saved.pop("diagnostics", None)
                _display(
                    repository.save_draft(arguments.draft, saved, expected_version=view["version"])
                )
            else:
                planner = ValidationPlanner(store, saved["policy"], saved["policy_schema"])
                previous = (
                    _reference(store, arguments.previous, arguments.previous_revision)
                    if arguments.previous
                    else None
                )
                try:
                    ref = planner.publish(
                        saved["plan"],
                        saved["bindings"],
                        saved["reviews"],
                        actor_id=arguments.evaluator,
                        contract_id=arguments.contract_id,
                        previous=previous,
                    )
                except ContractError as error:
                    saved["diagnostics"] = [str(error)[:1024]]
                    repository.save_draft(arguments.draft, saved, expected_version=view["version"])
                    raise
                _display(ref.to_json())
        elif action in {"show-plan", "run", "impact"}:
            ref = _reference(store, arguments.plan, arguments.revision)
            runner = ValidationRunner(store)
            if action == "show-plan":
                _display(runner.inspect_plan(ref))
            elif action == "impact":
                _display(runner.inspect_impact(ref))
            else:
                candidate, identity = arguments.candidate, None
                if arguments.workflow_attempt:
                    request = ExecutionRepository(store).audit_request(arguments.workflow_attempt)
                    candidate = candidate or Path(request["workspace"])
                    identity = request["artifact_identity"]
                    runner.require_requested_scope(ref, request)
                if candidate is None:
                    raise IntegrityError(
                        "Use --candidate or --workflow-attempt for the exact audit target."
                    )
                reviewer = _review if sys.stdin.isatty() and sys.stdout.isatty() else None
                result = runner.run(
                    ref,
                    candidate,
                    evaluator=arguments.evaluator,
                    expected_identity=identity,
                    reviewer=reviewer,
                    previous_run_id=arguments.previous_run,
                )
                document = store.get(result)
                _display(
                    {"result": result.to_json(), "gate": document["payload"]["gate_assessment"]}
                )
                return int(document["payload"]["gate_assessment"]["state"] != "SATISFIED")
        elif action == "runs":
            _display(repository.list())
        elif action == "show-run":
            _display(repository.get(arguments.run))
        elif action == "history":
            _display(repository.history(arguments.run))
        else:
            runner = ValidationRunner(store)
            if action == "recover":
                _terminal()
                _display(repository.get(arguments.run))
                stopped = (
                    input("Enter STOPPED after confirming the processes stopped: ") == "STOPPED"
                )
                inspected = (
                    input("Enter INSPECTED after examining all possible effects: ") == "INSPECTED"
                )
                reason = input("Actual inspection observations: ").strip()
                ref = runner.recover(
                    arguments.run,
                    {
                        "process_stopped": stopped,
                        "effects_inspected": inspected,
                        "reason": reason,
                    },
                )
            else:
                ref = runner.publish_frozen(arguments.run)
            _display(ref.to_json())
    except (ContractError, OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        print(f"validation: {str(error) or 'Interrupted.'}", file=sys.stderr)
        return 1
    return 0
