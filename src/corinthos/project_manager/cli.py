# SPDX-License-Identifier: MPL-2.0
"""Thin terminal questions and navigation over the Project Manager service."""

import argparse
import sys
from pathlib import Path

from corinthos.contracts import ContractError, ContractRef, IntegrityError

from .approval import local_actor_id
from .navigation import Back, SaveAndExit
from .navigation import answer as _answer
from .navigation import choose as _choose
from .navigation import lines as _lines
from .navigation import pick as _pick
from .presentation import render_completion, render_fields, render_review, safe_text
from .service import ProjectManager

_CLOSED = {"PUBLISHED", "CANCELLED", "CLOSED_UNCHANGED", "RETURNED"}


def configure_parser(parser: argparse.ArgumentParser):
    commands = parser.add_subparsers(dest="command")
    project = commands.add_parser("project", help="Create, negotiate and review a project.")
    project.add_argument(
        "--root", type=Path, default=Path.cwd(), help="Authorized project directory."
    )
    actions = project.add_subparsers(dest="project_action", required=True)
    for name, description in {
        "start": "Describe a new idea and choose how to define the project.",
        "sessions": "List saved negotiation sessions.",
        "resume": "Continue a saved session.",
        "show": "Show the complete saved draft and pending choices.",
        "review": "Freeze and display a complete candidate for review.",
        "approve": "Review and explicitly approve at the local terminal.",
        "defer": "Save a session for later without publishing.",
        "cancel": "Cancel negotiation without publishing a revision.",
        "history": "Show accepted turns and decisions.",
        "revise": "Negotiate a change to a published Project Contract.",
        "request": "Review a published Project Revision Request.",
        "advise": "Explicitly request native advisory assistance for one saved session.",
    }.items():
        action = actions.add_parser(name, help=description, description=description)
        action.add_argument(
            "--root", type=Path, default=argparse.SUPPRESS, help="Project directory."
        )
        if name in {"revise", "request"}:
            action.add_argument("contract_id", help="Published logical contract ID.")
            action.add_argument("--revision", help="Exact published revision ID.")
        elif name not in {"start", "sessions"}:
            action.add_argument(
                "session_id", nargs="?", help="Saved session ID, or select from a list."
            )
        if name == "advise":
            action.add_argument("--provider", required=True, choices=("codex", "claude"))
            action.add_argument("--timeout", type=float, default=60)
            action.add_argument("--operation", help="Stable advice operation ID for safe retries.")
        action.set_defaults(handler=run)
    product = actions.add_parser(
        "product-review", help="Optionally review one exact delivered version."
    )
    product.add_argument("--root", type=Path, default=argparse.SUPPRESS)
    review_actions = product.add_subparsers(dest="product_review_action", required=True)
    for name in ("start", "list", "show", "freeze", "approve", "defer"):
        action = review_actions.add_parser(name)
        action.add_argument("--root", type=Path, default=argparse.SUPPRESS)
        if name == "start":
            action.add_argument("version_id")
            action.add_argument(
                "--decision", required=True, choices=("ACCEPTED", "WITH_RESERVATIONS")
            )
            action.add_argument("--observation", action="append", default=[])
        elif name == "list":
            action.add_argument("project_id")
        else:
            action.add_argument("review_id")
        action.set_defaults(handler=run_product_review)
    return commands


def _linked(items: list[dict], id_key: str, *, existing: list[str] | None = None) -> list[str]:
    if not items:
        return []
    for index, item in enumerate(items, 1):
        print(
            f"{index}. {safe_text(item.get('description', item.get('criterion', '')))} "
            f"[{safe_text(item[id_key])}]"
        )
    choices = {str(i): item[id_key] for i, item in enumerate(items, 1)}
    default = ",".join(key for key, value in choices.items() if value in (existing or []))
    while True:
        answer = _answer(
            "Link item numbers separated by commas. Enter /clear for no links", default=default
        )
        if not answer or answer == "/clear":
            return []
        selected = [item.strip() for item in answer.split(",")]
        if all(item in choices for item in selected):
            return list(dict.fromkeys(choices[item] for item in selected))
        print("Use the displayed numbers separated by commas.")


