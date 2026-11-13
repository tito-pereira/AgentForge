# SPDX-License-Identifier: MPL-2.0
"""Persist Agent Sessions and observations through the shared SQLite store."""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from pathlib import Path
from uuid import uuid4

from corinthos.bootstrap import _root
from corinthos.contracts import ConflictError, ContractStore
from corinthos.contracts.artifacts import private_directory
from corinthos.contracts.model import ID_PATTERN, canonical_json
from corinthos.project_status import _absolute_root

from .model import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    EventKind,
    Session,
    SessionError,
    SessionEvent,
    SessionOwnership,
    SessionState,
    SessionSummary,
)

_ACTIVE = "state IN ('STARTING', 'RUNNING', 'CANCELLING')"
_MAX_INTEGER = 2**53 - 1
MAX_EVENT_BYTES = 4096
MAX_PAGE_SIZE = 25
_SESSION_ID = re.compile(r"session-[0-9a-f]{32}")
_WORK_ID = re.compile(r"work-[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MONEY = re.compile(r"[0-9]{1,30}(?:\.[0-9]{1,30})?")
_CURRENCY = re.compile(r"[A-Z]{3}")
_OBSERVATIONS = {
    EventKind.OUTPUT,
    EventKind.TOOL_ACTIVITY,
    EventKind.USAGE,
    EventKind.WARNING,
    EventKind.ERROR,
}
_TOKEN_FIELDS = ("input_tokens", "output_tokens", "cached_tokens")
_USAGE_FIELDS = (*_TOKEN_FIELDS, "reported_cost", "reported_cost_currency")


def _identifier(value, pattern=ID_PATTERN):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise SessionError("An Agent Session identifier is invalid.")
    return value


def _optional_label(value):
    if value is not None and (
        not isinstance(value, str) or not 0 < len(value) <= 128 or not value.isprintable()
    ):
        raise SessionError("An Agent Session observation label is invalid.")
    return value


def _amount(value):
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
        raise SessionError("Agent Session telemetry must be an explicit bounded integer.")
    return value


def _usage(value):
    if not isinstance(value, dict) or value.keys() - set(_USAGE_FIELDS):
        raise SessionError("The usage observation has unknown fields.")
    result = {key: _amount(value.get(key)) for key in _TOKEN_FIELDS}
    amount, currency = value.get("reported_cost"), value.get("reported_cost_currency")
    if amount is not None or currency is not None:
        _identifier(amount, _MONEY)
        _identifier(currency, _CURRENCY)
        integral, dot, fraction = value["reported_cost"].partition(".")
        fraction = fraction.rstrip("0")
        amount = (integral.lstrip("0") or "0") + (f".{fraction}" if dot and fraction else "")
    return result | {"reported_cost": amount, "reported_cost_currency": currency}


def _page(limit, cursor):
    if (
        type(limit) is not int
        or not 1 <= limit <= MAX_PAGE_SIZE
        or type(cursor) is not int
        or not 0 <= cursor <= _MAX_INTEGER
    ):
        raise SessionError("The Agent Session page is invalid.")


def _payload(value):
    if type(value) is not dict:
        raise SessionError("An Agent Session event payload must be a JSON object.")

    def bound(item, depth):
        if depth > 8:
            raise SessionError("An Agent Session event payload has too much nesting.")
        if isinstance(item, (dict, list)):
            if len(item) > 64:
                raise SessionError("An Agent Session event payload has too many entries.")
            for child in item.values() if isinstance(item, dict) else item:
                bound(child, depth + 1)

    bound(value, 0)
    result = canonical_json(value)
    if len(result.encode("utf-8")) > MAX_EVENT_BYTES:
        raise SessionError("An Agent Session event payload exceeds its size limit.")
    return result


def _timestamp(now: float):
    return datetime.fromtimestamp(now, UTC).isoformat(timespec="microseconds")


def _session(row):
    return (
        Session(
            **(
                dict(row)
                | {
                    "state": SessionState(row["state"]),
                    "read_only": bool(row["read_only"]),
                    "native_resume": bool(row["native_resume"]),
                    "cleanup_unconfirmed": bool(row["cleanup_unconfirmed"]),
                }
            )
        )
        if row is not None
        else None
    )


class SessionRepository:
    """Own atomic session state and event changes, with fenced worker ownership."""

    def __init__(self, root: str | Path, *, clock=None):
        self.root = root
        self._clock = time.time if clock is None else clock
        self._store = None

    def now(self) -> float:
        value = self._clock()
        if (
            type(value) not in (int, float)
            or not 0 <= value < 253_402_300_799
            or not isfinite(value)
        ):
            raise SessionError("The Agent Session clock is invalid.")
        return value

    @staticmethod
    def _deadline(now, seconds):
        if type(seconds) not in (int, float) or not 1 <= seconds <= 120:
            raise SessionError("Use a bounded Agent Session lease between 1 and 120 seconds.")
        return now + seconds

    def _project(self):
        return _root(_absolute_root(self.root), missing_ok=True)

    @contextmanager
    def _read(self):
        root = self._project()
        if root is None or not os.path.lexists(root / ".corinthos"):
            yield None
            return
        # Passive inspection verifies the private path and the database without opening a writer.
        with ContractStore.read_snapshot(root) as (connection, version):
            yield connection if version is not None and version >= 8 else None

    @contextmanager
    def _write(self):
        root = self._project()
        if root is None or not os.path.lexists(root / ".corinthos"):
            raise SessionError("An existing local Work Item is required.")
        if not (private_directory(root) / "state.db").is_file():
            raise SessionError("An existing local Work Item is required.")
        if self._store is None:
            self._store = ContractStore(root)
        elif root != self._store.database_path.parent.parent:
            raise ConflictError("The Agent Session project root changed.")
        with self._store._transaction() as connection:
            yield connection

    @staticmethod
    def _row(connection, session_id):
        row = connection.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise SessionError("The Agent Session was not found.")
        return row

    @classmethod
    def _owned(cls, connection, session_id, owner_id, generation, now, *, require_live=True):
        _identifier(session_id, _SESSION_ID)
        _identifier(owner_id)
        if type(generation) is not int:
            raise SessionError("The Agent Session generation is invalid.")
        row = cls._row(connection, session_id)
        if (
            row["owner_id"] != owner_id
            or row["run_generation"] != generation
            or row["state"] not in ACTIVE_STATES
            or row["cleanup_unconfirmed"]
            or (require_live and row["lease_expires_at"] <= now)
        ):
            raise ConflictError("The Agent Session ownership expired or changed.")
        return row

    @staticmethod
    def _event(connection, row, kind, payload, now, native_kind=None):
        connection.execute(
            """INSERT INTO agent_session_events (
                session_id, sequence, run_generation, kind, occurred_at, payload, native_kind
            ) SELECT ?, COALESCE(MAX(sequence), 0) + 1, ?, ?, ?, ?, ?
              FROM agent_session_events WHERE session_id = ?""",
            (
                row["session_id"],
                row["run_generation"],
                kind,
                _timestamp(now),
                payload,
                native_kind,
                row["session_id"],
            ),
        )

    @staticmethod
    def _slot(connection):
        if connection.execute(f"SELECT 1 FROM agent_sessions WHERE {_ACTIVE}").fetchone():
            raise ConflictError("This project already has an active Agent Session.")

    def create(
        self,
        work_item_id,
        *,
        provider,
        owner_id,
        timeout_seconds,
        envelope_sha256=None,
        lease_seconds=30,
        native_resume=False,
        read_only=True,
    ) -> Session:
        _identifier(work_item_id, _WORK_ID)
        _identifier(provider)
        _identifier(owner_id)
        if envelope_sha256 is not None:
            _identifier(envelope_sha256, _DIGEST)
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
            raise SessionError("Use an Agent Session timeout between 1 and 3600 seconds.")
        if type(native_resume) is not bool or type(read_only) is not bool:
            raise SessionError("The Agent Session execution mode is invalid.")
        session_id = f"session-{uuid4().hex}"
        with self._write() as connection:
            now = self.now()
            deadline = self._deadline(now, lease_seconds)
            work = connection.execute(
                "SELECT project_id, status FROM work_items WHERE work_item_id = ?", (work_item_id,)
            ).fetchone()
            if work is None or work["status"] in {"COMPLETED", "CANCELLED"}:
                raise SessionError("Choose an existing non-terminal Work Item.")
            self._slot(connection)
            connection.execute(
                """INSERT INTO agent_sessions (
                    session_id, project_id, work_item_id, provider, read_only, native_resume,
                    envelope_sha256, state, run_generation, owner_id, lease_expires_at,
                    timeout_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'STARTING', 1, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    work["project_id"],
                    work_item_id,
                    provider,
                    read_only,
                    native_resume,
                    envelope_sha256,
                    owner_id,
                    deadline,
                    timeout_seconds,
                    _timestamp(now),
                    _timestamp(now),
                ),
            )
            row = self._row(connection, session_id)
            self._event(connection, row, EventKind.SESSION_CREATED, "{}", now)
            return _session(row)

    def owned_state(self, session_id, owner_id, generation) -> Session:
        if self._store is None:
            raise ConflictError("The Agent Session ownership expired or changed.")
        with self._store._connection() as connection:
            return _session(self._owned(connection, session_id, owner_id, generation, self.now()))

    def renew(self, session_id, owner_id, generation, *, lease_seconds=30) -> Session:
        with self._write() as connection:
            now = self.now()
            row = self._owned(connection, session_id, owner_id, generation, now)
            deadline = max(row["lease_expires_at"], self._deadline(now, lease_seconds))
            connection.execute(
                "UPDATE agent_sessions SET lease_expires_at = ? WHERE session_id = ?",
                (deadline, session_id),
            )
            return _session(self._row(connection, session_id))

    def bind(self, session_id, owner_id, generation, *, envelope_sha256, native_resume) -> Session:
        _identifier(envelope_sha256, _DIGEST)
        if type(native_resume) is not bool:
            raise SessionError("The Agent Session recovery capability is invalid.")
        with self._write() as connection:
            now = self.now()
            row = self._owned(connection, session_id, owner_id, generation, now)
            if row["state"] != SessionState.STARTING:
                raise ConflictError("The Agent Session can only bind while starting.")
            if row["envelope_sha256"] not in (None, envelope_sha256):
                raise ConflictError("The Agent Session execution envelope changed.")
            if generation > 1 and not native_resume:
                raise ConflictError("Native Agent Session recovery is unavailable.")
            connection.execute(
                """UPDATE agent_sessions SET envelope_sha256 = ?, native_resume = ?, updated_at = ?
                   WHERE session_id = ?""",
                (envelope_sha256, native_resume, _timestamp(now), session_id),
            )
            return _session(self._row(connection, session_id))

    def running(
        self, session_id, owner_id, generation, *, provider_version=None, model=None
    ) -> Session:
        _optional_label(provider_version)
        _optional_label(model)
        with self._write() as connection:
            now = self.now()
            row = self._owned(connection, session_id, owner_id, generation, now)
            if row["state"] != SessionState.STARTING or row["envelope_sha256"] is None:
                raise ConflictError("The Agent Session is not waiting for a bound provider.")
            connection.execute(
                """UPDATE agent_sessions SET state = 'RUNNING', provider_version = ?, model = ?,
                   started_at = ?, updated_at = ? WHERE session_id = ?""",
                (provider_version, model, _timestamp(now), _timestamp(now), session_id),
            )
            self._event(connection, row, EventKind.SESSION_STARTED, "{}", now)
            return _session(self._row(connection, session_id))

    def observe(
        self,
        session_id,
        owner_id,
        generation,
        kind,
        payload,
        *,
        native_kind=None,
        native_session_id=None,
        usage=None,
        model=None,
    ) -> Session:
        if not isinstance(kind, str) or kind not in _OBSERVATIONS:
            raise SessionError("Unknown Agent Session observation kind.")
        encoded = _payload(payload)
        _optional_label(native_kind)
        _optional_label(model)
        if native_session_id is not None:
            _identifier(native_session_id)
        telemetry = None if usage is None else _usage(usage)
        with self._write() as connection:
            now = self.now()
            row = self._owned(connection, session_id, owner_id, generation, now)
            if native_session_id is not None and row["native_session_id"] not in (
                None,
                native_session_id,
            ):
                raise ConflictError("The provider returned another native Agent Session identity.")
            updates = {}
            if telemetry is not None:
                for key in _TOKEN_FIELDS:
                    if telemetry[key] is not None:
                        updates[key] = max(row[key] or 0, telemetry[key])
                amount, currency = telemetry["reported_cost"], telemetry["reported_cost_currency"]
                if amount is not None:
                    if row["reported_cost_currency"] not in (None, currency):
                        raise SessionError("Provider usage changed its reported currency.")
                    if row["reported_cost"] is None or Decimal(amount) >= Decimal(
                        row["reported_cost"]
                    ):
                        updates.update(reported_cost=amount, reported_cost_currency=currency)
            updates["updated_at"] = _timestamp(now)
            if model is not None:
                updates["model"] = model
            if native_session_id is not None:
                updates["native_session_id"] = native_session_id
            assignments = ", ".join(f"{key} = ?" for key in updates)
            connection.execute(
                f"UPDATE agent_sessions SET {assignments} WHERE session_id = ?",
                (*updates.values(), session_id),
            )
            self._event(connection, row, kind, encoded, now, native_kind)
            return _session(self._row(connection, session_id))

    def request_cancel(self, session_id, *, generation=None) -> Session:
        _identifier(session_id, _SESSION_ID)
        if generation is not None and (type(generation) is not int or generation < 1):
            raise SessionError("The Agent Session generation is invalid.")
        with self._write() as connection:
            now = self.now()
            row = self._row(connection, session_id)
            if (
                (generation is not None and generation != row["run_generation"])
                or row["state"] not in ACTIVE_STATES
                or row["lease_expires_at"] <= now
                or row["cleanup_unconfirmed"]
            ):
                raise ConflictError("The Agent Session is not cancellable by a live supervisor.")
            if row["state"] != SessionState.CANCELLING:
                connection.execute(
                    "UPDATE agent_sessions SET state = 'CANCELLING', updated_at = ? WHERE session_id = ?",
                    (_timestamp(now), session_id),
                )
                self._event(connection, row, EventKind.CANCEL_REQUESTED, "{}", now)
            return _session(self._row(connection, session_id))

    def _finish(self, connection, row, state, now, duration_ms, reason):
        if state == SessionState.CANCELLED and row["state"] != SessionState.CANCELLING:
            raise ConflictError("The Agent Session has no cancellation request.")
        if row["state"] == SessionState.CANCELLING and state != SessionState.INTERRUPTED:
            state = SessionState.CANCELLED
        if row["state"] == SessionState.STARTING and state == SessionState.SUCCEEDED:
            raise ConflictError("The Agent Session did not reach its running state.")
        connection.execute(
            """UPDATE agent_sessions SET state = ?, owner_id = NULL, lease_expires_at = NULL,
               updated_at = ?, finished_at = ?, duration_ms = ? WHERE session_id = ?""",
            (state, _timestamp(now), _timestamp(now), duration_ms, row["session_id"]),
        )
        event = {
            SessionState.CANCELLED: EventKind.CANCELLED,
            SessionState.TIMED_OUT: EventKind.TIMED_OUT,
            SessionState.INTERRUPTED: EventKind.INTERRUPTED,
        }.get(state, EventKind.SESSION_FINISHED)
        self._event(connection, row, event, _payload({"state": state.value, "reason": reason}), now)
        return _session(self._row(connection, row["session_id"]))

    def finish(
        self, session_id, owner_id, generation, state, *, duration_ms=None, reason=None
    ) -> Session:
        try:
            state = SessionState(state)
        except ValueError:
            raise SessionError("The Agent Session outcome is invalid.") from None
        if state not in TERMINAL_STATES:
            raise SessionError("The Agent Session outcome is invalid.")
        _amount(duration_ms)
        if reason is not None:
            _identifier(reason)
        with self._write() as connection:
            now = self.now()
            row = self._owned(connection, session_id, owner_id, generation, now)
            return self._finish(connection, row, state, now, duration_ms, reason)

    def block_reconciliation(self, session_id, owner_id, generation) -> Session:
        """Keep the active slot fenced when process cleanup cannot be proven."""
        with self._write() as connection:
            now = self.now()
            row = self._owned(connection, session_id, owner_id, generation, now, require_live=False)
            connection.execute(
                "UPDATE agent_sessions SET cleanup_unconfirmed = 1, updated_at = ? WHERE session_id = ?",
                (_timestamp(now), session_id),
            )
            self._event(connection, row, EventKind.ERROR, '{"reason":"CLEANUP_UNCONFIRMED"}', now)
            return _session(self._row(connection, session_id))

    def expired(self) -> list[SessionOwnership]:
        with self._read() as connection:
            if connection is None:
                return []
            return [
                SessionOwnership(*row)
                for row in connection.execute(
                    f"""SELECT session_id, owner_id, run_generation, lease_expires_at
                        FROM agent_sessions WHERE {_ACTIVE}
                        AND lease_expires_at <= ? AND cleanup_unconfirmed = 0""",
                    (self.now(),),
                )
            ]

    def reconcile_expired(self, session_id, *, owner_id, generation) -> Session | None:
        """Record loss only after the caller has established the owner is no longer live."""
        _identifier(session_id, _SESSION_ID)
        _identifier(owner_id)
        with self._write() as connection:
            now = self.now()
            row = self._row(connection, session_id)
            if (
                row["owner_id"] != owner_id
                or row["run_generation"] != generation
                or row["state"] not in ACTIVE_STATES
                or row["cleanup_unconfirmed"]
                or row["lease_expires_at"] > now
            ):
                return None
            return self._finish(connection, row, SessionState.INTERRUPTED, now, None, "OWNER_LOST")

    def recover(self, session_id, *, owner_id, envelope_sha256, lease_seconds=30) -> Session:
        _identifier(session_id, _SESSION_ID)
        _identifier(owner_id)
        _identifier(envelope_sha256, _DIGEST)
        with self._write() as connection:
            now = self.now()
            deadline = self._deadline(now, lease_seconds)
            row = self._row(connection, session_id)
            session = _session(row)
            if not session.recoverable or session.envelope_sha256 != envelope_sha256:
                raise ConflictError("Native Agent Session recovery is unavailable for this input.")
            work_state = connection.execute(
                "SELECT status FROM work_items WHERE work_item_id = ?", (session.work_item_id,)
            ).fetchone()
            if work_state is None or work_state[0] in {"COMPLETED", "CANCELLED"}:
                raise ConflictError(
                    "The Agent Session Work Item is no longer eligible for recovery."
                )
            if session.run_generation == _MAX_INTEGER:
                raise ConflictError("The Agent Session generation limit was reached.")
            self._slot(connection)
            connection.execute(
                """UPDATE agent_sessions SET state = 'STARTING', run_generation = run_generation + 1,
                   owner_id = ?, lease_expires_at = ?, updated_at = ?, started_at = NULL,
                   finished_at = NULL, provider_version = NULL, model = NULL,
                   input_tokens = NULL, output_tokens = NULL, cached_tokens = NULL,
                   duration_ms = NULL, reported_cost = NULL, reported_cost_currency = NULL
                   WHERE session_id = ?""",
                (owner_id, deadline, _timestamp(now), session_id),
            )
            row = self._row(connection, session_id)
            self._event(connection, row, EventKind.RECOVERY_STARTED, "{}", now)
            return _session(row)

    def get(self, session_id) -> Session:
        _identifier(session_id, _SESSION_ID)
        with self._read() as connection:
            if connection is None:
                raise SessionError("The Agent Session was not found.")
            return _session(self._row(connection, session_id))

    def list(self, *, limit=10, offset=0) -> list[Session]:
        _page(limit, offset)
        with self._read() as connection:
            if connection is None:
                return []
            return [
                _session(row)
                for row in connection.execute(
                    "SELECT * FROM agent_sessions ORDER BY created_at DESC, session_id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]

    def events(self, session_id, *, limit=10, after_sequence=0) -> list[SessionEvent]:
        _identifier(session_id, _SESSION_ID)
        _page(limit, after_sequence)
        with self._read() as connection:
            if connection is None:
                raise SessionError("The Agent Session was not found.")
            self._row(connection, session_id)
            return [
                SessionEvent(
                    session_id,
                    row["sequence"],
                    row["run_generation"],
                    EventKind(row["kind"]),
                    row["occurred_at"],
                    json.loads(row["payload"]),
                    row["native_kind"],
                )
                for row in connection.execute(
                    """SELECT * FROM agent_session_events WHERE session_id = ? AND sequence > ?
                       ORDER BY sequence LIMIT ?""",
                    (session_id, after_sequence, limit),
                )
            ]

    @staticmethod
    def snapshot_summary(connection, *, project_id=None) -> SessionSummary:
        """Compose bounded session facts in an existing project-state snapshot."""
        where = "WHERE 1 = 1" if project_id is None else "WHERE project_id = ?"
        params = () if project_id is None else (project_id,)
        total = connection.execute(
            f"SELECT COUNT(*) FROM agent_sessions {where}", params
        ).fetchone()[0]
        active = connection.execute(
            f"SELECT * FROM agent_sessions {where} AND {_ACTIVE} LIMIT 1",
            params,
        ).fetchone()
        latest = connection.execute(
            f"""SELECT * FROM agent_sessions {where} AND NOT ({_ACTIVE})
                ORDER BY finished_at DESC, session_id DESC LIMIT 1""",
            params,
        ).fetchone()
        return SessionSummary(_session(active), _session(latest), total)
