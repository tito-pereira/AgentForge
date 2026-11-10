# SPDX-License-Identifier: MPL-2.0
"""Durable negotiation snapshots and append-only turns in the shared store."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from ..contracts import ConflictError, ContractStore, StoreError
from ..contracts.model import ID_PATTERN, canonical_json

MAX_SNAPSHOT_BYTES = 1_048_576
_MAX_VERSION = 9_223_372_036_854_775_807


def _identifier(value: object) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise StoreError("A session operation requires a valid stable identifier.")


def _version(value: object) -> None:
    if type(value) is not int or not 1 <= value <= _MAX_VERSION:
        raise StoreError("A session operation requires a valid version.")


def _snapshot(snapshot: dict, *, version: int) -> dict:
    if type(snapshot) is not dict:
        raise StoreError("A session snapshot must be a JSON object.")
    _identifier(snapshot.get("session_id"))
    _identifier(snapshot.get("project_id"))
    result = {**snapshot, "version": version}
    serialized = canonical_json(result)
    if len(serialized.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise StoreError("The session snapshot exceeds the 1 MiB limit.")
    return json.loads(serialized)


def _read_snapshot(row: sqlite3.Row) -> dict:
    try:
        snapshot = json.loads(row["snapshot"])
        version = row["version"]
        _version(version)
        _version(snapshot.get("version"))
        if (
            snapshot.get("version") != version
            or snapshot.get("project_id") != row["project_id"]
            or snapshot.get("session_id") != row["session_id"]
        ):
            raise StoreError("The stored session snapshot has inconsistent identity.")
        return _snapshot(snapshot, version=version)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise StoreError("The stored session snapshot is invalid.") from None


class SessionRepository:
    """Store bounded JSON snapshots with optimistic session version checks."""

    def __init__(self, store: ContractStore):
        if not isinstance(store, ContractStore):
            raise StoreError("Session persistence requires a ContractStore.")
        self._store = store

    @property
    def store(self) -> ContractStore:
        return self._store

    @staticmethod
    def _turn(connection: sqlite3.Connection, snapshot: dict, actor_id: str, action: str) -> None:
        _identifier(actor_id)
        if (
            not isinstance(action, str)
            or not action.strip()
            or len(action) > 128
            or any(ord(character) < 32 or ord(character) == 127 for character in action)
        ):
            raise StoreError("A session action must be nonblank text of at most 128 characters.")
        connection.execute(
            "INSERT INTO pm_turns "
            "(turn_id, session_id, version, actor_id, action, snapshot, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                uuid4().hex,
                snapshot["session_id"],
                snapshot["version"],
                actor_id,
                action,
                canonical_json(snapshot),
                datetime.now(UTC).isoformat(),
            ),
        )

    def create(self, snapshot: dict, *, actor_id: str, action: str) -> dict:
        """Create version 1 and its first accepted turn atomically."""
        if type(snapshot) is not dict or type(snapshot.get("version", 1)) is not int:
            raise StoreError("A new session requires version 1.")
        if snapshot.get("version", 1) != 1:
            raise StoreError("A new session requires version 1.")
        saved = _snapshot(snapshot, version=1)
        with self.store._transaction() as connection:
            connection.execute(
                "INSERT INTO pm_sessions (session_id, project_id, version, snapshot) "
                "VALUES (?, ?, ?, ?)",
                (saved["session_id"], saved["project_id"], 1, canonical_json(saved)),
            )
            self._turn(connection, saved, actor_id, action)
        return saved

    def get(self, session_id: str) -> dict:
        """Return a detached snapshot or fail for an unknown session."""
        _identifier(session_id)
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT * FROM pm_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise StoreError("The negotiation session does not exist.")
            return _read_snapshot(row)

    def list(self) -> list[dict]:
        """List detached session snapshots in creation order."""
        with self.store._connection() as connection:
            rows = connection.execute("SELECT * FROM pm_sessions ORDER BY rowid")
            return [_read_snapshot(row) for row in rows]

    def save(
        self,
        session_id: str,
        expected_version: int,
        snapshot: dict,
        *,
        actor_id: str,
        action: str,
    ) -> dict:
        """Advance a session and append its accepted turn in one transaction."""
        with self.store._transaction() as connection:
            return self._save(
                connection,
                session_id,
                expected_version,
                snapshot,
                actor_id=actor_id,
                action=action,
            )

    def _save(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        expected_version: int,
        snapshot: dict,
        *,
        actor_id: str,
        action: str,
    ) -> dict:
        """Share the trusted bridge's transaction for session and receipt updates."""
        _identifier(session_id)
        _version(expected_version)
        if expected_version == _MAX_VERSION:
            raise StoreError("The session version cannot advance further.")
        if type(snapshot) is not dict:
            raise StoreError("A session snapshot must be a JSON object.")
        supplied_version = snapshot.get("version", expected_version)
        _version(supplied_version)
        if supplied_version not in (expected_version, expected_version + 1):
            raise ConflictError("The supplied snapshot has a conflicting version.")
        saved = _snapshot(snapshot, version=expected_version + 1)
        if saved["session_id"] != session_id:
            raise ConflictError("A negotiation session cannot change its identity.")
        row = connection.execute(
            "SELECT project_id, version FROM pm_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise StoreError("The negotiation session does not exist.")
        if row["project_id"] != saved["project_id"] or row["version"] != expected_version:
            raise ConflictError("The session changed. Reload it before continuing.")
        cursor = connection.execute(
            "UPDATE pm_sessions SET version = ?, snapshot = ? "
            "WHERE session_id = ? AND project_id = ? AND version = ?",
            (
                saved["version"],
                canonical_json(saved),
                session_id,
                saved["project_id"],
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ConflictError("The session changed. Reload it before continuing.")
        self._turn(connection, saved, actor_id, action)
        return saved

    def history(self, session_id: str) -> list[dict]:
        """Return durable accepted turns without exposing mutable stored objects."""
        self.get(session_id)
        with self.store._connection() as connection:
            rows = connection.execute(
                "SELECT pm_turns.*, pm_sessions.project_id FROM pm_turns "
                "JOIN pm_sessions USING (session_id) "
                "WHERE session_id = ? ORDER BY version",
                (session_id,),
            )
            return [{**dict(row), "snapshot": _read_snapshot(row)} for row in rows]
