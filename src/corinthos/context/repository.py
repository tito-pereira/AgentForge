# SPDX-License-Identifier: MPL-2.0
"""Store sealed Context Projections and Session Handoffs in the project database."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from corinthos.bootstrap import _root
from corinthos.contracts import ConflictError, ContractStore, IntegrityError
from corinthos.contracts.artifacts import private_directory
from corinthos.project_status import _absolute_root

from .model import MAX_PROJECTION_BYTES, Handoff, Projection, Source, canonical_bytes

_MAX_SOURCES = 256
_PROJECTION_ORDER = "ORDER BY created_at DESC, projection_id DESC"
_HANDOFF_ORDER = "ORDER BY created_at DESC, handoff_id DESC"
_PROJECTION_COLUMNS = """projection_id, project_id, work_item_id, target_provider,
    selector_policy_version, redaction_policy_version, projection_digest, source_set_digest, created_at"""
_HANDOFF_COLUMNS = """handoff_id, project_id, work_item_id, source_session_id, run_generation,
    provider, terminal_state, event_cutoff, digest, created_at"""


def _encode(value, *, limit=MAX_PROJECTION_BYTES):
    encoded = canonical_bytes(value)
    if len(encoded) > limit:
        raise IntegrityError("Derived context exceeds its bounded storage limit.")
    return encoded.decode("utf-8")


def _decode(value, kind, *, limit=MAX_PROJECTION_BYTES):
    if type(value) is not str or len(value) > limit:
        raise IntegrityError("Stored derived context has invalid JSON.")
    try:
        parsed = json.loads(value)
    except (ValueError, RecursionError):
        raise IntegrityError("Stored derived context has invalid JSON.") from None
    if type(parsed) is not kind or _encode(parsed, limit=limit) != value:
        raise IntegrityError("Stored derived context does not match its canonical form.")
    return parsed


def _projection(row):
    if row is None:
        return None
    data = dict(row)
    data["canonical_payload"] = _decode(data["canonical_payload"], dict)
    return Projection(**data)


def _source(row):
    data = dict(row)
    del data["projection_id"]
    data["capture"] = _decode(data["capture"], dict)
    redaction = _decode(data["redaction"], list, limit=2048)
    if any(type(reason) is not str for reason in redaction):
        raise IntegrityError("Stored source redaction metadata is invalid.")
    data["redaction"] = tuple(redaction)
    return Source(**data)


def _handoff(row):
    if row is None:
        return None
    data = dict(row)
    data["canonical_payload"] = _decode(data["canonical_payload"], dict)
    return Handoff(**data)


def _page(limit, offset, *, max_limit=25):
    if (
        type(limit) is not int
        or not 1 <= limit <= max_limit
        or (type(offset) is not int or not 0 <= offset <= 1_000_000)
    ):
        raise IntegrityError("The context page is invalid.")


class ContextRepository:
    """Use the shared project store, with immutable, reproducible derived history."""

    def __init__(self, root: str | Path):
        self.root = root

    @contextmanager
    def read(self):
        root = _root(_absolute_root(self.root), missing_ok=True)
        if root is None or not os.path.lexists(root / ".corinthos"):
            yield None
            return
        with ContractStore.read_snapshot(root) as (connection, version):
            yield connection if version is not None and version >= 9 else None

    @contextmanager
    def write(self):
        root = _root(_absolute_root(self.root))
        if not (private_directory(root) / "state.db").is_file():
            raise IntegrityError("An existing Work Item is required for derived context.")
        with ContractStore(root)._transaction() as connection:
            yield connection

    @staticmethod
    def save_projection(connection, projection: Projection, sources: list[Source]) -> Projection:
        if not 1 <= len(sources) <= _MAX_SOURCES or any(
            source.ordinal != ordinal for ordinal, source in enumerate(sources)
        ):
            raise IntegrityError("Context Projection source order is invalid.")
        existing = _projection(
            connection.execute(
                "SELECT * FROM context_projections WHERE projection_digest = ?",
                (projection.projection_digest,),
            ).fetchone()
        )
        if existing is not None:
            existing_sources = ContextRepository.projection_sources(
                connection, existing.projection_id, _MAX_SOURCES + 1, 0
            )
            comparable = asdict(existing)
            comparable.update(
                projection_id=projection.projection_id, created_at=projection.created_at
            )
            if comparable != asdict(projection) or existing_sources != list(sources):
                raise ConflictError("The stored Context Projection disagrees with its digest.")
            return existing

        # The deferred FK allows inserting all immutable captures first. The
        # projection row seals that collection against any later insertion.
        connection.executemany(
            """INSERT INTO context_projection_sources (
                projection_id, ordinal, kind, authority, identity, revision, digest,
                reason, redaction, capture
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    projection.projection_id,
                    source.ordinal,
                    source.kind,
                    source.authority,
                    source.identity,
                    source.revision,
                    source.digest,
                    source.reason,
                    _encode(list(source.redaction), limit=2048),
                    _encode(source.capture),
                )
                for source in sources
            ],
        )
        data = asdict(projection)
        data["canonical_payload"] = _encode(data["canonical_payload"])
        connection.execute(
            """INSERT INTO context_projections (
                projection_id, project_id, work_item_id, target_provider, selector_policy_version,
                redaction_policy_version, canonical_payload, projection_digest, source_set_digest, created_at
            ) VALUES (
                :projection_id, :project_id, :work_item_id, :target_provider, :selector_policy_version,
                :redaction_policy_version, :canonical_payload, :projection_digest, :source_set_digest, :created_at
            )""",
            data,
        )
        return projection

    @staticmethod
    def get_projection(connection, projection_id: str) -> Projection | None:
        return _projection(
            connection.execute(
                "SELECT * FROM context_projections WHERE projection_id = ?", (projection_id,)
            ).fetchone()
        )

    @staticmethod
    def switch_projection(connection, project_id, work_item_id, target_provider, handoff_id):
        rows = connection.execute(
            """SELECT * FROM context_projections WHERE work_item_id = ? AND project_id = ?
               AND target_provider = ? AND json_extract(canonical_payload, '$.required_handoff_id') = ?
               LIMIT 2""",
            (work_item_id, project_id, target_provider, handoff_id),
        ).fetchall()
        if len(rows) > 1:
            raise IntegrityError("More than one Context Projection is bound to this switch.")
        return _projection(rows[0]) if rows else None

    @staticmethod
    def list_projections(connection, work_item_id=None, limit=10, offset=0) -> list[Projection]:
        _page(limit, offset)
        where = "" if work_item_id is None else "WHERE work_item_id = ?"
        values = () if work_item_id is None else (work_item_id,)
        return [
            _projection(row)
            for row in connection.execute(
                f"SELECT * FROM context_projections {where} {_PROJECTION_ORDER} LIMIT ? OFFSET ?",
                (*values, limit, offset),
            )
        ]

    @staticmethod
    def projection_sources(connection, projection_id, limit=10, offset=0) -> list[Source]:
        _page(limit, offset, max_limit=_MAX_SOURCES + 1)
        return [
            _source(row)
            for row in connection.execute(
                """SELECT * FROM context_projection_sources WHERE projection_id = ?
                   ORDER BY ordinal LIMIT ? OFFSET ?""",
                (projection_id, limit, offset),
            )
        ]

    @staticmethod
    def save_handoff(connection, handoff: Handoff) -> Handoff:
        existing = _handoff(
            connection.execute(
                """SELECT * FROM session_handoffs
                   WHERE source_session_id = ? AND run_generation = ? AND event_cutoff = ?""",
                (handoff.source_session_id, handoff.run_generation, handoff.event_cutoff),
            ).fetchone()
        )
        if existing is not None:
            comparable = asdict(existing)
            comparable.update(handoff_id=handoff.handoff_id, created_at=handoff.created_at)
            if comparable != asdict(handoff):
                raise ConflictError("The stored Session Handoff disagrees with its event cutoff.")
            return existing

        data = asdict(handoff)
        data["canonical_payload"] = _encode(data["canonical_payload"])
        connection.execute(
            """INSERT INTO session_handoffs (
                handoff_id, project_id, work_item_id, source_session_id, run_generation,
                provider, terminal_state, event_cutoff, canonical_payload, digest, created_at
            ) VALUES (
                :handoff_id, :project_id, :work_item_id, :source_session_id, :run_generation,
                :provider, :terminal_state, :event_cutoff, :canonical_payload, :digest, :created_at
            )""",
            data,
        )
        return handoff

    @staticmethod
    def get_handoff(connection, handoff_id: str) -> Handoff | None:
        return _handoff(
            connection.execute(
                "SELECT * FROM session_handoffs WHERE handoff_id = ?", (handoff_id,)
            ).fetchone()
        )

    @staticmethod
    def handoff_for_event(connection, session_id, generation, cutoff):
        return _handoff(
            connection.execute(
                """SELECT * FROM session_handoffs
                   WHERE source_session_id = ? AND run_generation = ? AND event_cutoff = ?""",
                (session_id, generation, cutoff),
            ).fetchone()
        )

    @staticmethod
    def list_handoffs(
        connection, work_item_id=None, session_id=None, limit=10, offset=0
    ) -> list[Handoff]:
        _page(limit, offset)
        conditions = []
        parameters = []
        for column, value in (("work_item_id", work_item_id), ("source_session_id", session_id)):
            if value is not None:
                conditions.append(f"{column} = ?")
                parameters.append(value)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        return [
            _handoff(row)
            for row in connection.execute(
                f"SELECT * FROM session_handoffs {where} {_HANDOFF_ORDER} LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            )
        ]

    @staticmethod
    def snapshot_summary(connection) -> dict:
        projection = connection.execute(
            f"SELECT {_PROJECTION_COLUMNS} FROM context_projections {_PROJECTION_ORDER} LIMIT 1"
        ).fetchone()
        handoff = connection.execute(
            f"SELECT {_HANDOFF_COLUMNS} FROM session_handoffs {_HANDOFF_ORDER} LIMIT 1"
        ).fetchone()
        return {
            "projection_count": connection.execute(
                "SELECT count(*) FROM context_projections"
            ).fetchone()[0],
            "latest_projection": dict(projection) if projection is not None else None,
            "handoff_count": connection.execute("SELECT count(*) FROM session_handoffs").fetchone()[
                0
            ],
            "latest_handoff": dict(handoff) if handoff is not None else None,
        }
