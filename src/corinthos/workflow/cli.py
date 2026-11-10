# SPDX-License-Identifier: MPL-2.0
"""Guided planning questions over the WorkflowPlanner application service."""

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from corinthos.contracts import ContractError, ContractRef, IntegrityError
from corinthos.project_manager.approval import local_actor_id
from corinthos.project_manager.cli import _answer, _criteria, _lines, _linked, _pick
from corinthos.project_manager.presentation import render_fields, safe_text

from .presentation import render_plan_review
from .service import WorkflowPlanner


def configure_parser(commands) -> None:
    workflow = commands.add_parser("workflow", help="Negotiate and publish an engineering plan.")
    workflow.add_argument(
        "--root", type=Path, default=Path.cwd(), help="Authorized project directory."
    )
    actions = workflow.add_subparsers(dest="workflow_action", required=True)
    for name, description in {
        "plan": "Plan from an exact approved Project Contract.",
        "sessions": "List saved planning sessions.",
        "resume": "Continue a saved plan.",
        "show": "Show the complete saved plan and preliminary checks.",
        "review": "Freeze and review the complete publication set.",
        "publish": "Authorize the exact publication set at the local terminal.",
        "defer": "Save the plan for later.",
        "cancel": "Close planning without publication.",
        "history": "Inspect durable accepted planning choices.",
        "revise": "Revise an exact published Workflow Contract.",
    }.items():
        action = actions.add_parser(name, help=description, description=description)
        action.add_argument(
            "--root", type=Path, default=argparse.SUPPRESS, help="Project directory."
        )
        if name in {"plan", "revise"}:
            action.add_argument("contract_id", help="Published logical contract ID.")
            action.add_argument("--revision", help="Exact published revision ID.")
        elif name != "sessions":
            action.add_argument(
                "session_id", nargs="?", help="Saved session ID, or choose from a list."
            )
        if name == "publish":
            action.add_argument(
                "--mandate", help="Existing bounded human mandate ID for a permitted replan."
            )
        action.set_defaults(handler=run)


def _identifier(prefix: str) -> str:
    return prefix + "-" + uuid4().hex


def _label(item: dict) -> str:
    return item.get(
        "description",
        item.get(
            "title",
            item.get("purpose_and_boundaries", {}).get("purpose", item.get("module_id", "")),
        ),
    )


def _links(items: list[dict], key: str, existing=None) -> list[str]:
    return _linked(
        [{**item, "description": _label(item)} for item in items], key, existing=existing
    )


def _record(mapping: dict, describe):
    action = _pick(["Add", "Edit", "Remove", "Back"], str)
    item = None
    if action in {"Edit", "Remove"}:
        item = _pick(list(mapping.values()), describe)
        if item is None:
            return "Back", None
    return action, item


def _criteria_with_ids(existing: list[dict]) -> list[dict]:
    return [
        {"criterion_id": item.get("criterion_id", _identifier("criterion")), **item}
        for item in _criteria(existing)
    ]


def _module(snapshot: dict, project: dict) -> dict | None:
    modules = snapshot["draft"]["modules"]
    action, old = _record(modules, _label)
    if action == "Back":
        return None
    if action == "Remove":
        return {"action": "remove_module", "module_id": old["module_id"]}
    old = old or {}
    boundaries = old.get("purpose_and_boundaries", {})
    updated = {
        "action": "upsert_module",
        "purpose_and_boundaries": {
            "purpose": _answer(
                "What is this module responsible for?", default=boundaries.get("purpose")
            ),
            "responsibilities": _lines(
                "List its responsibilities", existing=boundaries.get("responsibilities")
            ),
            "exclusions": _lines(
                "List responsibilities outside this module", existing=boundaries.get("exclusions")
            ),
        },
    }
    if old:
        updated["module_id"] = old["module_id"]
    print("Project requirements assigned to this module")
    updated["requirement_ids"] = _links(
        project["payload"]["requirements"], "requirement_id", old.get("requirement_ids")
    )
    print("Project constraints applicable to this module")
    constraints = project["payload"]["constraints"]
    updated["constraint_ids"] = _links(
        constraints,
        "constraint_id",
        old.get("constraint_ids", [item["constraint_id"] for item in constraints]),
    )
    updated["constraint_exemptions"] = {
        item["constraint_id"]: _answer(
            "Explain why this constraint does not apply: " + safe_text(item["description"]),
            default=old.get("constraint_exemptions", {}).get(item["constraint_id"]),
        )
        for item in constraints
        if item["constraint_id"] not in updated["constraint_ids"]
    }
    print("Modules this module depends on")
    updated["depends_on"] = _links(
        [item for item in modules.values() if item["module_id"] != old.get("module_id")],
        "module_id",
        old.get("depends_on"),
    )
    return updated


