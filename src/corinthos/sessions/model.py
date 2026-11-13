# SPDX-License-Identifier: MPL-2.0
"""Provider-neutral Agent Session state and durable observations."""

from dataclasses import dataclass
from enum import StrEnum

from corinthos.contracts import ContractError


class SessionState(StrEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    INTERRUPTED = "INTERRUPTED"


ACTIVE_STATES = frozenset({SessionState.STARTING, SessionState.RUNNING, SessionState.CANCELLING})
TERMINAL_STATES = frozenset(set(SessionState) - ACTIVE_STATES)


class EventKind(StrEnum):
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_STARTED = "SESSION_STARTED"
    OUTPUT = "OUTPUT"
    TOOL_ACTIVITY = "TOOL_ACTIVITY"
    USAGE = "USAGE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SESSION_FINISHED = "SESSION_FINISHED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    INTERRUPTED = "INTERRUPTED"
    RECOVERY_STARTED = "RECOVERY_STARTED"


class SessionError(ContractError):
    """Invalid Agent Session state, identifier, or observation."""


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    project_id: str
    work_item_id: str
    provider: str
    read_only: bool
    provider_version: str | None
    model: str | None
    native_session_id: str | None
    native_resume: bool
    envelope_sha256: str | None
    state: SessionState
    run_generation: int
    owner_id: str | None
    lease_expires_at: float | None
    cleanup_unconfirmed: bool
    timeout_seconds: int
    created_at: str
    started_at: str | None
    updated_at: str
    finished_at: str | None
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    duration_ms: int | None
    reported_cost: str | None
    reported_cost_currency: str | None

    @property
    def recoverable(self) -> bool:
        """Stored eligibility, subject to adapter and authority checks on explicit recovery."""
        return (
            self.state is SessionState.INTERRUPTED
            and self.native_resume
            and self.native_session_id is not None
            and self.envelope_sha256 is not None
        )


@dataclass(frozen=True, slots=True)
class SessionOwnership:
    session_id: str
    owner_id: str
    run_generation: int
    lease_expires_at: float


@dataclass(frozen=True, slots=True)
class SessionEvent:
    session_id: str
    sequence: int
    run_generation: int
    kind: EventKind
    occurred_at: str
    payload: dict
    native_kind: str | None


@dataclass(frozen=True, slots=True)
class SessionSummary:
    active: Session | None
    latest_terminal: Session | None
    total: int
