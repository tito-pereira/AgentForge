# SPDX-License-Identifier: MPL-2.0
"""Guided execution configuration, inspection and explicit recovery decisions."""

import argparse
import json
import secrets
import sys
from dataclasses import replace
from pathlib import Path

from corinthos.adapters import AdapterManager
from corinthos.bootstrap import adapter_manager, show_adapters
from corinthos.contracts import (
    AuthorityError,
    ContractError,
    ContractRef,
    ContractStore,
    IntegrityError,
)
from corinthos.project_manager.approval import _terminal, local_actor_id
from corinthos.project_manager.cli import _answer, _lines, _pick
from corinthos.project_manager.presentation import render_fields, safe_text
from corinthos.work import WorkService
from corinthos.work.model import ScopeLevel

from .cli import _exact, _identifier, _links
from .execution_repository import ExecutionRepository
from .reconciliation import RevisionReconciler
from .runtime import WorkflowRunner
from .verification import (
    AuditExpectation,
    CheckpointSpec,
    CommandCheck,
    TechnicalReview,
    ValidationGateConsumer,
    _managed_plan,
    workspace_snapshot,
)
from .work_binding import (
    critical_audit_expectations,
    remove_predecessor_critical_audits,
    work_fingerprint,
)

_CHECKOUT_POLICY = Path("policies/standard.yaml")
_CHECKOUT_SCHEMA = Path("schemas/standard.schema.json")


def configure_parser(actions) -> None:
    descriptions = {
        "configure": "Bind an approved Workflow to actual files and verification commands.",
        "executions": "List durable project executions.",
        "status": "Inspect execution, checkpoint and attempt status.",
        "execute": "Run one eligible checkpoint and its actual engineering checks.",
        "recover": "Inspect interrupted effects before retry, verification or blocking.",
        "reconcile": "Move to an approved current plan while preserving eligible old evidence.",
        "changes": "Inspect active source revisions and conservative impact.",
        "request": "Diagnose a bounded structural conflict for Project Manager negotiation.",
        "execution-history": "Inspect append-only execution observations.",
        "audit-request": "Inspect an exact retained verifying or blocked candidate for Validation.",
    }
    for name, description in descriptions.items():
        parser = actions.add_parser(name, help=description, description=description)
        parser.add_argument(
            "--root", type=Path, default=argparse.SUPPRESS, help="Authorized project workspace."
        )
        if name in {"configure", "changes", "request"}:
            parser.add_argument("contract_id", help="Published Workflow logical ID.")
            parser.add_argument("--revision", help="Exact published revision ID.")
        elif name == "audit-request":
            parser.add_argument("attempt_id", help="Current verifying or blocked attempt ID.")
        elif name != "executions":
            parser.add_argument(
                "execution_id",
                nargs=None if name == "reconcile" else "?",
                help="Execution ID, or choose from a list.",
            )
        if name == "reconcile":
            parser.add_argument("contract_id", help="Approved replacement Workflow logical ID.")
            parser.add_argument("--revision", help="Exact replacement revision ID.")
        if name in {"configure", "reconcile"}:
            parser.add_argument(
                "--work-item",
                help="Explicit PROJECT or CRITICAL Work Item covered by this Workflow.",
            )
        if name == "recover":
            parser.add_argument(
                "checkpoint_id", nargs="?", help="Interrupted checkpoint ID, or choose from a list."
            )
        if name in {"configure", "execute", "recover", "reconcile"}:
            parser.add_argument(
                "--policy",
                type=Path,
                help="Existing Standard policy path. Defaults to the checkout or installed Standard.",
            )
            parser.add_argument(
                "--policy-schema",
                type=Path,
                help="Existing Standard schema path.",
            )
            parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
            parser.add_argument(
                "--provider-executable",
                type=Path,
                help="Native provider executable, or native host such as node.exe.",
            )
            parser.add_argument(
                "--provider-arg",
                action="append",
                default=[],
                help="One fixed native-host prefix argument. Repeat to preserve separate arguments.",
            )
        if name in {"configure", "reconcile"}:
            parser.add_argument(
                "--formal-audits",
                action="store_true",
                help="Bind required exact audit scopes even when their plans are absent.",
            )
        if name == "execute":
            parser.add_argument(
                "--timeout", type=float, default=300, help="Bounded agent timeout in seconds."
            )
        if name == "request":
            parser.add_argument(
                "--request-id", help="Stable request identity for an idempotent retry."
            )
        parser.set_defaults(handler=run, runtime_action=name)


