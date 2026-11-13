# SPDX-License-Identifier: MPL-2.0
"""Corinthos command-line entry point."""

import argparse
import sys
from pathlib import Path

from corinthos import __version__


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="corinthos",
        description="Corinthos Core - contracts and human-led project negotiation.",
        epilog="Run corinthos for Home or corinthos . to open the current project.",
    )
    parser.add_argument("--version", action="version", version=f"corinthos {__version__}")
    from corinthos.application.cli import configure as configure_status
    from corinthos.bootstrap import add_cli as configure_bootstrap
    from corinthos.lifecycle.playtest_cli import add_cli as configure_playtest
    from corinthos.lifecycle.version_cli import add_cli as configure_version
    from corinthos.project_manager.cli import configure_parser
    from corinthos.report.cli import configure_parser as configure_report_parser
    from corinthos.validation.cli import configure_parser as configure_validation_parser
    from corinthos.workflow.build_cli import add_cli as configure_build
    from corinthos.workflow.cli import configure_parser as configure_workflow_parser

    commands = configure_parser(parser)
    configure_workflow_parser(commands)
    configure_validation_parser(commands)
    configure_report_parser(commands)
    configure_bootstrap(commands)
    configure_build(commands)
    configure_playtest(commands)
    configure_version(commands)
    configure_status(
        commands.add_parser("status", help="Inspect known state without making changes.")
    )
    if not argv or argv == ["."]:
        from corinthos.app_shell import run_shell

        return run_shell(parser, current=Path(".") if argv else None)
    arguments = parser.parse_args(argv)
    if hasattr(arguments, "handler"):
        return arguments.handler(arguments)
    parser.print_help()
    return 0
