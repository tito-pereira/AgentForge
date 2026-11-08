"""Minimal Phase 0 command-line interface."""

import argparse

from agentforge import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentforge",
        description="AgentForge Core - Phase 0 technical foundation.",
    )
    parser.add_argument("--version", action="version", version=f"agentforge {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