def _technical_review(request: dict) -> TechnicalReview:
    """Record a deliberate local preliminary review of the actual observed artifact."""
    with _terminal() as (reader, writer):
        writer.write("PRELIMINARY ENGINEERING TECHNICAL REVIEW\n")
        writer.write("Review the actual artifact, checks and every completion criterion below.\n")
        writer.write(
            "Formal independent Validation and human product acceptance remain separate.\n"
        )
        writer.write(render_fields(request) + "\n")
        challenge = "ACCEPT " + secrets.token_hex(6)
        writer.write(
            "Type "
            + challenge
            + " to accept this exact preliminary review.\nEvery other answer records reservations.\n> "
        )
        writer.flush()
        accepted = reader.readline(256).rstrip("\r\n") == challenge
        writer.write("Record your actual observations or reservations\n> ")
        writer.flush()
        finding = reader.readline(8193).strip()
        if not finding:
            raise AuthorityError("A technical review needs actual observations or reservations.")
        return TechnicalReview(
            local_actor_id(),
            accepted,
            tuple(item["criterion_id"] for item in request["checkpoint"]["completion_criteria"]),
            request["artifact_identity"],
            (finding,),
        )


def _runner(arguments, store) -> WorkflowRunner:
    if arguments.provider_arg and arguments.provider_executable is None:
        raise IntegrityError("Native-host arguments require an explicit executable.")
    overrides = {}
    if arguments.provider_executable is not None:
        overrides[arguments.provider] = (
            str(arguments.provider_executable),
            *arguments.provider_arg,
        )
    policy = arguments.policy or _CHECKOUT_POLICY
    schema = arguments.policy_schema or _CHECKOUT_SCHEMA
    if policy.is_file() and schema.is_file():
        commands = {
            choice["provider"]: (choice["executable"],)
            for choice in show_adapters(arguments.root)
            if choice["executable"] is not None
        }
        commands.update(overrides)
        adapters = AdapterManager(policy, schema, store=store, commands=commands)
    elif arguments.policy is None and arguments.policy_schema is None:
        adapters = adapter_manager(arguments.root, store=store, operation_commands=overrides)
    else:
        raise IntegrityError(
            "Select existing Standard policy and schema paths for this installation."
        )
    return WorkflowRunner(arguments.root, adapters, reviewer=_technical_review)


def _choose_audits(store, consumer, workflow, checkpoint_id, existing):
    reference = ContractRef.from_document(workflow)
    payload = workflow["payload"]
    candidates = [
        AuditExpectation("CHECKPOINT", reference, (checkpoint_id,)),
        AuditExpectation(
            "PRODUCT",
            ContractRef.from_json(payload["project_contract_ref"]),
            (reference.project_id,),
        ),
    ]
    integration_ids = set()
    for row in payload["modules"]:
        module_ref = ContractRef.from_json(row["module_contract_ref"])
        identifier = row["module_id"]
        candidates.append(AuditExpectation("MODULE", module_ref, (identifier,)))
        integration_ids.add(identifier)
        module = store.get(module_ref)["payload"]
        integration_ids.update(
            item["interface_id"]
            for item in (*module["provided_interfaces"], *module["consumed_interfaces"])
        )
    candidates.extend(
        AuditExpectation("INTEGRATION", reference, (identifier,))
        for identifier in sorted(integration_ids)
    )
    candidates.extend(
        AuditExpectation("PLAYTEST_MILESTONE", reference, (row["milestone_id"],))
        for row in payload["playtest_milestones"]
    )
    available = [
        item
        for item in candidates
        if item not in existing and consumer.scope_allowed(workflow, checkpoint_id, item)
    ]
    chosen = list(existing)
    while available:
        selected = _pick(
            [None, *available],
            lambda item: (
                "Finish audit bindings" if item is None else f"{item.level} {', '.join(item.scope)}"
            ),
            "Choose an exact formal audit scope",
        )
        if selected is None:
            break
        chosen.append(selected)
        available.remove(selected)
    return tuple(chosen)


