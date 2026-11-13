# SPDX-License-Identifier: MPL-2.0
"""Scriptable read-only access to the shared application operations."""

import json
import sys
from argparse import ArgumentParser
from dataclasses import asdict
from pathlib import Path

from corinthos.application import project_status, providers_status, version
from corinthos.contracts import ContractError


def configure(parser: ArgumentParser) -> None:
    parser.add_argument("--root", default=Path.cwd(), help="Project directory to inspect.")
    parser.set_defaults(handler=_status)


def _status(arguments) -> int:
    try:
        result = {
            "version": version().version,
            "project": asdict(project_status(arguments.root)),
        }
    except (OSError, ValueError, RuntimeError):
        print("Corinthos status could not read the requested local state.", file=sys.stderr)
        return 1
    try:
        result["providers"] = [asdict(provider) for provider in providers_status(arguments.root)]
    except (ContractError, OSError, ValueError, RuntimeError):
        result["providers"] = None
    print(json.dumps(result, indent=2))
    return 0