def _criteria(existing: list[dict]) -> list[dict]:
    criteria = []
    for current in existing:
        answer = _answer(
            "Acceptance criterion. Enter /remove to remove this criterion",
            default=current["criterion"],
        )
        if answer != "/remove":
            criteria.append({**current, "criterion": answer})
    for text in _lines("Describe observable acceptance criteria"):
        criteria.append({"criterion": text})
    return criteria


def _edit_item(
    snapshot: dict, collection: str, choice: str | None = None, *, guided=False
) -> dict | None:
    items = snapshot["payload"][collection]
    if choice is None:
        choice = _pick(["Add", "Edit", "Remove"], str)
    if choice is None:
        return None
    selected = None
    if choice != "Add":
        selected = _pick(items, lambda item: item.get("description", item.get("criterion", "")))
        if selected is None:
            return None
    names = {
        "requirements": ("requirement", "requirement_id", "description"),
        "constraints": ("constraint", "constraint_id", "description"),
        "success_criteria": ("success_criterion", "criterion_id", "criterion"),
    }
    name, id_key, text_key = names[collection]
    operation = {"action": ("remove_" if choice == "Remove" else "upsert_") + name}
    if selected:
        operation[id_key] = selected[id_key]
    if choice != "Remove":
        operation[text_key] = _answer(
            "Describe the " + name.replace("_", " "),
            default=selected[text_key] if selected else None,
        )
        if collection == "requirements":
            operation["acceptance_criteria"] = _criteria(
                selected["acceptance_criteria"] if selected else []
            )
            if guided and not operation["acceptance_criteria"]:
                print("Give the requirement at least one observable acceptance criterion.")
                return None
    return operation


def _proposal(snapshot: dict) -> dict | None:
    choice = _pick(["Add proposal", "Refine or classify a proposal", "Record a decision"], str)
    if choice is None:
        return None
    existing = None
    if choice != "Add proposal":
        existing = _pick(
            list(snapshot["proposals"].values()),
            lambda entry: entry["proposal"]["description"] + " [" + entry["status"] + "]",
        )
        if existing is None:
            return None
    if choice == "Record a decision":
        print(
            "Negotiation choices concern the draft. Publication needs separate explicit approval."
        )
        status = _pick(["ACCEPTED", "REJECTED", "WITHDRAWN", "NEEDS_CLARIFICATION"], str)
        if status is None:
            return None
        return {
            "action": "decide_proposal",
            "proposal_id": existing["proposal"]["proposal_id"],
            "status": status,
            "decision": _answer("Record your decision"),
            "rationale": _answer("Why did you choose this?"),
        }
    prior = existing["proposal"] if existing else {}
    kind = _pick(
        ["SUGGESTION", "REQUIREMENT"],
        lambda value: value + (" (negotiable)" if value == "SUGGESTION" else " (binding demand)"),
    )
    if kind is None:
        return None
    operation = {
        "action": "propose",
        "kind": kind,
        "description": _answer(
            "Describe the product-level proposal", default=prior.get("description")
        ),
        "scope": _answer(
            "Which product scope does this concern?",
            default=existing.get("scope", "Whole project") if existing else "Whole project",
        ),
    }
    if existing:
        operation["proposal_id"] = prior["proposal_id"]
    print("Related requirements")
    operation["requirement_ids"] = _linked(
        snapshot["payload"]["requirements"], "requirement_id", existing=prior.get("requirement_ids")
    )
    print("Related constraints")
    operation["constraint_ids"] = _linked(
        snapshot["payload"]["constraints"], "constraint_id", existing=prior.get("constraint_ids")
    )
    operation["alternatives"] = _lines(
        "Enter actual alternatives you want considered",
        existing=existing.get("alternatives") if existing else None,
    )
    return operation