def _specifications(store, reference, *, existing=None, formal=False, critical=False):
    workflow = store.get(reference)
    if workflow is None or reference.contract_type != "WORKFLOW":
        raise IntegrityError("Execution configuration requires an exact published Workflow.")
    mandatory = critical_audit_expectations(workflow) if critical else {}
    specs = []
    for checkpoint in workflow["payload"]["checkpoints"]:
        print("CHECKPOINT EXECUTION CONFIGURATION")
        print(render_fields(checkpoint))
        prior = (existing or {}).get(checkpoint["checkpoint_id"])
        required = mandatory.get(checkpoint["checkpoint_id"])
        if prior:
            print("Previously bound configuration")
            print(render_fields(prior))
            if _answer("Keep or replace this configuration?", default="keep").lower() == "keep":
                spec = CheckpointSpec.from_json(prior)
                if required is not None and required not in spec.audit_expectations:
                    spec = replace(spec, audit_expectations=(*spec.audit_expectations, required))
                specs.append(spec)
                continue
        commands, reviews = [], []
        for item in checkpoint["verification_plan"]:
            print("Approved verification item " + safe_text(item))
            method = _pick(["Actual automated command", "Explicit technical review"], str)
            if method == "Explicit technical review":
                reviews.append(item)
                continue
            executable = _answer("Executable path or command name. Enter it without shell syntax")
            argv = [
                executable,
                *_lines(
                    "Enter each command argument as its own item, preserving spaces within that argument"
                ),
            ]
            cwd = _answer("Relative working directory for this check", default=".")
            commands.append(CommandCheck(_identifier("check"), item, tuple(argv), cwd))
        deliverables = {
            item: _lines(
                "List actual relative files for this approved deliverable: " + safe_text(item)
            )
            for item in checkpoint["deliverables"]
        }
        allowed = _lines(
            "List permitted relative source files or directories. Use explicit paths, without a root wildcard"
        )
        consumer = ValidationGateConsumer(store)
        gates, expectations, _ = consumer.requirements(reference, checkpoint["checkpoint_id"])
        if required is not None and required not in expectations:
            expectations = (*expectations, required)
        print("Applicable published independent checkpoint gates")
        print(
            render_fields(
                [
                    {
                        "validation_plan_ref": item.validation_plan_ref.to_json(),
                        "gate": item.gate,
                        "scope": item.scope,
                    }
                    for item in gates
                ]
            )
        )
        if formal:
            expectations = _choose_audits(
                store, consumer, workflow, checkpoint["checkpoint_id"], expectations
            )
        specs.append(
            CheckpointSpec(
                checkpoint["checkpoint_id"],
                tuple(commands),
                deliverables,
                tuple(allowed),
                tuple(reviews),
                tuple(
                    gate for gate in gates if not _managed_plan(store.get(gate.validation_plan_ref))
                ),
                expectations,
            )
        )
    return specs


def _execution(repository, identifier):
    return (
        repository.get(identifier)
        if identifier
        else _pick(
            repository.list(), lambda item: item["execution_id"] + " [" + item["state"] + "]"
        )
    )