def _provided(module: dict) -> dict | None:
    interfaces = {item["interface_id"]: item for item in module["provided_interfaces"]}
    action, old = _record(
        interfaces, lambda item: item["interface_type"] + " [" + item["interface_id"] + "]"
    )
    if action == "Back":
        return None
    if action == "Remove":
        del interfaces[old["interface_id"]]
    else:
        updated = {
            "interface_id": old["interface_id"] if old else _identifier("interface"),
            "interface_revision": old["interface_revision"]
            if old
            else _identifier("interface-revision"),
            "interface_type": _answer(
                "What kind of interface is this? For example, a function or file format",
                default=old.get("interface_type") if old else None,
            ),
        }
        for field, question in {
            "inputs": "Describe the accepted inputs",
            "outputs": "Describe the produced outputs",
            "errors": "Describe error behavior",
            "side_effects": "Describe side effects",
            "behavioral_guarantees": "Describe behavioral guarantees",
        }.items():
            updated[field] = _lines(question, existing=old.get(field) if old else None)
        if old and updated != old:
            updated["interface_revision"] = _identifier("interface-revision")
            print("Changed interface terms receive a new revision for explicit review.")
        interfaces[updated["interface_id"]] = updated
    return {
        "action": "set_provided_interfaces",
        "module_id": module["module_id"],
        "interfaces": list(interfaces.values()),
    }


def _consumed(snapshot: dict, module: dict) -> dict | None:
    current = deepcopy(module["consumed_interfaces"])
    action = _pick(["Add exact provider link", "Remove provider link", "Back"], str)
    if action == "Back":
        return None
    if action == "Remove provider link":
        item = _pick(
            current, lambda value: value["provider_module_id"] + " / " + value["interface_id"]
        )
        if item is None:
            return None
        current.remove(item)
    else:
        choices = [
            {
                "provider_module_id": provider["module_id"],
                "interface_id": interface["interface_id"],
                "required_interface_revision": interface["interface_revision"],
                "description": _label(provider) + " / " + interface["interface_type"],
            }
            for provider in snapshot["draft"]["modules"].values()
            if provider["module_id"] != module["module_id"]
            for interface in provider["provided_interfaces"]
        ]
        chosen = _pick(
            choices,
            lambda item: item["description"] + " [" + item["required_interface_revision"] + "]",
        )
        if chosen is None:
            return None
        current.append({key: value for key, value in chosen.items() if key != "description"})
    return {
        "action": "set_consumed_interfaces",
        "module_id": module["module_id"],
        "interfaces": current,
    }


def _verification(module: dict) -> dict | None:
    spec = deepcopy(module["verification_spec"])
    print("VISIBLE VERIFICATION PLAN")
    print(render_fields(spec))
    action = _pick(
        [
            "Edit a blocking check",
            "Edit evidence expectations",
            "Regenerate source-derived suggestions",
            "Back",
        ],
        str,
    )
    if action == "Back":
        return None
    if action == "Regenerate source-derived suggestions":
        return {"action": "reset_verification", "module_id": module["module_id"]}
    if action == "Edit evidence expectations":
        spec["evidence_expectations"] = _lines(
            "Describe the evidence the module must retain", existing=spec["evidence_expectations"]
        )
    else:
        checks = [
            check
            for field in (
                "requirement_checks",
                "constraint_checks",
                "interface_checks",
                "quality_checks",
            )
            for check in spec[field]
        ]
        check = _pick(checks, lambda item: item["criterion"] + " [" + item["check_id"] + "]")
        if check is None:
            return None
        check["criterion"] = _answer(
            "What observable condition must hold?", default=check["criterion"]
        )
        check["verification_methods"] = _lines(
            "How will this be checked?", existing=check["verification_methods"]
        )
        check["evidence_required"] = _lines(
            "What concrete evidence is required?", existing=check["evidence_required"]
        )
        check["blocking"] = True
    return {
        "action": "set_verification",
        "module_id": module["module_id"],
        "verification_spec": spec,
    }