def _clarification(snapshot: dict) -> dict | None:
    choice = _pick(
        ["Ask a question", "Answer a question", "Record feasibility evidence or an assumption"], str
    )
    if choice is None:
        return None
    if choice == "Ask a question":
        return {"action": "set_question", "text": _answer("What needs clarification?")}
    if choice == "Answer a question":
        question = _pick(snapshot["questions"], lambda item: item["text"])
        if question:
            return {
                "action": "set_question",
                "question_id": question["question_id"],
                "text": question["text"],
                "answer": _answer("Record your answer"),
            }
        return None
    print(
        "Feasibility records describe supplied evidence. They do not validate implemented software."
    )
    description = _answer("What is being assessed?")
    status = _pick(["NOT_VERIFIED", "ASSUMPTION", "CONFIRMED"], str)
    if status is None:
        return None
    return {
        "action": "record_feasibility",
        "description": description,
        "status": status,
        "evidence": _lines("Record the actual evidence or its local reference"),
    }


def _show(manager: ProjectManager, snapshot: dict) -> None:
    print("SAVED NEGOTIATION")
    print(render_fields({key: value for key, value in snapshot.items() if key != "review"}))
    print("PRELIMINARY ASSESSMENT")
    print(render_fields(manager.assess(snapshot["session_id"], include_assistance=False)))
    if snapshot["source_prr"]:
        _show_request(manager, snapshot["source_prr"])


def _show_request(manager: ProjectManager, reference: dict | ContractRef) -> None:
    exact = reference if isinstance(reference, ContractRef) else ContractRef.from_json(reference)
    document = manager.store.get(exact)
    if document is None:
        raise IntegrityError("The source revision request is unavailable.")
    print("SOURCE PROJECT REVISION REQUEST")
    print(render_fields(document))


def _review(manager: ProjectManager, snapshot: dict, actor: str) -> dict:
    if snapshot["source_prr"]:
        _show_request(manager, snapshot["source_prr"])
    assessment = manager.assess(snapshot["session_id"], include_assistance=False)
    if assessment["issues"]:
        print("Resolve these issues before requesting a complete approval review.")
        print(render_fields(assessment["issues"]))
    snapshot = manager.review(snapshot["session_id"], snapshot["version"], actor_id=actor)
    frozen = snapshot["review"]
    base = (
        manager.store.get(ContractRef.from_json(snapshot["base_ref"]))
        if snapshot["base_ref"]
        else None
    )
    print(
        render_review(
            frozen["document"],
            base_document=base,
            sha256=frozen["sha256"],
            expires_at=frozen["expires_at"],
            warnings=assessment["issues"] + assessment["unknowns"],
        )
    )
    return snapshot


def _approve(manager: ProjectManager, snapshot: dict) -> dict:
    from .approval import approve_interactively

    result = approve_interactively(manager, snapshot["session_id"], snapshot["version"])
    if result["published_ref"]:
        print("Published Project Contract")
        print(render_fields(result["published_ref"]))
    else:
        print("Approval was deferred. The draft is saved.")
    return result


def _completion(manager: ProjectManager, snapshot: dict) -> None:
    bar = render_completion(manager.completion(snapshot))
    try:
        print(bar)
    except UnicodeEncodeError:
        print(bar.replace("█", "#").replace("░", "-"))


def _apply(manager: ProjectManager, snapshot: dict, operation: dict, actor: str) -> dict:
    snapshot = manager.edit(snapshot["session_id"], snapshot["version"], operation, actor_id=actor)
    print("Saved.")
    _completion(manager, snapshot)
    return snapshot


def _operation_failed(manager: ProjectManager, snapshot: dict, error: ContractError) -> dict:
    print("The operation could not be completed. " + safe_text(error), file=sys.stderr)
    return manager.get(snapshot["session_id"])


def _vision(snapshot: dict) -> dict | None:
    current = snapshot["payload"]["vision"]
    text = _answer("Describe the project idea", default=current)
    if text != current:
        return {"action": "set_vision", "text": text}
    return None


def _scope(snapshot: dict, section: str) -> dict | None:
    current = snapshot["payload"]["scope"][section]
    items = _lines(
        "What should the first version include?"
        if section == "included"
        else "Describe " + section,
        existing=current,
    )
    if items != current:
        return {"action": "set_scope", "section": section, "items": items}
    return None


