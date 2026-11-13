# SPDX-License-Identifier: MPL-2.0
"""Shared, passive read operations for the CLI and desktop sidecar."""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from corinthos import __version__
from corinthos.bootstrap import _read_profile, _root, show_adapters
from corinthos.contracts import ConflictError, ContractError, ContractStore
from corinthos.contracts.artifacts import is_link, private_directory
from corinthos.providers import show_providers

MAX_ROOT_CHARS = 4096
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")


@dataclass(frozen=True)
class VersionInfo:
    version: str


@dataclass(frozen=True)
class ProjectStatus:
    root: str
    exists: bool
    is_directory: bool
    initialized: bool
    storage: Literal["ABSENT", "CURRENT", "LEGACY", "INVALID", "UNVERIFIED"]
    schema_version: int | None = None


@dataclass(frozen=True)
class KnownCapabilities:
    version: str | None
    available: bool
    json_events: bool
    stdin_prompt: bool
    native_resume: bool
    read_only: bool


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    supported: bool
    configuration: Literal["operational", "initial", "global", "default"]
    executable: str | None
    observation: Literal["OBSERVED", "NOT_OBSERVED", "UNKNOWN"]
    capabilities: KnownCapabilities | None


def version() -> VersionInfo:
    return VersionInfo(__version__)


def _absolute_root(value: str | Path) -> Path:
    raw = os.fspath(value)
    if (
        not isinstance(raw, str)
        or not 0 < len(raw) <= MAX_ROOT_CHARS
        or "\x00" in raw
        or any("\ud800" <= char <= "\udfff" for char in raw)
    ):
        raise ValueError("Invalid project root.")
    path = Path(raw)
    if os.name == "nt" and (
        path.anchor.startswith("\\\\")
        or (path.anchor and not path.is_absolute())
        or any(":" in part for part in path.parts[bool(path.anchor) :])
    ):
        raise ValueError("Invalid project root.")
    absolute = path if path.is_absolute() else Path.cwd() / path
    if len(str(absolute)) > MAX_ROOT_CHARS or (
        os.name == "nt" and absolute.anchor.startswith("\\\\")
    ):
        raise ValueError("Invalid project root.")
    return absolute


def _inspect_path(path: Path) -> tuple[Path, bool, bool]:
    if path == path.parent:
        candidate = path
    else:
        parent = _root(path.parent, missing_ok=True)
        if parent is None:
            return path, False, False
        candidate = parent / path.name
    try:
        info = candidate.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return candidate, False, False
    if is_link(info):
        raise ValueError("Project status requires an unredirected path.")
    return candidate, True, stat.S_ISDIR(info.st_mode)


def project_status(root: str | Path) -> ProjectStatus:
    """Inspect one explicitly supplied path without opening a writable store."""
    path = _absolute_root(root)
    path, exists, is_directory = _inspect_path(path)
    name = str(path)
    if not is_directory:
        return ProjectStatus(name, exists, False, False, "ABSENT")

    initialized = False
    try:
        safe_root = _root(path)
        name = str(safe_root)
        legacy = os.path.lexists(safe_root / ".nukytera")
        if not os.path.lexists(safe_root / ".corinthos"):
            return ProjectStatus(name, True, True, False, "LEGACY" if legacy else "ABSENT")
        private = private_directory(safe_root)
        initialized = _read_profile(private / "bootstrap.json") is not None and not legacy
        schema = ContractStore.inspect_existing(safe_root)
        if schema is None:
            return ProjectStatus(name, True, True, initialized, "LEGACY" if legacy else "ABSENT")
    except ConflictError:
        return ProjectStatus(name, True, True, initialized, "UNVERIFIED")
    except (ContractError, OSError, RuntimeError):
        return ProjectStatus(name, True, True, False, "INVALID")

    storage = "CURRENT" if schema == ContractStore.current_schema_version() else "LEGACY"
    return ProjectStatus(name, True, True, True, storage, schema)


def _known_capabilities(row: dict, executable: str | None) -> KnownCapabilities | None:
    cached = row["observed"]
    if cached is None or not row["supported"]:
        return None
    observed_path = cached["executable"]
    if executable is None:
        matches = row["executable"] is None and cached["discovery"] != "explicit"
    else:
        matches = observed_path is not None and os.path.normcase(observed_path) == os.path.normcase(
            executable
        )
    if not matches:
        return None
    observed_version = cached["version"]
    return KnownCapabilities(
        version=(
            observed_version
            if observed_version
            and len(observed_version) <= 128
            and _VERSION.fullmatch(observed_version)
            else None
        ),
        available=cached["available"],
        json_events=cached["json_events"],
        stdin_prompt=cached["stdin_prompt"],
        native_resume=cached["native_resume"],
        read_only=cached["read_only"],
    )


def providers_status(root: str | Path | None = None) -> list[ProviderStatus]:
    """Read saved choices and historical observations without discovery or probing."""
    choices = {}
    if root is not None:
        path, _, is_directory = _inspect_path(_absolute_root(root))
        if is_directory:
            choices = {row["provider"]: row for row in show_adapters(path)}
    results = []
    for row in show_providers():
        choice = choices.get(row["provider"])
        executable = row["executable"] if choice is None else choice["executable"]
        if executable is not None and len(executable) > MAX_ROOT_CHARS:
            raise ContractError("The configured executable path cannot be represented.")
        configuration = (
            ("global" if executable else "default") if choice is None else choice["configuration"]
        )
        capabilities = _known_capabilities(row, executable)
        observation = (
            "OBSERVED" if capabilities else "NOT_OBSERVED" if row["observed"] is None else "UNKNOWN"
        )
        results.append(
            ProviderStatus(
                row["provider"],
                row["supported"],
                configuration,
                executable,
                observation,
                capabilities,
            )
        )
    return results
