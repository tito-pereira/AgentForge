# SPDX-License-Identifier: MPL-2.0
"""Review optional agent recommendations through explicit Project Manager edits."""

import json
from dataclasses import dataclass

from corinthos.contracts import ConflictError, ContractError

from .advice import advise
from .navigation import Back, answer, lines, pick
from .presentation import render_fields, safe_text

_TEXT_SECTIONS = ("detected", "missing", "scope", "constraints", "success_criteria", "questions")
_SUGGESTION_LABELS = {
    "scope": "Included capability",
    "requirements": "Requirement",
    "constraints": "Constraint",
    "success_criteria": "Project success criterion",
}


def _text(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 4096
        and bool(value.strip())
        and all(ord(char) >= 32 or char in "\n\r\t" for char in value)
        and all(not 0xD800 <= ord(char) <= 0xDFFF for char in value)
    )


def _items(value):
    return isinstance(value, list) and len(value) <= 20


def _texts(value):
    return _items(value) and all(_text(item) for item in value)


def _valid_requirement(item):
    return (
        isinstance(item, dict)
        and item.keys() == {"description", "criteria"}
        and _text(item["description"])
        and _texts(item["criteria"])
    )


def _valid_alternatives(item):
    if (
        not isinstance(item, dict)
        or item.keys() != {"topic", "options", "recommendation"}
        or not _text(item["topic"])
        or not _items(item["options"])
        or len(item["options"]) < 2
    ):
        return False
    recommendation = item["recommendation"]
    return (
        recommendation is None
        or type(recommendation) is int
        and 1 <= recommendation <= len(item["options"])
    ) and all(
        isinstance(option, dict)
        and option.keys() == {"description", "trade_off"}
        and all(_text(value) for value in option.values())
        for option in item["options"]
    )


def _analysis(output):
    output = output.strip()
    if output.startswith("```json\n") and output.endswith("\n```"):
        output = output.removeprefix("```json\n").removesuffix("\n```")
    try:
        data = json.loads(output)
    except (ValueError, RecursionError):
        return None
    if (
        isinstance(data, dict)
        and data.keys() == {*_TEXT_SECTIONS, "requirements", "alternatives"}
        and all(_texts(data[key]) for key in _TEXT_SECTIONS)
        and _items(data["requirements"])
        and all(_valid_requirement(item) for item in data["requirements"])
        and _items(data["alternatives"])
        and all(_valid_alternatives(item) for item in data["alternatives"])
    ):
        return data
    return None


def _request(manager, snapshot, provider, context):
    print(f"Requesting read-only advice from {provider}.")
    try:
        record = advise(
            manager,
            snapshot["session_id"],
            provider=provider,
            authoring_context=context,
            expected_version=snapshot["version"],
        )
    except ConflictError:
        raise
    except (ContractError, OSError):
        print("Agent assistance is unavailable for this project.")
        return None
    if manager.get(snapshot["session_id"])["version"] != snapshot["version"]:
        raise ConflictError("The saved draft changed while the advice was being prepared.")
    if record["state"] != "COMPLETED":
        print("Agent assistance is unavailable or incomplete.")
        return None
    observed = record["snapshot"]["result"]
    data = None if observed["output_truncated"] else _analysis(observed["output"])
    if data is None:
        print("Agent assistance did not return usable structured suggestions.")
    return data


@dataclass(frozen=True)
class _Suggestion:
    section: str
    text: str
    criteria: tuple[str, ...] = ()

    def label(self):
        return f"{_SUGGESTION_LABELS[self.section]} — {self.text}"

    def operation(self, snapshot):
        if self.section == "scope":
            current = snapshot["payload"]["scope"]["included"]
            return {
                "action": "set_scope",
                "section": "included",
                "items": list(dict.fromkeys([*current, self.text])),
            }
        if self.section == "requirements":
            return {
                "action": "upsert_requirement",
                "description": self.text,
                "acceptance_criteria": [{"criterion": text} for text in self.criteria],
            }
        if self.section == "constraints":
            return {"action": "upsert_constraint", "description": self.text}
        return {"action": "upsert_success_criterion", "criterion": self.text}


def _suggestions(data):
    return [
        *(_Suggestion("scope", text) for text in data["scope"]),
        *(
            _Suggestion("requirements", item["description"], tuple(item["criteria"]))
            for item in data["requirements"]
        ),
        *(_Suggestion("constraints", text) for text in data["constraints"]),
        *(_Suggestion("success_criteria", text) for text in data["success_criteria"]),
    ]


def _decide(suggestion):
    """Return the chosen draft edit and whether the recommendation was dismissed."""
    print(safe_text(suggestion.label()))
    if suggestion.section == "requirements":
        print("Proposed acceptance criteria")
        print(render_fields(list(suggestion.criteria), indent=2))
    accept = "Add to draft"
    choice = pick([accept, "Edit before adding", "Reject suggestion"], str)
    if choice is None:
        return None, False
    if choice == "Reject suggestion":
        print("Suggestion dismissed.")
        return None, True
    if choice == accept:
        return suggestion, True
    text = answer("Edit the proposed text", default=suggestion.text)
    criteria = suggestion.criteria
    if suggestion.section == "requirements":
        criteria = tuple(
            lines("Describe observable acceptance criteria", existing=list(suggestion.criteria))
        )
    print(safe_text(text))
    if suggestion.section == "requirements":
        print("Acceptance criteria")
        print(render_fields(list(criteria), indent=2))
    if pick(["Add edited suggestion to draft"], str):
        return _Suggestion(suggestion.section, text, criteria), True
    return None, False