def _guided_items(manager, snapshot, actor, collection, label, *, gaps):
    while True:
        current = snapshot["payload"][collection]
        for item in current:
            print("  " + safe_text(item.get("description", item.get("criterion"))))
            for criterion in item.get("acceptance_criteria", []):
                print("    Verify: " + safe_text(criterion["criterion"]))
        print(f"1. Add {label}")
        print("2. Continue to the next step")
        choices = {"1": "Add", "2": "Continue"}
        if current:
            print(f"3. Edit {label}")
            print(f"4. Remove {label}")
            choices.update({"3": "Edit", "4": "Remove"})
        choice = _choose(choices)
        if choice is None:
            return snapshot, False
        if choice == "Continue":
            return snapshot, True
        try:
            operation = _edit_item(snapshot, collection, choice, guided=True)
            if operation:
                snapshot = _apply(manager, snapshot, operation, actor)
                if gaps and manager.specification_progress(snapshot)[collection]:
                    return snapshot, True
        except Back:
            continue
        except ContractError as error:
            snapshot = _operation_failed(manager, snapshot, error)


def _guided(manager: ProjectManager, snapshot: dict, actor: str, *, gaps=False) -> dict:
    steps = (
        ("vision", "PROJECT IDEA", None),
        ("included", "INCLUDED SCOPE", None),
        ("requirements", "REQUIREMENTS AND ACCEPTANCE CRITERIA", "a requirement"),
        ("constraints", "CONSTRAINTS (OPTIONAL)", "a constraint"),
        ("success_criteria", "PROJECT SUCCESS CRITERIA", "a success criterion"),
    )
    for number, (field, heading, label) in enumerate(steps, 1):
        if gaps and (field == "constraints" or manager.specification_progress(snapshot)[field]):
            continue
        if snapshot["source_prr"] and field in {"vision", "included"}:
            continue
        print(f"\nSTEP {number}/{len(steps)} - {heading}")
        try:
            if field == "vision":
                operation = _vision(snapshot)
            elif field == "included":
                operation = _scope(snapshot, field)
            else:
                snapshot, advance = _guided_items(manager, snapshot, actor, field, label, gaps=gaps)
                if not advance:
                    break
                operation = None
            if operation:
                snapshot = _apply(manager, snapshot, operation, actor)
            else:
                _completion(manager, snapshot)
        except Back:
            break
        except ContractError as error:
            snapshot = _operation_failed(manager, snapshot, error)
            break
    issues = manager.structural_issues(snapshot)
    if issues:
        print("Still needed for complete review")
        for issue in issues:
            print("  " + safe_text(issue))
    return snapshot


def _advanced_menu(snapshot: dict) -> str | None:
    print("\nADVANCED PROJECT CONFIGURATION")
    print(
        "Specification\n"
        "1. Project idea\n"
        "2. Scope, assumptions and risks\n"
        "3. Requirements and acceptance criteria\n"
        "4. Constraints\n"
        "5. Success criteria\n"
        "Analysis and decisions\n"
        "6. Suggestions and binding requirements\n"
        "7. Questions and feasibility\n"
        "Inspection\n"
        "8. Show complete draft\n"
        "9. History\n"
        "Lifecycle\n"
        "10. Review complete contract\n"
        "11. Approve at the local terminal\n"
        "12. Save and exit"
    )
    choices = {str(number): str(number) for number in range(1, 15) if number != 13}
    if snapshot["base_ref"]:
        print("13. Keep existing specification")
        choices["13"] = "13"
    print("14. Cancel negotiation")
    return _choose(choices)


