# SPDX-License-Identifier: MPL-2.0
"""Freeze local observed Agent Session evidence at a stable generation and cutoff."""

from datetime import UTC, datetime
from uuid import uuid4

from corinthos.sessions.model import TERMINAL_STATES

from .index import session_events, session_facts
from .model import (
    MAX_HANDOFF_BYTES,
    REDACTION_POLICY_VERSION,
    ContextError,
    Handoff,
    canonical_bytes,
    digest,
)
from .projection import identifier, page
from .redaction import redact, sanitize_text

_TERMINAL_EVENT = {
    "CANCELLED": "CANCELLED",
    "TIMED_OUT": "TIMED_OUT",
    "INTERRUPTED": "INTERRUPTED",
    "FAILED": "SESSION_FINISHED",
    "SUCCEEDED": "SESSION_FINISHED",
}


def verify_handoff(handoff):
    payload = handoff.canonical_payload
    try:
        session = payload["source_session"]
        events = payload["observations"]
        if (
            digest(payload) != handoff.digest
            or len(canonical_bytes(payload)) > MAX_HANDOFF_BYTES
            or payload["authority"] != "DERIVED"
            or payload["project_id"] != handoff.project_id
            or session["session_id"] != handoff.source_session_id
            or session["work_item_id"] != handoff.work_item_id
            or session["provider"] != handoff.provider
            or session["state"] != handoff.terminal_state
            or session["run_generation"] != handoff.run_generation
            or payload["event_cutoff"] != handoff.event_cutoff
            or not events
            or events[-1]["sequence"] != handoff.event_cutoff
            or events[-1]["kind"] != _TERMINAL_EVENT[handoff.terminal_state]
        ):
            raise ContextError("Stored Session Handoff failed verification.")
    except (KeyError, TypeError, AttributeError, IndexError):
        raise ContextError("Stored Session Handoff failed verification.") from None
    return handoff


class HandoffService:
    """Record and inspect a derived handoff without writing source state."""

    def __init__(self, root):
        from .repository import ContextRepository

        self.repository = ContextRepository(root)

    def create(self, session_id):
        identifier(session_id, "Agent Session")
        with self.repository.write() as connection:
            session = connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if session is None:
                raise ContextError("The Agent Session was not found.")
            if session["state"] not in TERMINAL_STATES or session["cleanup_unconfirmed"]:
                raise ContextError("A Session Handoff requires a stable terminal Agent Session.")
            for name in ("session_id", "work_item_id", "project_id", "provider"):
                if sanitize_text(session[name]) != session[name]:
                    raise ContextError("The Agent Session identity is not admissible as Context.")
            recorded = session_events(connection, session_id, session["run_generation"], 12)
            if not recorded or recorded[-1]["kind"] != _TERMINAL_EVENT[session["state"]]:
                raise ContextError("A Session Handoff requires a recorded terminal event.")
            cutoff = recorded[-1]["sequence"]
            payload, redactions = redact(
                {
                    "authority": "DERIVED",
                    "project_id": session["project_id"],
                    "source_session": session_facts(session),
                    "event_cutoff": cutoff,
                    "redaction_policy_version": REDACTION_POLICY_VERSION,
                    "observations": recorded,
                },
            )
            payload["redaction"] = list(redactions)
            while (
                len(payload["observations"]) > 1
                and len(canonical_bytes(payload)) > MAX_HANDOFF_BYTES
            ):
                del payload["observations"][0]
            if len(canonical_bytes(payload)) > MAX_HANDOFF_BYTES:
                raise ContextError("The terminal Session Handoff exceeds its capture budget.")
            record = Handoff(
                "handoff-" + uuid4().hex,
                session["project_id"],
                session["work_item_id"],
                session_id,
                session["run_generation"],
                session["provider"],
                session["state"],
                cutoff,
                payload,
                digest(payload),
                datetime.now(UTC).isoformat(),
            )
            return verify_handoff(self.repository.save_handoff(connection, record))

    def get(self, handoff_id):
        identifier(handoff_id, "Session Handoff")
        with self.repository.read() as connection:
            record = (
                self.repository.get_handoff(connection, handoff_id)
                if connection is not None
                else None
            )
            if record is None:
                raise ContextError("The Session Handoff was not found.")
            return verify_handoff(record)

    def list(self, work_item_id=None, session_id=None, *, limit=10, offset=0):
        if work_item_id is not None:
            identifier(work_item_id, "Work Item")
        if session_id is not None:
            identifier(session_id, "Agent Session")
        page(limit, offset)
        with self.repository.read() as connection:
            if connection is None:
                return []
            return [
                verify_handoff(record)
                for record in self.repository.list_handoffs(
                    connection,
                    work_item_id=work_item_id,
                    session_id=session_id,
                    limit=limit,
                    offset=offset,
                )
            ]
