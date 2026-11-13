# SPDX-License-Identifier: MPL-2.0
"""Interactive application Home over existing project and adapter operations."""

import os
import sys
from argparse import ArgumentParser
from pathlib import Path

from corinthos.bootstrap import _read_profile, _root, initialize
from corinthos.contracts import ContractError, ContractStore, IntegrityError
from corinthos.contracts.artifacts import private_directory
from corinthos.project_manager.navigation import Back, answer, choose, pick
from corinthos.project_manager.presentation import render_fields, safe_text
from corinthos.project_registry import ProjectRegistryService
from corinthos.user_state import read_state, state_root


def _remember(root):
    try:
        ProjectRegistryService().remember(root)
    except (ContractError, OSError) as error:
        print("Could not update Recent projects. " + safe_text(error), file=sys.stderr)


def _open_project(path):
    root = _root(path)
    if not os.path.lexists(root / ".corinthos"):
        raise IntegrityError("No Corinthos project exists in that directory.")
    private = private_directory(root)
    profile = _read_profile(private / "bootstrap.json")
    if not ContractStore.verify_existing(root):
        if os.path.lexists(root / ".nukytera"):
            raise IntegrityError("Migrate the legacy project state before opening this workspace.")
        if profile is None:
            raise IntegrityError("No saved Corinthos project was found in that directory.")
    return root


def _create_project(path):
    root = _root(path, create=True)
    if os.path.lexists(root / ".corinthos") and os.path.lexists(
        private_directory(root) / "state.db"
    ):
        raise IntegrityError("A Corinthos project already exists here. Open it from Home.")
    initialize(root)
    return root


def _project_menu(parser, root):
    _remember(root)
    while True:
        print(
            "\nPROJECT\n" + safe_text(root) + "\n\n1. Start project specification\n"
            "2. Resume saved draft\n"
            "3. List saved drafts"
        )
        action = choose({"1": "start", "2": "resume", "3": "sessions"}, save=False)
        if action is None:
            return
        arguments = parser.parse_args(["project", "--root", str(root), action])
        arguments.handler(arguments)


def _provider_menu():
    from corinthos.providers import (
        SUPPORTED_PROVIDERS,
        configure_provider,
        refresh_providers,
        show_providers,
    )

    while True:
        print("\nPROVIDERS")
        print(render_fields(show_providers()))
        print(
            "1. Refresh native capabilities\n"
            "2. Configure a native executable\n"
            "3. Reset a configured executable"
        )
        action = choose({"1": "refresh", "2": "configure", "3": "reset"}, save=False)
        if action is None:
            return
        try:
            if action == "refresh":
                refresh_providers()
                continue
            provider = pick(list(SUPPORTED_PROVIDERS), str, "Choose a provider", save=False)
            if provider is not None:
                executable = (
                    answer("Absolute native executable", save=False)
                    if action == "configure"
                    else None
                )
                configure_provider(provider, executable=executable)
        except Back:
            continue
        except (ContractError, OSError) as error:
            _report_error(error)


def _settings():
    config = read_state("config.json", {"version": 1})
    print("\nSETTINGS")
    print("User state directory\n  " + safe_text(state_root()))
    print(f"Configuration version\n  {config['version']}")
    choose({}, save=False)


def _report_error(error):
    print("Corinthos could not complete the operation. " + safe_text(error), file=sys.stderr)


def run_shell(parser: ArgumentParser, *, current: Path | None = None) -> int:
    """Open Home or the requested workspace, preserving the scriptable commands."""
    try:
        if current is not None:
            try:
                root = _open_project(current)
            except (ContractError, OSError) as error:
                _report_error(error)
                return 1
            _project_menu(parser, root)
        while True:
            print(
                "\nCORINTHOS\n\n"
                "1. Create new project\n"
                "2. Open existing project\n"
                "3. Recent projects\n"
                "4. Providers\n"
                "5. Settings\n"
                "6. Help"
            )
            action = choose({key: key for key in "123456"}, save=False, zero_label="Exit")
            if action is None:
                return 0
            try:
                if action in {"1", "2"}:
                    operation, prompt = (
                        (_create_project, "Directory for the new project")
                        if action == "1"
                        else (_open_project, "Directory of the existing project")
                    )
                    path = answer(prompt, save=False)
                    if "\0" in path:
                        raise IntegrityError("Enter a valid project directory.")
                    _project_menu(parser, operation(path))
                elif action == "3":
                    print("\nRECENT PROJECTS")
                    paths = ProjectRegistryService().paths()
                    selected = pick(paths, str, "Open a recent project", save=False)
                    if selected:
                        _project_menu(parser, _open_project(selected))
                elif action == "4":
                    _provider_menu()
                elif action == "5":
                    _settings()
                else:
                    parser.print_help()
                    choose({}, save=False)
            except Back:
                continue
            except (ContractError, OSError) as error:
                _report_error(error)
    except EOFError:
        return 0
    except KeyboardInterrupt:
        print("\nCorinthos closed.")
        return 130