def _advanced(manager: ProjectManager, snapshot: dict, actor: str) -> dict:
    while snapshot["state"] not in _CLOSED:
        choice = _advanced_menu(snapshot)
        operation = None
        try:
            if choice is None:
                return snapshot
            if choice == "1":
                operation = _vision(snapshot)
            elif choice == "2":
                section = _pick(["included", "excluded", "assumptions", "risks"], str)
                if section:
                    operation = _scope(snapshot, section)
            elif choice in {"3", "4", "5"}:
                collection = {"3": "requirements", "4": "constraints", "5": "success_criteria"}
                operation = _edit_item(snapshot, collection[choice])
            elif choice == "6":
                operation = _proposal(snapshot)
            elif choice == "7":
                operation = _clarification(snapshot)
            elif choice == "8":
                _show(manager, snapshot)
            elif choice == "9":
                print(render_fields(manager.history(snapshot["session_id"])))
            elif choice == "10":
                snapshot = _review(manager, snapshot, actor)
            elif choice == "11":
                snapshot = _approve(manager, snapshot)
            elif choice == "12":
                raise SaveAndExit
            elif choice == "13":
                return manager.keep(snapshot["session_id"], snapshot["version"], actor_id=actor)
            elif choice == "14":
                if _answer("Type CANCEL to close this negotiation", optional=True) == "CANCEL":
                    return manager.cancel(
                        snapshot["session_id"], snapshot["version"], actor_id=actor
                    )
            if operation:
                snapshot = _apply(manager, snapshot, operation, actor)
        except Back:
            continue
        except ContractError as error:
            snapshot = _operation_failed(manager, snapshot, error)
    return snapshot


def _draft_review(manager: ProjectManager, snapshot: dict, actor: str) -> dict:
    _show(manager, snapshot)
    _completion(manager, snapshot)
    while snapshot["state"] not in _CLOSED:
        choice = _pick(["Review complete contract", "Approve at the local terminal"], str)
        if choice is None:
            break
        try:
            if choice == "Review complete contract":
                snapshot = _review(manager, snapshot, actor)
            else:
                snapshot = _approve(manager, snapshot)
                if snapshot["state"] == "DEFERRED":
                    break
        except ContractError as error:
            snapshot = _operation_failed(manager, snapshot, error)
    return snapshot


def _conversation(manager: ProjectManager, snapshot: dict, actor: str) -> None:
    print("Accepted changes are saved locally as you work.")
    session_id = snapshot["session_id"]
    print("Session " + safe_text(session_id))
    try:
        while snapshot["state"] not in _CLOSED:
            print("\nPROJECT\n\nIdea\n  " + safe_text(snapshot["payload"]["vision"]))
            _completion(manager, snapshot)
            print(
                "\nHow would you like to define the project?\n"
                "1. Help me develop the idea\n"
                "   Ask an agent for recommendations, questions and alternatives.\n"
                "2. Guide me through the specification\n"
                "   Define the required information step by step without an agent.\n"
                "3. Configure it manually\n"
                "   Edit individual Project Contract sections.\n"
                "4. Review current draft\n"
                "5. Save and exit"
            )
            choice = _choose({number: number for number in "12345"})
            try:
                if choice == "1":
                    from .authoring_advice import author_with_advice

                    snapshot, route = author_with_advice(
                        manager, snapshot, actor, completion=_completion
                    )
                    if route == "gaps":
                        snapshot = _guided(manager, snapshot, actor, gaps=True)
                    elif route == "manual":
                        snapshot = _advanced(manager, snapshot, actor)
                elif choice == "2":
                    snapshot = _guided(manager, snapshot, actor)
                elif choice == "3":
                    snapshot = _advanced(manager, snapshot, actor)
                elif choice == "4":
                    snapshot = _draft_review(manager, snapshot, actor)
                else:
                    raise SaveAndExit
            except Back:
                snapshot = manager.get(session_id)
            except ContractError as error:
                snapshot = _operation_failed(manager, snapshot, error)
    except SaveAndExit:
        # Accepted edits already persist. Exiting must not clear another terminal's review.
        snapshot = manager.get(session_id)
    print("Session state " + safe_text(snapshot["state"]))
    if snapshot["state"] not in _CLOSED:
        print("Resume with corinthos project resume " + safe_text(session_id))


def _session(manager: ProjectManager, session_id: str | None) -> dict | None:
    if session_id:
        return manager.get(session_id)
    return _pick(
        manager.list(),
        lambda item: f"{item['session_id']} [{item['state']}] " + item["payload"]["vision"],
        save=False,
    )


def _published(
    manager: ProjectManager, contract_id: str, revision: str | None
) -> ContractRef | None:
    documents = manager.store.list_revisions(contract_id)
    if revision:
        documents = [item for item in documents if item["metadata"]["revision_id"] == revision]
    chosen = _pick(
        documents,
        lambda item: f"Version {item['metadata']['version']} " + item["metadata"]["revision_id"],
        "Choose the exact published revision",
        save=False,
    )
    return ContractRef.from_document(chosen) if chosen else None


