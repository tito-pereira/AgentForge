# SPDX-License-Identifier: MPL-2.0
"""Path validation and passive observation of project storage."""

import os
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from corinthos.bootstrap import _read_profile, _root
from corinthos.contracts import ConflictError, ContractError, ContractStore
from corinthos.contracts.artifacts import is_link, private_directory

MAX_ROOT_CHARS = 4096
ProjectStorage = Literal["ABSENT", "CURRENT", "LEGACY", "INVALID", "UNVERIFIED"]
_Snapshot = TypeVar("_Snapshot")


@dataclass(frozen=True)
class ProjectStatus:
    root: str
    exists: bool
    is_directory: bool
    initialized: bool
    storage: ProjectStorage
    schema_version: int | None = None


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


def project_status(root: str | Path, *, inspection_timeout: float = 2) -> ProjectStatus:
    """Inspect one explicitly supplied path without opening a writable store."""
    status, _ = inspect_project(root, timeout=inspection_timeout)
    return status


def inspect_project(
    root: str | Path,
    *,
    read: Callable[[sqlite3.Connection, int], _Snapshot] | None = None,
    timeout: float = 2,
) -> tuple[ProjectStatus, _Snapshot | None]:
    """Optionally compose a projection in the same verified, read-only snapshot as status."""
    path = _absolute_root(root)
    path, exists, is_directory = _inspect_path(path)
    name = str(path)
    if not is_directory:
        return ProjectStatus(name, exists, False, False, "ABSENT"), None

    initialized = False
    snapshot = None
    try:
        safe_root = _root(path)
        name = str(safe_root)
        legacy = os.path.lexists(safe_root / ".nukytera")
        if not os.path.lexists(safe_root / ".corinthos"):
            return ProjectStatus(name, True, True, False, "LEGACY" if legacy else "ABSENT"), None
        private = private_directory(safe_root)
        initialized = _read_profile(private / "bootstrap.json") is not None and not legacy
        with ContractStore.inspect_snapshot(safe_root, timeout=timeout) as (connection, schema):
            if read is not None and connection is not None and schema is not None:
                snapshot = read(connection, schema)
        if schema is None:
            return ProjectStatus(
                name, True, True, initialized, "LEGACY" if legacy else "ABSENT"
            ), None
    except ConflictError:
        return ProjectStatus(name, True, True, initialized, "UNVERIFIED"), None
    except (ContractError, OSError, RuntimeError):
        return ProjectStatus(name, True, True, False, "INVALID"), None

    storage = "CURRENT" if schema == ContractStore.current_schema_version() else "LEGACY"
    return ProjectStatus(name, True, True, True, storage, schema), snapshot
