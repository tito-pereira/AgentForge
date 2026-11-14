# SPDX-License-Identifier: MPL-2.0
"""Advance a provider switch over durable session, handoff and projection records."""

from hashlib import sha256

from corinthos.adapters import SessionPlanError
from corinthos.context import ContextService, HandoffService
from corinthos.contracts import ConflictError
from corinthos.contracts.model import canonical_json
from corinthos.providers import SUPPORTED_PROVIDERS
from corinthos.work.repository import WorkRepository

from .model import ACTIVE_STATES, SessionError
from .ownership import ProjectOwnerBusy
from .repository import _ACTIVE, _MAX_INTEGER, _SESSION_ID, SessionRepository, _identifier, _session

_TARGET_STAGES = {"TARGET_SESSION_ACTIVE", "TARGET_SESSION_TERMINAL"}


def _blocked(view, reason):
    return dict(view, stage="BLOCKED", blocker=reason)


class ProviderSwitchService:
    """Derive status without probes and advance only on explicit requests."""

    def __init__(self, supervisor):
        self.supervisor = supervisor

    def _inspect(self, root, source_session_id, target_provider, source_generation):
        _identifier(source_session_id, _SESSION_ID)
        if not isinstance(target_provider, str) or target_provider not in SUPPORTED_PROVIDERS:
            raise SessionError("Select an explicit supported target provider.")
        if source_generation is not None and (
            type(source_generation) is not int or not 1 <= source_generation <= _MAX_INTEGER
        ):
            raise SessionError("Use a valid source Agent Session generation.")
        context = ContextService(root)
        repository = SessionRepository(root)
        with context.repository.read() as connection:
            if connection is None:
                raise SessionError("The source Agent Session was not found in a v9 project.")
            source = _session(repository._row(connection, source_session_id))
            if source.provider == target_provider:
                raise SessionError("The source and target providers must differ.")
            if source_generation is not None and source.run_generation != source_generation:
                raise ConflictError("The source Agent Session generation has changed.")
            handoff = projection = target = None
            work = WorkRepository(connection).row(source.work_item_id)
            if work["project_id"] != source.project_id:
                raise ConflictError("The source Agent Session has inconsistent project ownership.")
            active = connection.execute(
                f"SELECT session_id FROM agent_sessions WHERE {_ACTIVE}"
            ).fetchone()
            stage = "SOURCE_TERMINAL"
            if source.state in ACTIVE_STATES:
                stage = "STOPPING_SOURCE" if source.state == "CANCELLING" else "SOURCE_ACTIVE"
            elif not source.cleanup_unconfirmed:
                handoff = HandoffService(root).for_source(connection, source)
                if handoff is not None:
                    stage = "HANDOFF_READY"
                    projection = context.switch_projection(
                        connection,
                        source.project_id,
                        source.work_item_id,
                        target_provider,
                        handoff.handoff_id,
                    )
                    if projection is not None:
                        stage = "PROJECTION_READY"
                        target = repository.switch_target(connection, projection)
                        if target is not None:
                            stage = (
                                "TARGET_SESSION_ACTIVE"
                                if target.state in ACTIVE_STATES
                                else "TARGET_SESSION_TERMINAL"
                            )

            identity = [
                source.project_id,
                source.work_item_id,
                source.session_id,
                source.run_generation,
                target_provider,
            ]
            view = {
                "switch_key": sha256(canonical_json(identity).encode("utf-8")).hexdigest(),
                "project_id": source.project_id,
                "work_item_id": source.work_item_id,
                "source_session_id": source.session_id,
                "source_provider": source.provider,
                "source_generation": source.run_generation,
                "source_state": source.state,
                "cleanup_unconfirmed": source.cleanup_unconfirmed,
                "target_provider": target_provider,
                "stage": stage,
                "handoff_id": handoff.handoff_id if handoff else None,
                "handoff_digest": handoff.digest if handoff else None,
                "projection_id": projection.projection_id if projection else None,
                "projection_digest": projection.projection_digest if projection else None,
                "target_session_id": target.session_id if target else None,
                "target_state": target.state if target else None,
                "blocker": None,
            }
            if target is None:
                if source.cleanup_unconfirmed:
                    view = _blocked(view, "SOURCE_CLEANUP_UNCONFIRMED")
                elif work["status"] in {"COMPLETED", "CANCELLED"}:
                    view = _blocked(view, "WORK_ITEM_CLOSED")
                elif active is not None and active["session_id"] != source.session_id:
                    view = _blocked(view, "PROJECT_SESSION_ACTIVE")
                elif source.state in ACTIVE_STATES and source.lease_expires_at <= repository.now():
                    view = _blocked(view, "SOURCE_LEASE_EXPIRED")
            return source, handoff, projection, target, view

    def status(self, root, source_session_id, target_provider, source_generation=None):
        return self._inspect(root, source_session_id, target_provider, source_generation)[-1]

    def execute(self, root, source_session_id, target_provider, source_generation=None):
        source, handoff, projection, target, view = self._inspect(
            root, source_session_id, target_provider, source_generation
        )
        args = (root, source_session_id, target_provider, source.run_generation)
        if view["blocker"] == "SOURCE_LEASE_EXPIRED":
            self.supervisor.reconcile(root, source)
            source, handoff, projection, target, view = self._inspect(*args)
        if (
            target is not None
            and target.state in ACTIVE_STATES
            and not target.cleanup_unconfirmed
            and target.lease_expires_at <= SessionRepository(root).now()
        ):
            self.supervisor.reconcile(root, target)
            return self.status(*args)
        if view["stage"] in {*_TARGET_STAGES, "BLOCKED", "STOPPING_SOURCE"}:
            return view

        if source.state not in ACTIVE_STATES:
            if handoff is None:
                handoff = HandoffService(root).create(
                    source_session_id, generation=source.run_generation
                )
            if projection is None:
                projection = ContextService(root).create(
                    source.work_item_id, target_provider, required_handoff_id=handoff.handoff_id
                )
        try:
            self.supervisor.preflight(root, target_provider, read_only=source.read_only)
        except SessionPlanError as error:
            reason = (
                "TARGET_UNSUPPORTED"
                if error.error_kind == "REQUIRED_CAPABILITY_UNAVAILABLE"
                else "TARGET_UNAVAILABLE"
            )
            current = self.status(*args)
            return (
                current
                if current["stage"] in {*_TARGET_STAGES, "BLOCKED"}
                else _blocked(current, reason)
            )

        if source.state in ACTIVE_STATES:
            try:
                self.supervisor.cancel(root, source_session_id, generation=source.run_generation)
            except ConflictError:
                current = self.status(*args)
                if current["stage"] in {
                    "STOPPING_SOURCE",
                    "SOURCE_TERMINAL",
                    "HANDOFF_READY",
                    "PROJECTION_READY",
                    *_TARGET_STAGES,
                }:
                    return current
                raise
        else:
            try:
                self.supervisor.start_switch(root, source, projection, handoff)
            except ProjectOwnerBusy:
                current = self.status(*args)
                return (
                    current
                    if current["stage"] in {*_TARGET_STAGES, "BLOCKED"}
                    else _blocked(current, "PROJECT_SESSION_ACTIVE")
                )
        return self.status(*args)