def run(arguments: argparse.Namespace) -> int:
    try:
        manager = ProjectManager(arguments.root)
        actor = local_actor_id()
        action = arguments.project_action
        if action == "start":
            print("Describe your idea in your own words.")
            snapshot = manager.start(_answer("What would you like to create?"), actor_id=actor)
            _conversation(manager, snapshot, actor)
        elif action == "sessions":
            print(render_fields(manager.list()))
        elif action in {"revise", "request"}:
            reference = _published(manager, arguments.contract_id, arguments.revision)
            if reference is None:
                return 1
            if action == "revise":
                snapshot = manager.revise(
                    reference, _answer("Why should this specification change?"), actor_id=actor
                )
            else:
                _show_request(manager, reference)
                triage = _pick(["STRUCTURAL", "NEEDS_CLARIFICATION", "RETURN"], str, save=False)
                if triage is None:
                    return 0
                snapshot = manager.receive_prr(reference, triage, actor_id=actor)
            _conversation(manager, snapshot, actor)
        else:
            snapshot = _session(manager, arguments.session_id)
            if snapshot is None:
                return 1
            if action == "resume":
                if snapshot["source_prr"]:
                    _show_request(manager, snapshot["source_prr"])
                if snapshot["state"] == "DEFERRED":
                    snapshot = manager.edit(
                        snapshot["session_id"],
                        snapshot["version"],
                        {"action": "resume"},
                        actor_id=actor,
                    )
                _conversation(manager, snapshot, actor)
            elif action == "show":
                _show(manager, snapshot)
            elif action == "review":
                _review(manager, snapshot, actor)
            elif action == "approve":
                _approve(manager, snapshot)
            elif action == "history":
                print(render_fields(manager.history(snapshot["session_id"])))
            elif action == "advise":
                from .advice import advise

                print(
                    render_fields(
                        advise(
                            manager,
                            snapshot["session_id"],
                            provider=arguments.provider,
                            timeout=arguments.timeout,
                            operation_id=arguments.operation,
                        )
                    )
                )
            else:
                operation = manager.defer if action == "defer" else manager.cancel
                snapshot = operation(snapshot["session_id"], snapshot["version"], actor_id=actor)
                print("Session state " + safe_text(snapshot["state"]))
        return 0
    except (Back, SaveAndExit):
        return 0
    except (EOFError, KeyboardInterrupt):
        print(
            "\nInput stopped. Accepted changes are saved. Use corinthos project resume to continue."
        )
        return 130
    except ContractError as error:
        print("Project operation failed. " + safe_text(error), file=sys.stderr)
        return 1
    except OSError:
        print("Project operation could not access its local files or terminal.", file=sys.stderr)
        return 1


def run_product_review(arguments: argparse.Namespace) -> int:
    from .product_review import ProductReviewService

    try:
        service = ProductReviewService(arguments.root)
        actor = local_actor_id()
        action = arguments.product_review_action
        if action == "start":
            result = service.start(
                arguments.version_id,
                decision=arguments.decision,
                observations=arguments.observation,
                actor_id=actor,
            )
        elif action == "list":
            result = service.list(arguments.project_id)
        else:
            record = service.get(arguments.review_id)
            if action == "show":
                result = record
            elif action == "freeze":
                result = service.freeze(arguments.review_id, record["version"], actor_id=actor)
            elif action == "approve":
                result = service.approve_interactively(arguments.review_id, record["version"])
            else:
                result = service.defer(arguments.review_id, record["version"], actor_id=actor)
        print(render_fields(result))
        return 0
    except (EOFError, KeyboardInterrupt):
        print(
            "\nProduct review stopped. Saved content is retained; approval requires a fresh terminal challenge."
        )
        return 130
    except ContractError as error:
        print("Product review failed. " + safe_text(error), file=sys.stderr)
        return 1
    except OSError:
        print(
            "Product review could not access its local files or foreground terminal.",
            file=sys.stderr,
        )
        return 1