def _recommendations(existing: list[dict]) -> list[dict]:
    options = {item["option_id"]: deepcopy(item) for item in existing}
    while True:
        print("EVALUATED RECOMMENDATIONS")
        print(render_fields(list(options.values())))
        action, old = _record(options, lambda item: str(item["rank"]) + ". " + item["technology"])
        if action == "Back":
            return sorted(options.values(), key=lambda item: item["rank"])
        if action == "Remove":
            del options[old["option_id"]]
            continue
        if action == "Add" and len(options) >= 5:
            print("A decision supports at most five genuinely viable recommendations.")
            continue
        old = old or {}
        item = {
            "option_id": old.get("option_id", _identifier("option")),
            "technology": _answer("Name the evaluated technology", default=old.get("technology")),
            "rank": _pick([1, 2, 3, 4, 5], str, "Choose its suitability rank"),
            "suitability_rationale": _answer(
                "Why is this option suitable?", default=old.get("suitability_rationale")
            ),
        }
        for field in ("advantages", "limitations", "risks", "compatibility_notes"):
            item[field] = _lines("Describe " + field.replace("_", " "), existing=old.get(field))
        options[item["option_id"]] = item


def _technology(snapshot: dict, project: dict) -> dict | None:
    decisions = snapshot["draft"]["decisions"]
    action = _pick(
        [
            "Add or refine evaluated recommendations",
            "Select a technology",
            "Remove a decision",
            "Back",
        ],
        str,
    )
    old = None
    if action in {"Select a technology", "Remove a decision"}:
        old = _pick(
            list(decisions.values()), lambda item: item["payload"]["decision_scope"]["subject"]
        )
        if old is None:
            return None
    if action == "Back":
        return None
    if action == "Remove a decision":
        return {"action": "remove_technology", "decision_id": old["decision_id"]}
    if action == "Select a technology":
        print(render_fields(old))
        source = _pick(
            ["Choose an evaluated recommendation", "Propose another option", "Leave undecided"], str
        )
        if source == "Leave undecided":
            return None
        if source == "Choose an evaluated recommendation":
            option = _pick(
                old["payload"]["ai_recommendations"],
                lambda item: str(item["rank"]) + ". " + item["technology"],
            )
            if option is None:
                return None
            selection = {"source": "RECOMMENDED", "option_id": option["option_id"]}
        else:
            selection = {
                "source": "HUMAN",
                "technology": _answer("Which technology do you propose?"),
                "feasibility_rationale": _answer(
                    "Evaluate its feasibility against the same constraints"
                ),
            }
        return {
            "action": "select_technology",
            "decision_id": old["decision_id"],
            "selected_option": selection,
            "decision_rationale": _answer(
                "Record your selection rationale. Exact publication approval follows later"
            ),
        }
    if (
        decisions
        and _pick(["New decision", "Refine existing decision"], str) == "Refine existing decision"
    ):
        old = _pick(
            list(decisions.values()), lambda item: item["payload"]["decision_scope"]["subject"]
        )
    payload = deepcopy(old["payload"]) if old else {}
    prior_scope = payload.get("decision_scope", {})
    payload["decision_scope"] = {
        "subject": _answer(
            "Which technology decision is needed?", default=prior_scope.get("subject")
        ),
        "objective": _answer(
            "What must this decision achieve?", default=prior_scope.get("objective")
        ),
    }
    print("Modules in this decision's scope")
    payload["decision_scope"]["module_ids"] = _links(
        list(snapshot["draft"]["modules"].values()), "module_id", prior_scope.get("module_ids")
    )
    obligations = [
        {"obligation_id": item[key], "description": item.get("description", item.get("criterion"))}
        for field, key in (
            ("requirements", "requirement_id"),
            ("constraints", "constraint_id"),
            ("success_criteria", "criterion_id"),
        )
        for item in project["payload"][field]
    ]
    prior_drivers = payload.get("decision_drivers", {})
    driver_ids = _links(
        obligations,
        "obligation_id",
        [item["obligation_id"] for item in prior_drivers.get("source_refs", [])],
    )
    payload["decision_drivers"] = {
        "source_refs": [
            {"contract_ref": snapshot["project_ref"], "obligation_id": identifier}
            for identifier in driver_ids
        ],
        "factors": _lines("Describe decision drivers", existing=prior_drivers.get("factors")),
    }
    if old:
        print(
            "Original recommendations and ranking are retained. Use Select a technology to evaluate another option."
        )
        print(render_fields(payload["ai_recommendations"]))
    else:
        payload["ai_recommendations"] = _recommendations([])
    payload["selected_option"] = None
    payload["decision_rationale"] = _answer(
        "Record the evaluation rationale", default=payload.get("decision_rationale")
    )
    payload["compatibility_requirements"] = _lines(
        "Describe compatibility requirements", existing=payload.get("compatibility_requirements")
    )
    payload["verification_criteria"] = _criteria_with_ids(payload.get("verification_criteria", []))
    operation = {"action": "upsert_technology", "payload": payload}
    if old:
        operation["decision_id"] = old["decision_id"]
    return operation


