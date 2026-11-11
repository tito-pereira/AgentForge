# SPDX-License-Identifier: MPL-2.0
"""Corinthos command-line entry point."""

import argparse

from corinthos import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="corinthos",
        description="Corinthos Core - contracts and human-led project negotiation.",
    )
    parser.add_argument("--version", action="version", version=f"corinthos {__version__}")
    from corinthos.project_manager.cli import configure_parser
    from corinthos.report.cli import configure_parser as configure_report_parser
    from corinthos.validation.cli import configure_parser as configure_validation_parser
    from corinthos.workflow.cli import configure_parser as configure_workflow_parser

    commands = configure_parser(parser)
    configure_workflow_parser(commands)
    configure_validation_parser(commands)
    configure_report_parser(commands)
    arguments = parser.parse_args(argv)
    if hasattr(arguments, "handler"):
        return arguments.handler(arguments)
    parser.print_help()
    return 0