def _recover(runner, execution, checkpoint_id, actor):
    checkpoint = (
        execution["checkpoints"].get(checkpoint_id)
        if checkpoint_id
        else _pick(
            list(execution["checkpoints"].values()),
            lambda item: item["checkpoint_id"] + " [" + item["state"] + "]",
        )
    )
    if checkpoint is None or checkpoint["attempt_id"] is None:
        raise IntegrityError("Select a checkpoint with an unfinished attempt to inspect.")
    previous = runner.repository.get_attempt(checkpoint["attempt_id"])
    print("PREVIOUS ATTEMPT AND OBSERVED EFFECTS")
    print(render_fields(previous))
    print("CURRENT WORKSPACE SNAPSHOT")
    snapshot = workspace_snapshot(runner.root)
    print(render_fields(snapshot))
    print(
        "Inspect process state, working files, artifacts and external effects before choosing recovery."
    )
    if (
        _answer("Type STOPPED after confirming the old process is stopped", optional=True)
        != "STOPPED"
    ):
        raise IntegrityError("Recovery requires confirmed process termination.")
    if _answer("Type INSPECTED after inspecting its effects", optional=True) != "INSPECTED":
        raise IntegrityError("Recovery requires explicit effects inspection.")
    summary = _answer("Record the actual effects and your recovery reasoning")
    decision = _pick(
        ["RETRY", "VERIFY", "BLOCK"],
        lambda item: {
            "RETRY": "Make ready for a separately requested new agent attempt",
            "VERIFY": "Check existing files without invoking the agent again",
            "BLOCK": "Preserve evidence while investigation continues",
        }[item],
    )
    observed = {
        "snapshot_id": snapshot["artifact_identity"]["snapshot_id"],
        "commit_id": snapshot["artifact_identity"].get("commit"),
        "files": snapshot["files"],
    }
    result = runner.repository.recover(
        execution["execution_id"],
        checkpoint["checkpoint_id"],
        execution["version"],
        actor_id=actor,
        inspection={"process_stopped": True, "effects_inspected": True, "summary": summary},
        decision=decision,
        owner_id=runner.owner_id,
        context={"source_snapshot": observed},
    )
    if decision == "VERIFY":
        result = runner.verify_existing(
            result["checkpoints"][checkpoint["checkpoint_id"]]["attempt_id"]
        )
    print(render_fields(result))
    return 0 if decision != "VERIFY" or result["state"] == "COMPLETED" else 1


def _carry_completed(execution, workflow, bindings, proposed_ids):
    """Carry only unchanged completed work with a fully carried prerequisite set."""
    old_bindings = execution["bindings"]["checkpoints"]
    current = bindings["checkpoints"]
    carried = {
        identifier
        for identifier in proposed_ids
        if execution["checkpoints"].get(identifier, {}).get("state") == "COMPLETED"
        and identifier in current
        and old_bindings.get(identifier) == current[identifier]
    }
    rows = {row["checkpoint_id"]: row for row in workflow["payload"]["checkpoints"]}
    while True:
        eligible = {
            identifier for identifier in carried if set(rows[identifier]["depends_on"]) <= carried
        }
        if eligible == carried:
            return sorted(carried)
        carried = eligible