def _checkpoint(snapshot: dict, project: dict) -> dict | None:
    checkpoints = snapshot["draft"]["checkpoints"]
    action, old = _record(checkpoints, _label)
    if action == "Back":
        return None
    if action == "Remove":
        return {"action": "remove_checkpoint", "checkpoint_id": old["checkpoint_id"]}
    old = old or {}
    point = {
        "checkpoint_id": old.get("checkpoint_id", _identifier("checkpoint")),
        "title": _answer("Give this checkpoint a title", default=old.get("title")),
        "objective": _answer("Describe its bounded objective", default=old.get("objective")),
    }
    print("Modules addressed by this checkpoint")
    point["module_ids"] = _links(
        list(snapshot["draft"]["modules"].values()), "module_id", old.get("module_ids")
    )
    print("Requirements addressed by this checkpoint")
    point["requirement_ids"] = _links(
        project["payload"]["requirements"], "requirement_id", old.get("requirement_ids")
    )
    print("Prerequisite checkpoints")
    point["depends_on"] = _links(
        [item for item in checkpoints.values() if item["checkpoint_id"] != point["checkpoint_id"]],
        "checkpoint_id",
        old.get("depends_on"),
    )
    point["deliverables"] = _lines(
        "List concrete code, test or documentation deliverables", existing=old.get("deliverables")
    )
    point["completion_criteria"] = _criteria_with_ids(old.get("completion_criteria", []))
    point["verification_plan"] = _lines(
        "Describe how each deliverable and criterion will be verified",
        existing=old.get("verification_plan"),
    )
    return {"action": "upsert_checkpoint", "checkpoint": point}


def _milestone(snapshot: dict) -> dict | None:
    milestones = snapshot["draft"]["playtest_milestones"]
    print(
        "Milestones describe optional cumulative test plans. An empty milestone list is supported."
    )
    action, old = _record(milestones, _label)
    if action == "Back":
        return None
    if action == "Remove":
        return {"action": "remove_milestone", "milestone_id": old["milestone_id"]}
    old = old or {}
    milestone = {
        "milestone_id": old.get("milestone_id", _identifier("milestone")),
        "title": _answer("Give this milestone a title", default=old.get("title")),
        "objective": _answer(
            "What cumulative test scope should it support?", default=old.get("objective")
        ),
    }
    print("Prerequisite milestones")
    milestone["depends_on"] = _links(
        [item for item in milestones.values() if item["milestone_id"] != milestone["milestone_id"]],
        "milestone_id",
        old.get("depends_on"),
    )
    print("Required checkpoints")
    milestone["required_checkpoint_ids"] = _links(
        list(snapshot["draft"]["checkpoints"].values()),
        "checkpoint_id",
        old.get("required_checkpoint_ids"),
    )
    prior_scope = old.get("test_scope", {})
    milestone["test_scope"] = {
        field: _lines("Describe " + field + " test scope", existing=prior_scope.get(field))
        for field in ("included", "excluded")
    }
    milestone["test_scenarios"] = _lines(
        "Describe actual test scenarios, including relevant regressions",
        existing=old.get("test_scenarios"),
    )
    milestone["readiness_criteria"] = _criteria_with_ids(old.get("readiness_criteria", []))
    return {"action": "upsert_milestone", "milestone": milestone}


