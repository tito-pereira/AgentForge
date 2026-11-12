# SPDX-License-Identifier: MPL-2.0
"""Explicit terminal navigation for Project Manager authoring."""

from .presentation import render_fields, safe_text

_MAX_ANSWER = 8192


class Back(Exception):
    """Leave an in-progress input without saving it."""


class SaveAndExit(Exception):
    """Leave the authoring session with accepted edits saved."""


def answer(prompt: str, *, default: str | None = None, optional: bool = False) -> str:
    suffix = "" if default is None else f" [{safe_text(default)}]"
    while True:
        text = input(prompt + suffix + "\n/back to go back, /save to save and exit\n> ").strip()
        if text.lower() == "/back":
            raise Back
        if text.lower() == "/save":
            raise SaveAndExit
        if text.lower() in {"//back", "//save"}:
            return text[1:]
        if not text and default is not None:
            return default
        if len(text) > _MAX_ANSWER:
            print(f"Use at most {_MAX_ANSWER} characters for one answer.")
        elif text or optional:
            return text
        else:
            print("Enter an answer, /back or /save.")


def choose[T](choices: dict[str, T], prompt: str = "Choose a number", *, save=True) -> T | None:
    print("0. Back")
    if save:
        print("S. Save and exit")
    while True:
        choice = input(prompt + "\n> ").strip().upper()
        if choice == "0":
            return None
        if save and choice == "S":
            raise SaveAndExit
        if choice in choices:
            return choices[choice]
        print("Choose one of the displayed options.")


def pick(items: list, describe, prompt: str = "Choose a number", *, save=True):
    if not items:
        print("There are no items to choose yet.")
        return None
    choices = {}
    for index, item in enumerate(items, 1):
        print(f"{index}. {safe_text(describe(item))}")
        choices[str(index)] = item
    return choose(choices, prompt, save=save)


def lines(prompt: str, *, existing: list[str] | None = None) -> list[str]:
    if existing:
        print(render_fields(existing))
        if answer("Keep these entries? Enter keep or replace", default="keep").lower() == "keep":
            return existing
    print(prompt + " Enter one item per answer. An empty answer finishes the list.")
    result = []
    while text := answer("Next item", optional=True):
        result.append(text)
    return result
