# SPDX-License-Identifier: MPL-2.0
"""Verify switch checkpoints, failure paths and the additive application wire."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from jsonschema import ValidationError
from test_application_workspace import _call, _transcript
from test_application_workspace import wire as wire
from test_session_supervisor import SyntheticManager, _project

from corinthos.adapters import SessionPlanError
from corinthos.cli import main
from corinthos.context import ContextService, HandoffService
from corinthos.contracts import ConflictError
from corinthos.sessions.model import SessionError
from corinthos.sessions.repository import SessionRepository
from corinthos.sessions.supervisor import SessionSupervisor
from corinthos.sessions.switch import ProviderSwitchService
from corinthos.work import WorkService


class SwitchManager(SyntheticManager):
    unavailable = False
    fail_target_task = False

    def session_plan(self, provider, root, **options):
        if provider == "claude" and (
            self.unavailable or (self.fail_target_task and options["prepare"])
        ):
            raise SessionPlanError("EXECUTABLE_UNAVAILABLE")
        return super().session_plan(provider, root, **options)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "switch"
    return str(root), _project(root), SessionRepository(root)


def _source(repository, work, *, terminal=True, cleanup=True, clock=None):
    if clock is not None:
        repository = SessionRepository(repository.root, clock=lambda: clock)
    source = repository.create(
        work.work_item_id,
        provider="codex",
        owner_id="test-owner",
        timeout_seconds=20,
        envelope_sha256="a" * 64,
        read_only=True,
    )
    fence = (source.session_id, source.owner_id, source.run_generation)
    repository.running(*fence)
    repository.observe(*fence, "OUTPUT", {"text": "Continue the observed checkpoint."})
    if not cleanup:
        repository.block_reconciliation(*fence)
    elif terminal:
        repository.finish(*fence, "SUCCEEDED")
    return repository.get(source.session_id)


def test_restart_from_cancellation_waits_for_cleanup_and_never_repeats_event(project):
    root, work, repository = project
    started, stopping, confirm = Event(), Event(), Event()

    def pause_cleanup():
        stopping.set()
        assert confirm.wait(8)

    manager = SwitchManager(linger=True, start_gate=started, before_cleanup=pause_cleanup)

    def factory(*args, **kw):
        return manager

    owner = SessionSupervisor(manager_factory=factory)
    client = SessionSupervisor(manager_factory=factory)
    restarted = SessionSupervisor(manager_factory=factory)
    try:
        source = owner.start(root, work.work_item_id, "codex", timeout_seconds=20)
        assert started.wait(8)
        args = (root, source.session_id, "claude", source.run_generation)
        service = ProviderSwitchService(client)
        baseline = repository.get(source.session_id)
        manager.unavailable = True
        assert service.execute(*args)["blocker"] == "TARGET_UNAVAILABLE"
        assert repository.get(source.session_id) == baseline
        assert not HandoffService(root).list()
        assert len(ContextService(root).list()) == len(repository.list()) == 1
        manager.unavailable = False
        assert service.execute(*args)["stage"] == "STOPPING_SOURCE"
        assert stopping.wait(8)
        assert client.close()
        service = ProviderSwitchService(restarted)
        assert service.status(*args)["stage"] == "STOPPING_SOURCE"
        assert service.execute(*args)["stage"] == "STOPPING_SOURCE"
        assert manager.selected.count("claude") == 1
        assert not HandoffService(root).list()
        assert len(repository.list()) == 1
        assert sum(e.kind == "CANCEL_REQUESTED" for e in repository.events(source.session_id)) == 1
        confirm.set()
        assert owner.wait(root, source.session_id).state == "CANCELLED"
        manager.linger = False
        result = service.execute(*args)
        assert restarted.wait(root, result["target_session_id"]).state == "SUCCEEDED"
        assert WorkService(root).get(work.work_item_id) == work
    finally:
        confirm.set()
        assert owner.close() and client.close() and restarted.close()


@pytest.mark.parametrize("stage", ["SOURCE_TERMINAL", "HANDOFF_READY", "PROJECTION_READY"])
def test_restart_replays_terminal_handoff_and_projection(project, stage):
    root, work, repository = project
    source = _source(repository, work)
    handoffs = HandoffService(root)
    context = ContextService(root)
    handoff = projection = None
    if stage in {"HANDOFF_READY", "PROJECTION_READY"}:
        handoff = handoffs.create(source.session_id)
    if stage == "PROJECTION_READY":
        projection = context.create(
            work.work_item_id, "claude", required_handoff_id=handoff.handoff_id
        )
        work = WorkService(root).update(
            work.work_item_id, objective="Edited after durable projection."
        )

    manager = SwitchManager()
    first = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    second = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    args = (root, source.session_id, "claude", source.run_generation)
    try:
        assert ProviderSwitchService(first).status(*args)["stage"] == stage
        assert not manager.selected
        assert first.close()
        service = ProviderSwitchService(second)
        result = service.execute(*args)
        target = second.wait(root, result["target_session_id"])
        assert target.state == "SUCCEEDED"
        assert target.session_id != source.session_id
        assert target.read_only and target.timeout_seconds == source.timeout_seconds
        assert target.work_item_id == work.work_item_id
        assert target.context_projection_id == result["projection_id"]
        assert manager.resumes == [None]
        assert repository.get(source.session_id) == source
        assert len(handoffs.list()) == len(context.list()) == 1
        if handoff is not None:
            assert result["handoff_id"] == handoff.handoff_id
        if projection is not None:
            assert result["projection_id"] == projection.projection_id
        assert service.execute(*args)["target_session_id"] == target.session_id
        assert len(repository.list()) == 2
    finally:
        assert first.close() and second.close()


def test_restart_after_orphaned_target_insert_reconciles_same_row(project):
    root, work, repository = project
    source = _source(repository, work)
    handoff = HandoffService(root).create(source.session_id)
    projection = ContextService(root).create(
        work.work_item_id, "claude", required_handoff_id=handoff.handoff_id
    )
    target = SessionRepository(root, clock=lambda: 1000.0).create(
        work.work_item_id,
        provider="claude",
        owner_id="lost-supervisor",
        timeout_seconds=20,
        context_projection_id=projection.projection_id,
    )
    manager = SwitchManager()
    restarted = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    try:
        args = (root, source.session_id, "claude", source.run_generation)
        service = ProviderSwitchService(restarted)
        assert service.status(*args)["target_state"] == "STARTING"
        assert repository.get(target.session_id) == target
        result = service.execute(*args)
        assert result["stage"] == "TARGET_SESSION_TERMINAL"
        assert result["target_state"] == "INTERRUPTED"
        assert result["target_session_id"] == target.session_id
        assert service.execute(*args) == result
        assert len(repository.list()) == 2 and not manager.selected
        assert repository.get(source.session_id) == source
    finally:
        assert restarted.close()


def test_target_unavailable_then_launch_failure_is_replayed_without_new_target(project):
    root, work, repository = project
    source = _source(repository, work)
    manager = SwitchManager()
    supervisor = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    service = ProviderSwitchService(supervisor)
    args = (root, source.session_id, "claude", 1)
    try:
        manager.unavailable = True
        blocked = service.execute(*args)
        assert blocked["blocker"] == "TARGET_UNAVAILABLE"
        assert blocked["projection_id"] and blocked["handoff_id"]
        assert len(repository.list()) == 1
        assert service.status(*args)["stage"] == "PROJECTION_READY"
        manager.unavailable = False
        manager.fail_target_task = True
        result = service.execute(*args)
        target = supervisor.wait(root, result["target_session_id"])
        assert target.state == "FAILED"
        done = service.execute(*args)
        assert done["target_session_id"] == target.session_id
        assert done["projection_id"] == blocked["projection_id"]
        assert done["handoff_id"] == blocked["handoff_id"]
        assert len(repository.list()) == 2 and repository.get(source.session_id) == source
    finally:
        assert supervisor.close()


def test_concurrent_terminal_replay_has_one_target(project):
    root, work, repository = project
    source = _source(repository, work)
    manager = SwitchManager()
    supervisors = [SessionSupervisor(manager_factory=lambda *args, **kw: manager) for _ in range(2)]
    args = (root, source.session_id, "claude", 1)
    try:
        services = [ProviderSwitchService(supervisor) for supervisor in supervisors]
        with ThreadPoolExecutor() as pool:
            list(pool.map(lambda service: service.execute(*args), services))
        views = [service.execute(*args) for service in services]
        assert views[0]["target_session_id"] == views[1]["target_session_id"]
        assert views[0]["target_session_id"] is not None and len(repository.list()) == 2
    finally:
        assert all(supervisor.close() for supervisor in supervisors)


def test_switch_never_sends_a_source_native_identity_echoed_in_an_observation(project):
    root, work, repository = project
    source = _source(repository, work, terminal=False)
    native_id = "a223a713-a8a6-44b3-9168-1a3a2a5ce401"
    fence = (source.session_id, source.owner_id, source.run_generation)
    repository.observe(
        *fence,
        "OUTPUT",
        {"text": f"Provider echoed {native_id.upper()}"},
        native_session_id=native_id,
    )
    repository.finish(*fence, "SUCCEEDED")
    manager = SwitchManager()
    supervisor = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    try:
        with pytest.raises(SessionError, match="source native identity"):
            ProviderSwitchService(supervisor).execute(root, source.session_id, "claude", 1)
        assert len(repository.list()) == 1 and not manager.resumes
        assert manager.prompts == ["Verify native session capabilities."]
    finally:
        assert supervisor.close()


def test_expired_source_is_reconciled_and_uncertain_cleanup_blocks(project):
    root, work, repository = project
    source = _source(repository, work, terminal=False, clock=1000.0)
    manager = SwitchManager()
    manager.unavailable = True
    supervisor = SessionSupervisor(manager_factory=lambda *args, **kw: manager)
    service = ProviderSwitchService(supervisor)
    try:
        args = (root, source.session_id, "claude", 1)
        assert service.status(*args)["blocker"] == "SOURCE_LEASE_EXPIRED"
        assert repository.get(source.session_id) == source
        result = service.execute(*args)
        assert result["source_state"] == "INTERRUPTED" and result["handoff_id"]
        assert result["target_session_id"] is None
        uncertain = _source(repository, work, cleanup=False)
        assert service.execute(root, uncertain.session_id, "claude")["blocker"] == (
            "SOURCE_CLEANUP_UNCONFIRMED"
        )
        assert service.execute(*args)["blocker"] == "PROJECT_SESSION_ACTIVE"
        assert repository.get(uncertain.session_id) == uncertain
        assert not manager.selected
    finally:
        assert supervisor.close()


def test_v2_mutation_id_and_passive_status_with_cli(project, wire, capsys):
    root, work, repository = project
    source = _source(repository, work)
    params = dict(root=root, source_session_id=source.session_id, target_provider="claude")
    status = _call("switch.status", 2, **params)
    notification = _call("switch.execute", None, **params)
    messages = _transcript(
        [
            _call("system.handshake", 1, protocol_version=2),
            status,
            notification,
            _call("system.shutdown", 3),
        ]
    )
    assert {"switch.status", "switch.execute"} <= set(messages[1]["result"]["methods"])
    wire("request", status)
    wire("request", _call("switch.execute", 4, **params, source_generation=1))
    with pytest.raises(ValidationError):
        wire("request", notification)
    assert messages[2]["result"]["stage"] == "SOURCE_TERMINAL"
    wire("switch-result", messages[2]["result"])
    assert len(messages) == 5 and not HandoffService(root).list()
    legacy = _transcript([_call("system.handshake", 1, protocol_version=1), status])
    assert legacy[2]["error"]["code"] == -32601
    assert (
        main(
            [
                "switch",
                "status",
                "--root",
                root,
                "--session",
                source.session_id,
                "--provider",
                "claude",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == messages[2]["result"]
    service = ProviderSwitchService(None)
    with pytest.raises(SessionError):
        service.status(root, source.session_id, "codex")
    with pytest.raises(ConflictError):
        service.status(root, source.session_id, "claude", 2)
