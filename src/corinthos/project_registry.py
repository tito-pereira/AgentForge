# SPDX-License-Identifier: MPL-2.0
"""Multi-project navigation over the existing per-user Recent Projects document."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from corinthos.contracts import ContractError, IntegrityError
from corinthos.project_status import MAX_ROOT_CHARS, ProjectStorage, project_status
from corinthos.user_state import read_state, update_state

_FILE = "recent-projects.json"
_EMPTY = {"version": 2, "projects": []}
_MAX_PROJECTS = 20
_OBSERVATION_TIMEOUT = 0.1


@dataclass(frozen=True)
class ProjectRegistryEntry:
    root: str
    display_name: str
    last_accessed_at: str
    availability: Literal["AVAILABLE", "MISSING", "UNAVAILABLE"]
    initialized: bool
    storage: ProjectStorage
    schema_version: int | None


def display_name(root: str) -> str:
    name = Path(root).name or Path(root).anchor or root
    return (
        "".join(character if character.isprintable() else " " for character in name).strip()
        or "Project"
    )[:128]


def _records(document: dict) -> list[dict[str, str]]:
    projects = document.get("projects")
    if (
        document.keys() != {"version", "projects"}
        or not isinstance(projects, list)
        or len(projects) > _MAX_PROJECTS
    ):
        raise IntegrityError("The saved Project Registry is invalid.")
    root_key, date_key = (
        ("path", "last_opened_at") if document["version"] == 1 else ("root", "last_accessed_at")
    )
    records = []
    roots = set()
    for entry in projects:
        try:
            if not isinstance(entry, dict) or entry.keys() != {root_key, date_key}:
                raise ValueError
            root, date = entry[root_key], entry[date_key]
            if (
                not isinstance(root, str)
                or not 0 < len(root) <= MAX_ROOT_CHARS
                or "\0" in root
                or any("\ud800" <= char <= "\udfff" for char in root)
                or not Path(root).is_absolute()
                or os.path.normpath(root) != root
                or not isinstance(date, str)
                or len(date) > 64
                or datetime.fromisoformat(date).utcoffset() != timedelta(0)
            ):
                raise ValueError
            key = os.path.normcase(root)
            if key in roots:
                raise ValueError
        except (TypeError, ValueError):
            raise IntegrityError("The saved Project Registry is invalid.") from None
        roots.add(key)
        records.append({"root": root, "last_accessed_at": date})
    return records


def _observed(record: dict[str, str]) -> ProjectRegistryEntry:
    root, date = record["root"], record["last_accessed_at"]
    name = display_name(root)
    try:
        status = project_status(root, inspection_timeout=_OBSERVATION_TIMEOUT)
    except (OSError, ValueError):
        return ProjectRegistryEntry(root, name, date, "UNAVAILABLE", False, "UNVERIFIED", None)
    if not status.exists:
        availability = "MISSING"
    elif not status.is_directory or status.storage in {"INVALID", "UNVERIFIED"}:
        availability = "UNAVAILABLE"
    else:
        availability = "AVAILABLE"
    return ProjectRegistryEntry(
        root, name, date, availability, status.initialized, status.storage, status.schema_version
    )


class ProjectRegistryService:
    """Store only normalized paths and explicit access times for a bounded set of projects."""

    def _saved(self) -> list[dict[str, str]]:
        return _records(read_state(_FILE, _EMPTY))

    def paths(self) -> list[str]:
        """Return recent paths in access order for the existing terminal Home."""
        return [record["root"] for record in self._saved()]

    def list(self, *, limit: int = 10, offset: int = 0) -> list[ProjectRegistryEntry]:
        if type(limit) is not int or not 1 <= limit <= 25 or type(offset) is not int or offset < 0:
            raise ValueError("Invalid Project Registry page.")
        return [_observed(record) for record in self._saved()[offset : offset + limit]]

    def last_accessed_at(self, root: str) -> str | None:
        key = os.path.normcase(root)
        return next(
            (
                record["last_accessed_at"]
                for record in self._saved()
                if os.path.normcase(record["root"]) == key
            ),
            None,
        )

    def remember(self, root: str | Path) -> ProjectRegistryEntry:
        """Revalidate an explicitly opened project and atomically record its access."""
        status = project_status(root)
        if not status.initialized or status.storage in {"INVALID", "UNVERIFIED"}:
            raise ContractError("The project is unavailable for access.")
        path = status.root
        key = os.path.normcase(path)
        entry = {"root": path, "last_accessed_at": datetime.now(UTC).isoformat()}

        def update(document):
            others = [
                record for record in _records(document) if os.path.normcase(record["root"]) != key
            ]
            return {"version": 2, "projects": [entry, *others[: _MAX_PROJECTS - 1]]}

        update_state(_FILE, _EMPTY, update)
        return ProjectRegistryEntry(
            path,
            display_name(path),
            entry["last_accessed_at"],
            "AVAILABLE",
            status.initialized,
            status.storage,
            status.schema_version,
        )