def _show(planner: WorkflowPlanner, snapshot: dict) -> None:
    print("SAVED ENGINEERING PLAN")
    print(render_fields({key: value for key, value in snapshot.items() if key != "review"}))
    print("PRELIMINARY PLANNING ASSESSMENT")
    print(render_fields(planner.assess(snapshot["session_id"])))


def _review(planner: WorkflowPlanner, snapshot: dict, actor: str) -> dict:
    assessment = planner.assess(snapshot["session_id"])
    print(render_fields(assessment))
    snapshot = planner.review(snapshot["session_id"], snapshot["version"], actor_id=actor)
    previous = [
        planner.store.get(ContractRef.from_json(item["metadata"]["supersedes"]))
        for item in snapshot["review"]["documents"]
        if item["metadata"]["supersedes"]
    ]
    if any(item is None for item in previous):
        raise IntegrityError("An exact predecessor is unavailable for review.")
    print(
        render_plan_review(
            snapshot,
            previous=previous,
            warnings=assessment.get("issues", []) + assessment.get("unknowns", []),
        )
    )
    return snapshot


def _publish(planner: WorkflowPlanner, snapshot: dict, mandate_id: str | None = None) -> dict:
    from .authorization import authorize_interactively, publish_delegated

    result = (
        publish_delegated(planner, snapshot["session_id"], snapshot["version"], mandate_id)
        if mandate_id is not None
        else authorize_interactively(planner, snapshot["session_id"], snapshot["version"])
    )
    print("Planning state " + safe_text(result["state"]))
    if result["published_refs"]:
        print("Exact published plan references")
        print(render_fields(result["published_refs"]))
    return result


def _conversation(planner: WorkflowPlanner, snapshot: dict, actor: str) -> None:
    print("Accepted planning choices are saved. Session " + safe_text(snapshot["session_id"]))
    print("This editor plans obligations. Checkpoint execution requires a later authorized step.")
    if snapshot.get("mandate_id"):
        print("Available inherited bounded mandate " + safe_text(snapshot["mandate_id"]))
    while snapshot["state"] not in {"PUBLISHED", "CANCELLED"}:
        choice = _pick(
            [
                "Modules and responsibilities",
                "Technology decisions",
                "Provider interfaces",
                "Consumer interfaces",
                "Module technology links",
                "Verification requirements",
                "Checkpoints",
                "Playtest milestone plans",
                "Show complete plan",
                "Review complete publication set",
                "Authorize and publish at the local terminal",
                "Save for later and leave",
                "Show history",
                "Cancel planning",
                "Publish using inherited bounded mandate",
            ],
            str,
        )
        operation = None
        try:
            project = planner.store.get(ContractRef.from_json(snapshot["project_ref"]))
            if project is None:
                raise IntegrityError("The exact approved Project Contract is unavailable.")
            if choice == "Modules and responsibilities":
                operation = _module(snapshot, project)
            elif choice == "Technology decisions":
                operation = _technology(snapshot, project)
            elif choice in {
                "Provider interfaces",
                "Consumer interfaces",
                "Module technology links",
                "Verification requirements",
            }:
                module = _pick(list(snapshot["draft"]["modules"].values()), _label)
                if module is not None:
                    if choice == "Provider interfaces":
                        operation = _provided(module)
                    elif choice == "Consumer interfaces":
                        operation = _consumed(snapshot, module)
                    elif choice == "Verification requirements":
                        operation = _verification(module)
                    else:
                        decisions = [
                            {
                                "decision_id": item["decision_id"],
                                "description": item["payload"]["decision_scope"]["subject"],
                            }
                            for item in snapshot["draft"]["decisions"].values()
                        ]
                        operation = {
                            "action": "set_module_technology",
                            "module_id": module["module_id"],
                            "decision_ids": _links(
                                decisions, "decision_id", module["technology_decision_ids"]
                            ),
                        }
            elif choice == "Checkpoints":
                operation = _checkpoint(snapshot, project)
            elif choice == "Playtest milestone plans":
                operation = _milestone(snapshot)
            elif choice == "Show complete plan":
                _show(planner, snapshot)
            elif choice == "Review complete publication set":
                snapshot = _review(planner, snapshot, actor)
            elif choice == "Authorize and publish at the local terminal":
                snapshot = _publish(planner, snapshot)
            elif choice == "Save for later and leave":
                snapshot = planner.defer(
                    snapshot["session_id"], snapshot["version"], actor_id=actor
                )
                break
            elif choice == "Show history":
                print(render_fields(planner.history(snapshot["session_id"])))
            elif choice == "Cancel planning":
                if _answer("Type CANCEL to close this planning session", optional=True) == "CANCEL":
                    snapshot = planner.cancel(
                        snapshot["session_id"], snapshot["version"], actor_id=actor
                    )
                    break
            elif choice == "Publish using inherited bounded mandate":
                if snapshot.get("mandate_id"):
                    snapshot = _publish(planner, snapshot, snapshot["mandate_id"])
                else:
                    print(
                        "This session has no inherited bounded mandate. Explicit human authorization is available separately."
                    )
            if operation:
                snapshot = planner.edit(
                    snapshot["session_id"], snapshot["version"], operation, actor_id=actor
                )
                print("Saved.")
        except ContractError as error:
            print("Planning choice could not be completed. " + safe_text(error), file=sys.stderr)
            snapshot = planner.get(snapshot["session_id"])
    print("Planning state " + safe_text(snapshot["state"]))
    print("Resume with corinthos workflow resume " + safe_text(snapshot["session_id"]))


