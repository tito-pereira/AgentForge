# SPDX-License-Identifier: MPL-2.0
"""Shared CLI and v2 RPC operations for supervised sessions."""

from dataclasses import asdict

from corinthos.application.workspace import DEFAULT_LIMIT, _page, _page_args
from corinthos.sessions.repository import SessionRepository
from corinthos.sessions.supervisor import SessionSupervisor
from corinthos.sessions.switch import ProviderSwitchService

_SESSION_FIELDS = (
    "session_id",
    "work_item_id",
    "project_id",
    "provider",
    "provider_version",
    "model",
    "state",
    "run_generation",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "duration_ms",
    "reported_cost",
    "reported_cost_currency",
    "timeout_seconds",
    "read_only",
    "cleanup_unconfirmed",
)


def session_view(session):
    value = {key: getattr(session, key) for key in _SESSION_FIELDS}
    value["can_cancel"] = (
        session.state in {"STARTING", "RUNNING", "CANCELLING"} and not session.cleanup_unconfirmed
    )
    value["can_recover"] = session.recoverable
    return value


class SessionApplication:
    def __init__(self, supervisor=None):
        self.supervisor = SessionSupervisor() if supervisor is None else supervisor
        self.switch = ProviderSwitchService(self.supervisor)

    def start(self, root, work_item_id, provider, **options):
        return session_view(self.supervisor.start(root, work_item_id, provider, **options))

    def get(self, root, session_id):
        return session_view(SessionRepository(root).get(session_id))

    def list(self, root, *, limit=DEFAULT_LIMIT, offset=0):
        _page_args(limit, offset)
        rows = SessionRepository(root).list(limit=limit, offset=offset)
        return _page("sessions", [session_view(row) for row in rows], limit, offset)

    def events(self, root, session_id, *, limit=DEFAULT_LIMIT, after_sequence=0):
        _page_args(limit, 0)
        if type(after_sequence) is not int or not 0 <= after_sequence <= 2**53 - 1:
            raise ValueError("Invalid session event cursor.")
        rows = SessionRepository(root).events(
            session_id, limit=min(limit, 10), after_sequence=after_sequence
        )
        return {
            "events": [asdict(row) for row in rows],
            "next_after_sequence": rows[-1].sequence if rows else after_sequence,
        }

    def cancel(self, root, session_id, *, generation=None):
        return session_view(self.supervisor.cancel(root, session_id, generation=generation))

    def recover(self, root, session_id, **options):
        return session_view(self.supervisor.recover(root, session_id, **options))

    def switch_status(self, root, source_session_id, target_provider, source_generation=None):
        return self.switch.status(root, source_session_id, target_provider, source_generation)

    def switch_execute(self, root, source_session_id, target_provider, source_generation=None):
        return self.switch.execute(root, source_session_id, target_provider, source_generation)
