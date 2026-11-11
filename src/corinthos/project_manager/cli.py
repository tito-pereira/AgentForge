# SPDX-License-Identifier: MPL-2.0
"""Thin terminal questions and navigation over the Project Manager service."""

import argparse
import sys
from pathlib import Path

from corinthos.contracts import ContractError, ContractRef, IntegrityError

from .approval import local_actor_id
from .presentation import render_fields, render_review, safe_text
from .service import ProjectManager

_MAX_ANSWER = 8192


def configure_parser(parser: argparse.ArgumentParser):
    commands = parser.add_subparsers(dest="command")
    project = commands.add_parser("project", help="Create, negotiate and review a project.")
    project.add_argument(
        "--root", type=Path, default=Path.cwd(), help="Authorized project directory."
    )
    actions = project.add_subparsers(dest="project_action", required=True)
    for name, description in {
        "start": "Describe a new idea and enter guided negotiation.",
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


def _answer(prompt: str, *, default: str | None = None, optional: bool = False) -> str:
    while True:
        suffix = "" if default is None else f" [{safe_text(default)}]"
        answer = input(prompt + suffix + "\n> ").strip()
        if not answer and default is not None:
            return default
        if len(answer) > _MAX_ANSWER:
            print(f"Use at most {_MAX_ANSWER} characters for one answer.")
        elif answer or optional:
            return answer
        else:
            print("Enter an answer, or press Ctrl-C to leave with accepted changes saved.")


def _pick(items: list, describe, prompt: str = "Choose a number"):
    if not items:
        print("There are no items to choose yet.")
        return None
    for index, item in enumerate(items, 1):
        print(f"{index}. {safe_text(describe(item))}")
    while True:
        choice = _answer(prompt)
        if choice.isascii() and choice.isdigit() and 1 <= int(choice) <= len(items):
            return items[int(choice) - 1]
        print("Choose one of the displayed numbers.")


def _lines(prompt: str, *, existing: list[str] | None = None) -> list[str]:
    if existing:
        print(render_fields(existing))
        if _answer("Keep these entries? Enter keep or replace", default="keep").lower() == "keep":
            return existing
    print(prompt + " Enter one item per answer. An empty answer finishes the list.")
    result = []
    while answer := _answer("Next item", optional=True):
        result.append(answer)
    return result


def _linked(items: list[dict], id_key: str, *, existing: list[str] | None = None) -> list[str]:
    if not items:
        return []
    for index, item in enumerate(items, 1):
        print(
            f"{index}. {safe_text(item.get('description', item.get('criterion', '')))} "
            f"[{safe_text(item[id_key])}]"
        )
    default = ",".join(
        str(i) for i, item in enumerate(items, 1) if item[id_key] in (existing or [])
    )
    while True:
        answer = _answer(
            "Link item numbers separated by commas. Enter /clear for no links", default=default
        )
        if not answer or answer == "/clear":
            return []
        choices = [item.strip() for item in answer.split(",")]
        if all(
            item.isascii() and item.isdigit() and 1 <= int(item) <= len(items) for item in choices
        ):
            return list(dict.fromkeys(items[int(item) - 1][id_key] for item in choices))
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


def _edit_item(snapshot: dict, collection: str) -> dict | None:
    items = snapshot["payload"][collection]
    choice = _pick(["Add", "Edit", "Remove"], str)
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
    return operation


def _proposal(snapshot: dict) -> dict | None:
    choice = _pick(["Add proposal", "Refine or classify a proposal", "Record a decision"], str)
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
    return {
        "action": "record_feasibility",
        "description": _answer("What is being assessed?"),
        "status": _pick(["NOT_VERIFIED", "ASSUMPTION", "CONFIRMED"], str),
        "evidence": _lines("Record the actual evidence or its local reference"),
    }


def _show(manager: ProjectManager, snapshot: dict) -> None:
    print("SAVED NEGOTIATION")
    print(render_fields({key: value for key, value in snapshot.items() if key != "review"}))
    print("PRELIMINARY ASSESSMENT")
    print(render_fields(manager.assess(snapshot["session_id"])))
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
    assessment = manager.assess(snapshot["session_id"])
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


def _conversation(manager: ProjectManager, snapshot: dict, actor: str) -> None:
    print("Your accepted changes are saved locally. You can leave and resume this session.")
    print("Session " + safe_text(snapshot["session_id"]))
    while snapshot["state"] not in {"PUBLISHED", "CANCELLED", "CLOSED_UNCHANGED", "RETURNED"}:
        choice = _pick(
            [
                "Edit project idea",
                "Edit scope, assumptions or risks",
                "Edit requirements and acceptance criteria",
                "Edit constraints",
                "Edit success criteria",
                "Negotiate suggestions or binding requirements",
                "Clarify questions or record feasibility",
                "Show complete draft",
                "Review complete contract",
                "Approve at the local terminal",
                "Save for later and leave",
                "Show history",
                "Keep existing specification",
                "Cancel this negotiation",
            ],
            str,
        )
        operation = None
        try:
            if choice == "Edit project idea":
                operation = {
                    "action": "set_vision",
                    "text": _answer(
                        "Describe the project idea", default=snapshot["payload"]["vision"]
                    ),
                }
            elif choice == "Edit scope, assumptions or risks":
                section = _pick(["included", "excluded", "assumptions", "risks"], str)
                operation = {
                    "action": "set_scope",
                    "section": section,
                    "items": _lines(
                        "Describe " + section, existing=snapshot["payload"]["scope"][section]
                    ),
                }
            elif choice in {
                "Edit requirements and acceptance criteria",
                "Edit constraints",
                "Edit success criteria",
            }:
                collection = {
                    "Edit requirements and acceptance criteria": "requirements",
                    "Edit constraints": "constraints",
                    "Edit success criteria": "success_criteria",
                }[choice]
                operation = _edit_item(snapshot, collection)
            elif choice == "Negotiate suggestions or binding requirements":
                operation = _proposal(snapshot)
            elif choice == "Clarify questions or record feasibility":
                operation = _clarification(snapshot)
            elif choice == "Show complete draft":
                _show(manager, snapshot)
            elif choice == "Review complete contract":
                snapshot = _review(manager, snapshot, actor)
            elif choice == "Approve at the local terminal":
                snapshot = _approve(manager, snapshot)
            elif choice == "Save for later and leave":
                snapshot = manager.defer(
                    snapshot["session_id"], snapshot["version"], actor_id=actor
                )
                break
            elif choice == "Show history":
                print(render_fields(manager.history(snapshot["session_id"])))
            elif choice == "Keep existing specification":
                snapshot = manager.keep(snapshot["session_id"], snapshot["version"], actor_id=actor)
                break
            elif choice == "Cancel this negotiation":
                if _answer("Type CANCEL to close this negotiation", optional=True) == "CANCEL":
                    snapshot = manager.cancel(
                        snapshot["session_id"], snapshot["version"], actor_id=actor
                    )
                    break
            if operation:
                snapshot = manager.edit(
                    snapshot["session_id"], snapshot["version"], operation, actor_id=actor
                )
                print("Saved.")
        except ContractError as error:
            print("The operation could not be completed. " + safe_text(error), file=sys.stderr)
            snapshot = manager.get(snapshot["session_id"])
    print("Session state " + safe_text(snapshot["state"]))
    print("Resume with corinthos project resume " + safe_text(snapshot["session_id"]))


def _session(manager: ProjectManager, session_id: str | None) -> dict | None:
    if session_id:
        return manager.get(session_id)
    return _pick(
        manager.list(),
        lambda item: f"{item['session_id']} [{item['state']}] " + item["payload"]["vision"],
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
    )
    return ContractRef.from_document(chosen) if chosen else None


def run(arguments: argparse.Namespace) -> int:
    try:
        manager = ProjectManager(arguments.root)
        actor = local_actor_id()
        action = arguments.project_action
        if action == "start":
            print(
                "Describe your idea in your own words. You will refine it through structured questions."
            )
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
                triage = _pick(["STRUCTURAL", "NEEDS_CLARIFICATION", "RETURN"], str)
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