def _exact(planner: WorkflowPlanner, contract_id: str, revision: str | None) -> ContractRef | None:
    documents = planner.store.list_revisions(contract_id)
    if revision:
        documents = [item for item in documents if item["metadata"]["revision_id"] == revision]
    chosen = _pick(
        documents,
        lambda item: (
            "Version " + str(item["metadata"]["version"]) + " " + item["metadata"]["revision_id"]
        ),
        "Choose the exact published revision",
    )
    return ContractRef.from_document(chosen) if chosen else None


def run(arguments: argparse.Namespace) -> int:
    try:
        planner = WorkflowPlanner(arguments.root)
        actor = local_actor_id()
        action = arguments.workflow_action
        if action == "sessions":
            print(render_fields(planner.list()))
            return 0
        if action in {"plan", "revise"}:
            reference = _exact(planner, arguments.contract_id, arguments.revision)
            if reference is None:
                return 1
            snapshot = (
                planner.start(reference, actor_id=actor)
                if action == "plan"
                else planner.revise(
                    reference, _answer("Why should the published plan change?"), actor_id=actor
                )
            )
            _conversation(planner, snapshot, actor)
            return 0
        snapshot = (
            planner.get(arguments.session_id)
            if arguments.session_id
            else _pick(planner.list(), lambda item: item["session_id"] + " [" + item["state"] + "]")
        )
        if snapshot is None:
            return 1
        if action == "resume":
            _conversation(planner, snapshot, actor)
        elif action == "show":
            _show(planner, snapshot)
        elif action == "review":
            _review(planner, snapshot, actor)
        elif action == "publish":
            _publish(planner, snapshot, arguments.mandate)
        elif action == "history":
            print(render_fields(planner.history(snapshot["session_id"])))
        else:
            transition = planner.defer if action == "defer" else planner.cancel
            print(
                render_fields(
                    transition(snapshot["session_id"], snapshot["version"], actor_id=actor)
                )
            )
        return 0
    except (EOFError, KeyboardInterrupt):
        print(
            "\nInput stopped. Accepted planning choices are saved. Use corinthos workflow resume to continue."
        )
        return 130
    except ContractError as error:
        print("Planning operation failed. " + safe_text(error), file=sys.stderr)
        return 1
    except OSError:
        print("Planning operation could not access its local files or terminal.", file=sys.stderr)
        return 1