def _structural_request(reconciler, reference, actor, request_id):
    workflow = reconciler.store.get(reference)
    if workflow is None or reference.contract_type != "WORKFLOW":
        raise IntegrityError("A structural diagnosis requires an exact published Workflow.")
    category = _pick(
        ["STRUCTURAL_CONFLICT", "LOCAL_FAILURE", "OWNER_CHANGE"],
        lambda item: {
            "STRUCTURAL_CONFLICT": "An evidenced structural conflict needs product-level negotiation",
            "LOCAL_FAILURE": "A bug, failed check or agent issue needs repair under current obligations",
            "OWNER_CHANGE": "The owner wants to change the product requirements directly",
        }[item],
    )
    if category == "LOCAL_FAILURE":
        print(
            "Keep the existing product obligations. Inspect the execution and use scoped repair or recovery."
        )
        return
    if category == "OWNER_CHANGE":
        session = reconciler.start_project_revision(
            workflow["payload"]["project_contract_ref"],
            _answer("Describe the owner's requested global change"),
            actor_id=actor,
        )
        print("Project Manager revision session")
        print(render_fields(session))
        print("Continue with corinthos project resume " + safe_text(session["session_id"]))
        return
    project = reconciler.store.get(
        ContractRef.from_json(workflow["payload"]["project_contract_ref"])
    )
    print("EXACT APPROVED PRODUCT OBLIGATIONS")
    print(render_fields(project))
    affected = {}
    for key, collection, id_key in (
        ("proposal_ids", "structural_proposals", "proposal_id"),
        ("requirement_ids", "requirements", "requirement_id"),
        ("constraint_ids", "constraints", "constraint_id"),
    ):
        print("Affected " + collection.replace("_", " "))
        affected[key] = _links(project["payload"][collection], id_key)
    criteria = [
        *project["payload"]["success_criteria"],
        *(
            criterion
            for item in project["payload"]["requirements"]
            for criterion in item["acceptance_criteria"]
        ),
    ]
    print("Affected product criteria")
    affected["criterion_ids"] = _links(criteria, "criterion_id")
    inconsistency = {
        "kind": "STRUCTURAL_CONFLICT",
        "description": _answer("Explain the structural incompatibility"),
        "confirmed_facts": _lines("Record confirmed facts"),
        "uncertainties": _lines("Record remaining uncertainties"),
    }
    sources = reconciler.inspect(reference)["source_refs"]
    source = _pick(
        sources,
        lambda item: (
            item["contract_type"] + " " + item["contract_id"] + " / " + item["revision_id"]
        ),
    )
    evidence = {
        "source_ref": source,
        "evidence_ids": [],
        "description": _answer("Explain what this exact published source establishes"),
        "limitations": _lines("State the evidence and verification limitations"),
    }
    alternatives = []
    while text := _answer(
        "Describe an actual alternative, or leave empty to finish", optional=True
    ):
        alternatives.append(
            {
                "description": text,
                **{
                    key: _lines("Record " + key.replace("_", " "))
                    for key in ("trade_offs", "verification", "documentation", "risks")
                },
            }
        )
    unavailable = (
        None
        if alternatives
        else _answer("Explain why no viable alternative is currently available")
    )
    impact = {}
    for key, collection, id_key in (
        ("module_ids", "modules", "module_id"),
        ("checkpoint_ids", "checkpoints", "checkpoint_id"),
        ("milestone_ids", "playtest_milestones", "milestone_id"),
    ):
        print("Impacted " + collection.replace("_", " "))
        impact[key] = _links(workflow["payload"][collection], id_key)
    interfaces = {
        item["interface_id"]: item
        for row in workflow["payload"]["modules"]
        for item in reconciler.store.get(ContractRef.from_json(row["module_contract_ref"]))[
            "payload"
        ]["provided_interfaces"]
    }
    impact["interface_ids"] = _links(list(interfaces.values()), "interface_id")
    decisions = list(
        {
            ContractRef.from_json(row["decision_contract_ref"]): row["decision_contract_ref"]
            for row in workflow["payload"]["technology_decisions"]
        }.values()
    )
    print("Impacted technology decisions")
    chosen = _links(
        [{**item, "description": item["contract_id"]} for item in decisions], "contract_id"
    )
    impact["technology_decision_refs"] = [
        item for item in decisions if item["contract_id"] in chosen
    ]
    impact.update(requirement_ids=affected["requirement_ids"], build_ids=[])
    for key in ("regressions", "documentation", "risks", "preserved_items"):
        impact[key] = _lines("Record " + key.replace("_", " "))
    diagnosis = {
        "kind": "STRUCTURAL_CONFLICT",
        "affected_proposals": affected,
        "inconsistencies": [inconsistency],
        "evidence": [evidence],
        "alternatives": {"options": alternatives, "unavailable_reason": unavailable},
        "impact": impact,
    }
    print("COMPLETE STRUCTURAL REQUEST DIAGNOSIS")
    print(render_fields(diagnosis))
    if (
        _answer(
            "Type REQUEST to publish this negotiation request without changing product requirements",
            optional=True,
        )
        != "REQUEST"
    ):
        print("Request publication deferred.")
        return
    result = reconciler.create_revision_request(
        reference, diagnosis, actor_id=actor, request_id=request_id
    )
    print("Published request reference")
    print(render_fields(result.to_json()))
    print(
        "Use corinthos project request "
        + result.contract_id
        + " to review its bounded negotiation."
    )