def _save(manager, snapshot, actor, operation, completion):
    snapshot = manager.edit(snapshot["session_id"], snapshot["version"], operation, actor_id=actor)
    print("Saved to the project draft.")
    completion(manager, snapshot)
    return snapshot


def _review_suggestions(manager, snapshot, actor, suggestions, completion):
    while suggestions and (item := pick(suggestions, _Suggestion.label, "Review a suggestion")):
        try:
            accepted, dismissed = _decide(item)
        except Back:
            continue
        if accepted is not None:
            snapshot = _save(manager, snapshot, actor, accepted.operation(snapshot), completion)
        if dismissed:
            suggestions.remove(item)
    return snapshot


def _answer_questions(manager, snapshot, actor, questions, completion):
    while questions and (question := pick(questions, str, "Choose a question")):
        print(safe_text(question))
        try:
            response = answer("Your answer")
        except Back:
            continue
        if pick(["Record answer in draft"], str):
            snapshot = _save(
                manager,
                snapshot,
                actor,
                {"action": "set_question", "text": question, "answer": response},
                completion,
            )
            questions.remove(question)
    return snapshot


def _choose_alternative(topic, *, read_only):
    """Review options and return a proposed constraint, or request more options."""
    while True:
        labels = [
            f"{option['description']} — {option['trade_off']}"
            + (" (agent recommendation)" if index == topic["recommendation"] else "")
            for index, option in enumerate(topic["options"], 1)
        ]
        request = "Ask for different alternatives"
        choice = pick([*labels, request], str, "Explore a choice")
        if choice is None:
            return None, False
        if choice == request:
            return None, True
        if read_only:
            print("Use advanced configuration to edit the obligations covered by this request.")
            continue
        option = topic["options"][labels.index(choice)]
        try:
            accepted, _ = _decide(_Suggestion("constraints", option["description"]))
        except Back:
            continue
        if accepted is not None:
            return accepted, False


def _show_analysis(manager, snapshot, data):
    print("\nCORINTHOS PROJECT ANALYSIS")
    print("These are suggestions. Only choices you explicitly save enter the draft.")
    print("Detected in your description")
    print(render_fields(data["detected"], indent=2))
    print("Missing information identified by the agent")
    print(render_fields(data["missing"], indent=2))
    print("Open questions identified by the agent")
    print(render_fields(data["questions"], indent=2))
    print("Outstanding checks for the saved draft")
    print(render_fields(manager.structural_issues(snapshot), indent=2))


def _continuation(snapshot):
    route = pick(
        ["Walk through missing information", "Configure manually"], str, "Continue without advice"
    )
    return snapshot, {
        "Walk through missing information": "gaps",
        "Configure manually": "manual",
    }.get(route)


def author_with_advice(manager, snapshot, actor, *, completion):
    """Offer read-only recommendations and apply only separately accepted edits."""
    print("Choose which configured agent may receive the saved project draft.")
    provider = pick(["Codex", "Claude Code"], str, "Choose an advisory provider")
    if provider is None:
        return snapshot, None
    provider = {"Codex": "codex", "Claude Code": "claude"}[provider]
    context = {}
    bounded_revision = snapshot["source_prr"] is not None
    while (data := _request(manager, snapshot, provider, context)) is not None:
        _show_analysis(manager, snapshot, data)
        suggestions = _suggestions(data)
        questions = list(data["questions"])
        alternatives = list(data["alternatives"])
        while True:
            choices = [
                "Review suggested specification",
                "Answer questions",
                "Explore choices and trade-offs",
                "Ask for alternatives",
                "Walk through missing information",
                "Configure manually",
            ]
            if not bounded_revision:
                choices.insert(4, "Refine project idea")
            choice = pick(choices, str)
            if choice is None:
                return snapshot, None
            if choice == "Review suggested specification":
                if bounded_revision:
                    print(render_fields([item.label() for item in suggestions], indent=2))
                    print(
                        "Use advanced configuration to edit the obligations covered by this request."
                    )
                elif suggestions:
                    snapshot = _review_suggestions(
                        manager, snapshot, actor, suggestions, completion
                    )
                else:
                    print("No remaining suggestions.")
            elif choice == "Answer questions":
                if questions:
                    snapshot = _answer_questions(manager, snapshot, actor, questions, completion)
                else:
                    print("No remaining questions.")
            elif choice == "Explore choices and trade-offs":
                topic = pick(alternatives, lambda item: item["topic"], "Choose a topic")
                if topic is not None:
                    accepted, request = _choose_alternative(topic, read_only=bounded_revision)
                    if request:
                        context = {"topic": topic}
                        break
                    if accepted is not None:
                        snapshot = _save(
                            manager, snapshot, actor, accepted.operation(snapshot), completion
                        )
                        alternatives.remove(topic)
            elif choice == "Ask for alternatives":
                context = {"alternatives": data["alternatives"][:3]}
                break
            elif choice == "Refine project idea":
                try:
                    vision = answer(
                        "Refine the project idea", default=snapshot["payload"]["vision"]
                    )
                except Back:
                    continue
                snapshot = _save(
                    manager, snapshot, actor, {"action": "set_vision", "text": vision}, completion
                )
            elif choice == "Walk through missing information":
                return snapshot, "gaps"
            else:
                return snapshot, "manual"
    return _continuation(snapshot)
