# SPDX-License-Identifier: MPL-2.0
"""Bounded lifecycle origins, CAS state and append-only historical projections."""

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from corinthos.contracts import ConflictError, ContractStore, IntegrityError, SchemaError
from corinthos.contracts.model import ID_PATTERN, canonical_json

KINDS = frozenset({"VERSION", "EVOLUTION", "BUILD", "SESSION", "FEEDBACK", "REVIEW", "OPERATION"})
UNCHANGED = object()
_STATE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_MAX_JSON = 4 * 1024 * 1024
_MAX_EVENT_JSON = 8 * 1024 * 1024
_MAX_ROWS = 20_000


@dataclass(frozen=True)
class LifecycleSummary:
    tracker_id: str
    enabled: bool
    active_build_id: str | None
    pending_build_id: str | None
    version: int


def now():
    return datetime.now(UTC).isoformat()


def digest(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise IntegrityError("Use a stable lifecycle identifier.")
    return value


def _kind(value):
    if not isinstance(value, str) or value not in KINDS:
        raise IntegrityError("Unknown lifecycle record kind.")
    return value


def _state(value):
    if not isinstance(value, str) or not _STATE.fullmatch(value):
        raise IntegrityError("Use a valid lifecycle state or event kind.")
    return value


def _pack(value, *, limit=_MAX_JSON):
    if not isinstance(value, dict):
        raise IntegrityError("Lifecycle origin, snapshot and event data require objects.")
    try:
        serialized = canonical_json(value)
    except SchemaError:
        raise IntegrityError("Lifecycle data requires finite, serializable JSON.") from None
    if len(serialized.encode("utf-8")) > limit:
        raise IntegrityError("Lifecycle data exceeds its bounded record limit.")
    return serialized, sha256(serialized.encode("utf-8")).hexdigest()


def _record(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("origin", "snapshot"):
        serialized = result[key]
        if not isinstance(serialized, str) or len(serialized.encode("utf-8")) > _MAX_JSON:
            raise IntegrityError("A stored lifecycle record is unavailable or oversized.")
        try:
            value = json.loads(serialized)
            canonical, expected = _pack(value)
        except (ValueError, TypeError, RecursionError):
            raise IntegrityError("A stored lifecycle record contains invalid JSON.") from None
        if canonical != serialized or expected != result[key + "_sha256"]:
            raise IntegrityError("A stored lifecycle record failed its integrity check.")
        result[key] = value
    return result


class LifecycleRepository:
    """Infrastructure only; existing Engine services own domain transitions."""

    def __init__(self, store_or_root):
        self.store = (
            store_or_root
            if isinstance(store_or_root, ContractStore)
            else ContractStore(store_or_root)
        )
        self.root = self.store._project_root

    @contextmanager
    def transaction(self):
        with self.store._transaction() as connection:
            yield connection

    @contextmanager
    def _use(self, connection, *, write=False):
        if connection is not None:
            if write and not connection.in_transaction:
                raise IntegrityError("Lifecycle writes require an active transaction.")
            yield connection
        elif write:
            with self.transaction() as connection:
                yield connection
        else:
            with self.store._connection() as connection:
                yield connection

    @staticmethod
    def project_summary(connection, project_id) -> LifecycleSummary | None:
        """Read the existing tracker and its exact build identities."""
        row = connection.execute(
            "SELECT tracker_id, enabled, active_build_id, pending_build_id, version "
            "FROM lc_projects WHERE project_id = ?",
            (identifier(project_id),),
        ).fetchone()
        if row is None:
            return None
        tracker, enabled, active, pending, version = row
        if enabled not in {0, 1} or type(version) is not int or version < 1:
            raise IntegrityError("The stored lifecycle tracker has inconsistent metadata.")
        return LifecycleSummary(
            identifier(tracker),
            bool(enabled),
            identifier(active) if active is not None else None,
            identifier(pending) if pending is not None else None,
            version,
        )

    def find(self, kind, record_id, *, connection=None):
        with self._use(connection) as conn:
            return _record(
                conn.execute(
                    "SELECT * FROM lc_records WHERE kind=? AND record_id=?",
                    (_kind(kind), identifier(record_id)),
                ).fetchone()
            )

    def get(self, kind, record_id, *, connection=None):
        record = self.find(kind, record_id, connection=connection)
        if record is None:
            raise IntegrityError("The exact lifecycle record was not found.")
        return record

    def list(self, kind, project_id, *, state=None, connection=None):
        with self._use(connection) as conn:
            values = [_kind(kind), identifier(project_id)]
            query = "SELECT * FROM lc_records WHERE kind=? AND project_id=?"
            if state is not None:
                query += " AND state=?"
                values.append(_state(state))
            rows = conn.execute(
                query + " ORDER BY rowid LIMIT ?", (*values, _MAX_ROWS + 1)
            ).fetchall()
            if len(rows) > _MAX_ROWS:
                raise IntegrityError("Lifecycle history exceeds its bounded record count.")
            return [_record(row) for row in rows]

    def create(
        self,
        kind,
        project_id,
        origin,
        *,
        state,
        snapshot=None,
        record_id=None,
        logical_key=None,
        connection=None,
        actor_id="lifecycle",
        event=None,
    ):
        kind, project_id = _kind(kind), identifier(project_id)
        actor_id = identifier(actor_id)
        event = _state(event or kind + "_CREATED")
        record_id = identifier(record_id or kind.lower() + "-" + uuid4().hex)
        state = _state(state)
        if logical_key is not None and (
            not isinstance(logical_key, str)
            or not 1 <= len(logical_key) <= 128
            or any(ord(char) < 32 or ord(char) == 127 for char in logical_key)
        ):
            raise IntegrityError("Use a bounded printable lifecycle logical key.")
        origin_json, origin_sha = _pack(origin)
        snapshot_json, snapshot_sha = _pack({} if snapshot is None else snapshot)
        created = now()
        with self._use(connection, write=True) as conn:
            if conn.execute("SELECT 1 FROM lc_records WHERE record_id=?", (record_id,)).fetchone():
                raise ConflictError("This lifecycle identity already exists.")
            if (
                logical_key is not None
                and conn.execute(
                    "SELECT 1 FROM lc_records WHERE kind=? AND project_id=? AND logical_key=?",
                    (kind, project_id, logical_key),
                ).fetchone()
            ):
                raise ConflictError("This lifecycle logical key already exists in the project.")
            conn.execute(
                "INSERT INTO lc_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    kind,
                    project_id,
                    logical_key,
                    state,
                    1,
                    origin_json,
                    origin_sha,
                    snapshot_json,
                    snapshot_sha,
                    created,
                    created,
                ),
            )
            record = self.get(kind, record_id, connection=conn)
            self.event(
                project_id,
                event,
                {"record": self._post(record)},
                record_id=record_id,
                connection=conn,
                actor_id=actor_id,
            )
            return record

    def update(
        self,
        kind,
        record_id,
        expected_version,
        *,
        state=None,
        snapshot=None,
        connection=None,
        actor_id="lifecycle",
        event=None,
    ):
        actor_id = identifier(actor_id)
        event = _state(event or _kind(kind) + "_UPDATED")
        with self._use(connection, write=True) as conn:
            old = self.get(kind, record_id, connection=conn)
            if type(expected_version) is not int or old["version"] != expected_version:
                raise ConflictError("The lifecycle record changed; inspect its current version.")
            state = old["state"] if state is None else _state(state)
            snapshot_json, snapshot_sha = _pack(old["snapshot"] if snapshot is None else snapshot)
            if state == old["state"] and snapshot_sha == old["snapshot_sha256"]:
                return old
            changed = conn.execute(
                "UPDATE lc_records SET state=?,version=version+1,snapshot=?,snapshot_sha256=?,"
                "updated_at=? WHERE record_id=? AND kind=? AND version=?",
                (state, snapshot_json, snapshot_sha, now(), record_id, kind, expected_version),
            ).rowcount
            if changed != 1:
                raise ConflictError("The lifecycle record changed concurrently.")
            record = self.get(kind, record_id, connection=conn)
            self.event(
                record["project_id"],
                event,
                {"record": self._post(record)},
                record_id=record_id,
                connection=conn,
                actor_id=actor_id,
            )
            return record

    @staticmethod
    def _post(record):
        return {
            key: record[key]
            for key in (
                "record_id",
                "kind",
                "project_id",
                "state",
                "version",
                "origin_sha256",
                "snapshot",
                "snapshot_sha256",
                "created_at",
                "updated_at",
            )
        }

    def project(self, project_id, *, create=False, connection=None, actor_id="lifecycle"):
        project_id = identifier(project_id)
        if type(create) is not bool:
            raise IntegrityError("Explicit lifecycle creation requires a boolean.")
        actor_id = identifier(actor_id)
        with self._use(connection, write=create) as conn:
            row = conn.execute(
                "SELECT * FROM lc_projects WHERE project_id=?", (project_id,)
            ).fetchone()
            if row is None and create:
                created = now()
                conn.execute(
                    "INSERT INTO lc_projects VALUES(?,0,?,NULL,NULL,1,?,?)",
                    (project_id, "tracker-" + uuid4().hex, created, created),
                )
                row = conn.execute(
                    "SELECT * FROM lc_projects WHERE project_id=?", (project_id,)
                ).fetchone()
                result = dict(row)
                result["enabled"] = bool(result["enabled"])
                self.event(
                    project_id,
                    "PROJECT_CREATED",
                    {"project": result},
                    connection=conn,
                    actor_id=actor_id,
                )
                return result
            if row is None:
                return None
            result = dict(row)
            result["enabled"] = bool(result["enabled"])
            return result

    def _update_project(
        self,
        project_id,
        expected_version,
        *,
        enabled=None,
        active_build_id=UNCHANGED,
        pending_build_id=UNCHANGED,
        connection=None,
        actor_id="lifecycle",
        event="PROJECT_UPDATED",
    ):
        actor_id = identifier(actor_id)
        event = _state(event)
        with self._use(connection, write=True) as conn:
            old = self.project(project_id, connection=conn)
            if (
                old is None
                or type(expected_version) is not int
                or old["version"] != expected_version
            ):
                raise ConflictError("The project lifecycle state changed; inspect it again.")
            if enabled is not None and type(enabled) is not bool:
                raise IntegrityError("IPE enabled requires a boolean.")
            changed = dict(old)
            if enabled is not None:
                changed["enabled"] = enabled
            for key, value in (
                ("active_build_id", active_build_id),
                ("pending_build_id", pending_build_id),
            ):
                if value is UNCHANGED:
                    continue
                if value is not None:
                    record = self.get("BUILD", value, connection=conn)
                    if record["project_id"] != project_id:
                        raise IntegrityError("A lifecycle pointer belongs to another project.")
                changed[key] = value
            if changed == old:
                return old
            count = conn.execute(
                "UPDATE lc_projects SET enabled=?,active_build_id=?,pending_build_id=?,"
                "version=version+1,updated_at=? WHERE project_id=? AND version=?",
                (
                    int(changed["enabled"]),
                    changed["active_build_id"],
                    changed["pending_build_id"],
                    now(),
                    project_id,
                    expected_version,
                ),
            ).rowcount
            if count != 1:
                raise ConflictError("The project lifecycle state changed concurrently.")
            result = self.project(project_id, connection=conn)
            self.event(project_id, event, {"project": result}, connection=conn, actor_id=actor_id)
            return result

    def event(
        self, project_id, kind, data, *, record_id=None, connection=None, actor_id="lifecycle"
    ):
        serialized, _ = _pack(data, limit=_MAX_EVENT_JSON)
        with self._use(connection, write=True) as conn:
            if record_id is not None:
                identifier(record_id)
            occurred = now()
            cursor = conn.execute(
                "INSERT INTO lc_events(project_id,record_id,kind,data,actor_id,occurred_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    identifier(project_id),
                    record_id,
                    _state(kind),
                    serialized,
                    identifier(actor_id),
                    occurred,
                ),
            )
            return {
                "sequence": cursor.lastrowid,
                "project_id": project_id,
                "record_id": record_id,
                "kind": kind,
                "data": json.loads(serialized),
                "actor_id": actor_id,
                "occurred_at": occurred,
            }

    def events(self, project_id, *, record_id=None, connection=None):
        with self._use(connection) as conn:
            values = [identifier(project_id)]
            query = "SELECT * FROM lc_events WHERE project_id=?"
            if record_id is not None:
                query += " AND record_id=?"
                values.append(identifier(record_id))
            rows = conn.execute(
                query + " ORDER BY sequence LIMIT ?", (*values, _MAX_ROWS + 1)
            ).fetchall()
            if len(rows) > _MAX_ROWS:
                raise IntegrityError("Lifecycle event history exceeds its bounded read limit.")
            result = []
            for row in rows:
                value = dict(row)
                try:
                    value["data"] = json.loads(value["data"])
                    _pack(value["data"], limit=_MAX_EVENT_JSON)
                except (ValueError, TypeError, RecursionError):
                    raise IntegrityError("A stored lifecycle event is invalid.") from None
                result.append(value)
            return result