def run(arguments: argparse.Namespace) -> int:
    try:
        store = ContractStore(arguments.root)
        repository = ExecutionRepository(store)
        actor = local_actor_id()
        action = arguments.runtime_action
        if action == "executions":
            print(render_fields(repository.list()))
            return 0
        if action == "audit-request":
            print(json.dumps(repository.audit_request(arguments.attempt_id), indent=2))
            return 0
        if action in {"configure", "changes", "request"}:
            reference = _exact(repository, arguments.contract_id, arguments.revision)
            if reference is None:
                return 1
            if action == "configure":
                runner = _runner(arguments, store)
                item = (
                    WorkService(arguments.root).get(arguments.work_item)
                    if arguments.work_item is not None
                    else None
                )
                print(
                    render_fields(
                        runner.configure(
                            reference,
                            _specifications(
                                store,
                                reference,
                                formal=arguments.formal_audits,
                                critical=item is not None
                                and item.scope_level is ScopeLevel.CRITICAL,
                            ),
                            actor_id=actor,
                            work_item_id=arguments.work_item,
                        )
                    )
                )
            elif action == "changes":
                print(render_fields(RevisionReconciler(store).inspect(reference)))
            else:
                _structural_request(
                    RevisionReconciler(store), reference, actor, arguments.request_id
                )
            return 0
        execution = _execution(repository, arguments.execution_id)
        if execution is None:
            return 1
        if action == "status":
            print(render_fields(execution))
            for checkpoint in execution["checkpoints"].values():
                if checkpoint["attempt_id"]:
                    print(render_fields(repository.get_attempt(checkpoint["attempt_id"])))
        elif action == "execution-history":
            print(render_fields(repository.history(execution["execution_id"])))
        else:
            runner = _runner(arguments, store)
            if action == "execute":
                attempt = runner.run_next(
                    execution["execution_id"],
                    provider=arguments.provider,
                    timeout=arguments.timeout,
                )
                if attempt is None:
                    print(
                        "No eligible checkpoint was dispatched. Inspect status for completion or blockers."
                    )
                    current = runner.repository.get(execution["execution_id"])
                    print(render_fields(current))
                    return 0 if current["state"] == "COMPLETED" else 1
                else:
                    print(render_fields(attempt))
                    return 0 if attempt["state"] == "COMPLETED" else 1
            elif action == "recover":
                return _recover(runner, execution, arguments.checkpoint_id, actor)
            else:
                reference = _exact(repository, arguments.contract_id, arguments.revision)
                if reference is None:
                    return 1
                impact = RevisionReconciler(store).compare(execution["workflow_ref"], reference)
                print("PROPOSED REVISION IMPACT AND HISTORICAL EVIDENCE PRESERVATION")
                print(render_fields(impact))
                workflow = store.get(reference)
                kept = execution["bindings"]
                bound = kept.get("work_item")
                if (
                    bound is not None
                    and arguments.work_item is not None
                    and arguments.work_item != bound["work_item_id"]
                ):
                    raise IntegrityError(
                        "Reconciliation cannot change a Workflow's Work Item owner."
                    )
                work_item_id = arguments.work_item if bound is None else bound["work_item_id"]
                item = (
                    None if work_item_id is None else WorkService(arguments.root).get(work_item_id)
                )
                critical = item is not None and item.scope_level is ScopeLevel.CRITICAL
                if critical:
                    predecessor = store.get(ContractRef.from_json(execution["workflow_ref"]))
                    remove_predecessor_critical_audits(kept, predecessor, workflow)
                specs = _specifications(
                    store,
                    reference,
                    existing=kept["checkpoints"],
                    formal=arguments.formal_audits,
                    critical=critical,
                )
                bindings = runner.prepare_bindings(reference, specs)
                carried = _carry_completed(
                    execution, workflow, bindings, impact["preserved_checkpoint_ids"]
                )
                if item is not None and (
                    bound is None or work_fingerprint(item) != bound["content_sha256"]
                ):
                    carried = []
                    print("New or changed Work Item bindings require fresh checkpoint evidence.")
                print("EXACT RECONCILIATION DISPOSITION AFTER CONFIGURATION")
                print(
                    render_fields(
                        {
                            "carried_checkpoint_ids": carried,
                            "reset_checkpoint_ids": sorted(
                                set(bindings["checkpoints"]) - set(carried)
                            ),
                            "removed_checkpoint_ids": sorted(
                                set(execution["checkpoints"]) - set(bindings["checkpoints"])
                            ),
                        }
                    )
                )
                reason = _answer("Record the reconciliation reason and any required revalidation")
                print(
                    render_fields(
                        repository.reconcile(
                            execution["execution_id"],
                            execution["version"],
                            reference,
                            bindings,
                            actor_id=actor,
                            preserve_checkpoint_ids=carried,
                            reason=reason,
                            work_item_id=arguments.work_item,
                        )
                    )
                )
        return 0
    except (EOFError, KeyboardInterrupt):
        print(
            "\nInput stopped. Durable execution observations remain saved. Inspect status before recovery."
        )
        return 130
    except ContractError as error:
        print("Execution operation failed. " + safe_text(error), file=sys.stderr)
        return 1
    except OSError:
        print(
            "Execution could not access its authorized local files, process or terminal.",
            file=sys.stderr,
        )
        return 1
