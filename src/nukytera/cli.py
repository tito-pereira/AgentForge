# SPDX-License-Identifier: MPL-2.0
"""Minimal Phase 0 command-line interface."""

import argparse

from nukytera import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nukytera",
        description="Nukytera Core - Phase 0 technical foundation.",
    )
    parser.add_argument("--version", action="version", version=f"nukytera {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
