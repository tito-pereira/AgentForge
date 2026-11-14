# SPDX-License-Identifier: MPL-2.0
"""Exercise process supervision behind the shared application and RPC."""

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_application_workspace import _call, _transcript
from test_application_workspace import wire as wire

from corinthos.adapters.model import AgentResult
from corinthos.application import context, sidecar, workspace
from corinthos.application.sessions import SessionApplication
from corinthos.bootstrap import initialize
from corinthos.contracts import ConflictError, ContractStore
from corinthos.contracts import store as contract_storage
from corinthos.project_state import ProjectStateService
from corinthos.sessions import repository as session_storage
from corinthos.sessions.model import SessionError
from corinthos.sessions.repository import SessionRepository
from corinthos.sessions.supervisor import SessionSupervisor
from corinthos.work import WorkService


class SyntheticManager:
    def __init__(self, *, linger=False, resumable=True, start_gate=None, before_cleanup=None):
        self.linger = linger
        self.resumable = resumable
        self.start_gate = start_gate
        self.before_cleanup = before_cleanup
        self.selected = []
        self.resumes = []
        self.prompts = []
        self.native_id = str(uuid4())

    def session_binding(self, provider, root, *, prompt, read_only):
        return hashlib.sha256(prompt.encode()).hexdigest()

    def session_plan(self, provider, root, *, prompt, read_only, **options):
        self.selected.append(provider)
        self.prompts.append(prompt)
        return SimpleNamespace(
            capabilities=SimpleNamespace(version="1.2.3", native_resume=self.resumable),
            binding_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            provider=provider,
        )

    def run_session(
        self,
        plan,
        *,
        task_id,
        attempt_id,
        timeout,
        cancel,
        on_event,
        on_start,
        resume_session_id,
        owner_fd,
    ):
        self.resumes.append(resume_session_id)
        on_start()
        payload = {
            "input_tokens": 0,
            "output_tokens": 9,
            "reported_cost": "0.0123",
            "reported_cost_currency": "USD",
        }
        for _ in range(2):
            on_event(
                {
                    "kind": "USAGE",
                    "payload": payload,
                    "native_session_id": self.native_id,
                    "provider_type": "fixture.usage",
                    "model": "fixture-model",
                }
            )
        on_event({"kind": "OUTPUT", "payload": {"text": "Prepared fixture output."}})
        if self.start_gate is not None:
            self.start_gate.set()
        status = "COMPLETED"
        if self.linger:
            status = "CANCELLED" if cancel.wait(timeout) else "TIMEOUT"
        if status == "CANCELLED" and self.before_cleanup is not None:
            self.before_cleanup()
        return AgentResult(plan.provider, status, task_id, attempt_id)


def _project(root):
    initialize(root)
    item = WorkService(root).create(
        scope_level="TASK",
        objective="Verify ordinary local application behavior",
        acceptance_criteria=["Observe a supervised, bounded native run"],
    )
    return item


def _until(call, matches, timeout=8):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        try:
            result = call()
            if matches(result):
                return result
        except ConflictError:
            pass
        sleep(0.05)
    pytest.fail("Timed out waiting for session state.")


def test_lifecycle_and_read_only_surfaces(tmp_path):
    root = tmp_path / "workspace"
    item = _project(root)
    manager = SyntheticManager()
    supervisor = SessionSupervisor(manager_factory=lambda *args, **kwargs: manager)
    app = SessionApplication(supervisor)
    try:
        assert app.list(root)["sessions"] == [] and manager.selected == []
        active = app.start(root, item.work_item_id, "codex")
        assert active["state"] == "STARTING" and active["input_tokens"] is None
        finished = supervisor.wait(root, active["session_id"])
        assert finished.state == "SUCCEEDED"
        assert (finished.input_tokens, finished.output_tokens, finished.cached_tokens) == (
            0,
            9,
            None,
        )
        assert (finished.reported_cost, finished.reported_cost_currency) == ("0.0123", "USD")
        assert finished.model == "fixture-model"
        row = WorkService(root).get(item.work_item_id)
        assert row == item
        assert ContractStore(root).list_events() == []
        assert (
            ProjectStateService().summary(root).sessions.latest_terminal.session_id
            == finished.session_id
        )
        assert {"sessions", "context"}.isdisjoint(workspace.project_summary(root))
        assert set(manager.selected) == {"codex"}
        assert [event["kind"] for event in app.events(root, finished.session_id)["events"]] == [
            "SESSION_CREATED",
            "SESSION_STARTED",
            "USAGE",
            "USAGE",
            "OUTPUT",
            "SESSION_FINISHED",
        ]
        limited = app.events(root, finished.session_id, limit=2)
        tail = app.events(root, finished.session_id, after_sequence=limited["next_after_sequence"])
        assert limited["events"][-1]["sequence"] + 1 == tail["events"][0]["sequence"]
    finally:
        supervisor.close()


def test_one_project_writer_cross_supervisor_and_cancel(tmp_path):
    manager = SyntheticManager(linger=True)
    first = SessionSupervisor(manager_factory=lambda *args, **kwargs: manager)
    second = SessionSupervisor(manager_factory=lambda *args, **kwargs: manager)
    a, b = tmp_path / "a", tmp_path / "b"
    one, two = _project(a), _project(b)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(supervisor.start, a, one.work_item_id, "codex"): supervisor
                for supervisor in (first, second)
            }
            winners = []
            for future, supervisor in futures.items():
                try:
                    winners.append((supervisor, future.result()))
                except ConflictError:
                    continue
        [(owner, session)] = winners
        other = second.start(b, two.work_item_id, "claude", timeout_seconds=1)
        cross = second if owner is first else first
        cross.cancel(a, session.session_id, generation=session.run_generation)
        assert _until(
            lambda: SessionRepository(a).get(session.session_id),
            lambda session: session.state == "CANCELLED",
        ).finished_at
        assert second.wait(b, other.session_id).state == "TIMED_OUT"
        assert WorkService(a).get(one.work_item_id) == one
        assert WorkService(b).get(two.work_item_id) == two
    finally:
        first.close()
        second.close()


@pytest.fixture
def running_cancellation(tmp_path):
    root = tmp_path / "cancellation"
    item = _project(root)
    database = ContractStore(root).database_path
    started, stopping, confirm_cleanup = Event(), Event(), Event()

    def pause_cleanup():
        stopping.set()
        assert confirm_cleanup.wait(8)

    manager = SyntheticManager(linger=True, start_gate=started)
    previous = SessionSupervisor(manager_factory=lambda *args, **kwargs: manager)
    owner = SessionSupervisor(manager_factory=lambda *args, **kwargs: manager)
    cross = SessionSupervisor()
    repository = SessionRepository(root)
    try:
        original = previous.start(root, item.work_item_id, "codex")
        assert started.wait(8)
        assert previous.close()
        assert repository.get(original.session_id).state == "INTERRUPTED"

        started.clear()
        manager.before_cleanup = pause_cleanup
        resumed = owner.recover(root, original.session_id)
        assert started.wait(8)
        session = repository.get(resumed.session_id)
        assert session.state == "RUNNING" and session.run_generation == original.run_generation + 1
        yield SimpleNamespace(
            root=root,
            item=item,
            database=database,
            session=session,
            stale_generation=original.run_generation,
            owner=owner,
            cross=cross,
            repository=repository,
            stopping=stopping,
            confirm_cleanup=confirm_cleanup,
        )
    finally:
        confirm_cleanup.set()
        assert previous.close()
        assert owner.close()
        assert cross.close()


def _assert_cancelled(case):
    session_id = case.session.session_id
    case.confirm_cleanup.set()
    result = case.owner.wait(case.root, session_id)
    assert result.state == "CANCELLED" and result.finished_at
    assert result.owner_id is None and not result.cleanup_unconfirmed
    assert result.run_generation == case.session.run_generation
    events = case.repository.events(session_id, limit=25)
    assert [event.kind for event in events][-2:] == ["CANCEL_REQUESTED", "CANCELLED"]
    assert [event.kind for event in events].count("CANCEL_REQUESTED") == 1
    assert all(event.run_generation == result.run_generation for event in events[-2:])
    assert WorkService(case.root).get(case.item.work_item_id) == case.item


def test_cancel_retries_real_short_contention_and_waits_for_cleanup(
    running_cancellation, monkeypatch
):
    case = running_cancellation
    session_id = case.session.session_id
    generation = case.session.run_generation
    retry_delays = []
    with closing(sqlite3.connect(case.database, autocommit=True)) as writer:
        writer.execute("BEGIN IMMEDIATE")

        def release_after_busy(delay):
            retry_delays.append(delay)
            assert writer.in_transaction
            writer.execute("ROLLBACK")

        monkeypatch.setattr(session_storage, "sleep", release_after_busy)
        requested = case.cross.cancel(case.root, session_id, generation=generation)

    assert retry_delays == [session_storage._CANCEL_RETRY_DELAYS[0]]
    assert case.stopping.wait(8)
    assert requested.state == "CANCELLING" and requested.finished_at is None
    assert requested.owner_id == case.session.owner_id and requested.run_generation == generation
    assert case.repository.get(session_id) == requested
    with pytest.raises(ConflictError, match="not cancellable"):
        case.cross.cancel(case.root, session_id, generation=case.stale_generation)
    assert case.cross.cancel(case.root, session_id, generation=generation) == requested
    assert retry_delays == [session_storage._CANCEL_RETRY_DELAYS[0]]
    _assert_cancelled(case)


def test_cancel_exhausts_real_contention_without_persisting_a_request(
    running_cancellation, monkeypatch
):
    case = running_cancellation
    session_id = case.session.session_id
    generation = case.session.run_generation
    retry_delays = []

    def observe_delay(delay):
        retry_delays.append(delay)
        sleep(delay)

    monkeypatch.setattr(session_storage, "sleep", observe_delay)
    with closing(sqlite3.connect(case.database, autocommit=True)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        started = monotonic()
        with pytest.raises(ConflictError, match="database is busy"):
            case.cross.cancel(case.root, session_id, generation=generation)
        elapsed = monotonic() - started
        assert writer.in_transaction
        writer.execute("ROLLBACK")

    assert retry_delays == list(session_storage._CANCEL_RETRY_DELAYS)
    assert elapsed < 7
    assert case.repository.get(session_id).state == "RUNNING"
    assert not case.stopping.is_set()
    assert all(
        event.kind != "CANCEL_REQUESTED" for event in case.repository.events(session_id, limit=25)
    )

    requested = case.cross.cancel(case.root, session_id, generation=generation)
    assert requested.state == "CANCELLING" and requested.finished_at is None
    assert case.stopping.wait(8)
    assert retry_delays == list(session_storage._CANCEL_RETRY_DELAYS)
    _assert_cancelled(case)


def test_cancel_does_not_retry_when_a_reader_blocks_commit(running_cancellation, monkeypatch):
    case = running_cancellation
    session_id = case.session.session_id
    retry_delays, writes = [], []
    record_event = SessionRepository._event

    monkeypatch.setattr(contract_storage, "_LOCK_TIMEOUT", 0.05)
    monkeypatch.setattr(session_storage, "sleep", retry_delays.append)
    with closing(sqlite3.connect(case.database, autocommit=True)) as reader:
        reader.row_factory = sqlite3.Row

        def hold_reader_after_write(connection, row, kind, payload, now, native_kind=None):
            record_event(connection, row, kind, payload, now, native_kind)
            if kind == "CANCEL_REQUESTED":
                writes.append(SessionRepository._row(connection, session_id)["state"])
                reader.execute("BEGIN")
                assert SessionRepository._row(reader, session_id)["state"] == "RUNNING"

        monkeypatch.setattr(SessionRepository, "_event", staticmethod(hold_reader_after_write))
        with pytest.raises(ConflictError, match="database is busy"):
            case.cross.cancel(case.root, session_id, generation=case.session.run_generation)
        reader.execute("ROLLBACK")

    assert writes == ["CANCELLING"] and retry_delays == []
    assert case.repository.get(session_id).state == "RUNNING"
    assert not case.stopping.is_set()
    assert all(
        event.kind != "CANCEL_REQUESTED" for event in case.repository.events(session_id, limit=25)
    )


def test_explicit_native_recovery_uses_same_work_and_binding(tmp_path):
    root = tmp_path / "workspace"
    item = _project(root)
    running = Event()
    manager = SyntheticManager(linger=True, start_gate=running)
    owner = SessionSupervisor(manager_factory=lambda *args, **kwargs: manager)
    initial = owner.start(root, item.work_item_id, "codex", instruction="Original task")
    assert running.wait(8)
    assert owner.close()
    repo = SessionRepository(root)
    broken = repo.get(initial.session_id)
    assert broken.state == "INTERRUPTED" and broken.recoverable
    old = context.context_for_session(root, initial.session_id)["projection"]
    assert old["projection_id"] == broken.context_projection_id
    assert old["projection_digest"] in manager.prompts[0]
    assert "OPERATIONAL" in manager.prompts[0]
    WorkService(root).update(item.work_item_id, objective="Revised operational objective")
    new = context.context_create(root, item.work_item_id, "codex")
    assert new["projection_digest"] != old["projection_digest"]
    assert (
        old["projection_digest"]
        == context.context_verify(root, old["projection_id"])["projection_digest"]
    )

    manager.linger = False
    later = SessionSupervisor(manager_factory=lambda *args, **kwargs: manager)
    try:
        mismatch = later.recover(root, initial.session_id, instruction="Changed task")
        assert mismatch.run_generation == 2
        assert later.wait(root, initial.session_id).state == "INTERRUPTED"
        assert manager.resumes == [None]
        resumed = later.recover(root, initial.session_id, instruction="Original task")
        assert resumed.run_generation == 3
        assert later.wait(root, initial.session_id).state == "SUCCEEDED"
        assert manager.resumes == [None, manager.native_id]
        assert manager.selected == ["codex", "codex"]
        assert manager.prompts[0] == manager.prompts[1]
        assert context.context_for_session(root, initial.session_id)["projection"] == old
        with pytest.raises(SessionError):
            later.recover(root, initial.session_id)
        assert later.wait(root, initial.session_id).context_projection_id == old["projection_id"]
        fresh = later.start(root, item.work_item_id, "codex")
        assert later.wait(root, fresh.session_id).state == "SUCCEEDED"
        fresh_projection = context.context_for_session(root, fresh.session_id)["projection"]
        assert fresh_projection["projection_digest"] != old["projection_digest"]
        assert fresh_projection["projection_digest"] in manager.prompts[-1]
        assert "Revised operational objective" in manager.prompts[-1]
    finally:
        later.close()


def test_additive_rpc_old_summary_and_shutdown(tmp_path, monkeypatch, wire):
    supplied = SyntheticManager(linger=True)
    supervisor = SessionSupervisor(manager_factory=lambda *args, **kwargs: supplied)
    monkeypatch.setattr(sidecar, "SessionApplication", lambda: SessionApplication(supervisor))
    root = str(tmp_path / "rpc")
    work = _project(root)
    before = _transcript(
        [
            _call("system.handshake", 1, protocol_version=1),
            _call("session.list", 2, root=root),
            _call("system.shutdown", 3),
        ]
    )
    assert before[2]["error"]["code"] == -32601
    assert supplied.selected == []

    frontend = SessionSupervisor(manager_factory=lambda *args, **kwargs: supplied)
    monkeypatch.setattr(sidecar, "SessionApplication", lambda: SessionApplication(frontend))
    requests = [
        _call("system.handshake", 1, protocol_version=2),
        _call("project.summary", 2, root=root),
        _call("session.start", 3, root=root, work_item_id=work.work_item_id, provider="codex"),
        _call("session.list", 4, root=root),
        _call("system.shutdown", 5),
    ]
    results = _transcript(requests)
    schemas = [
        "handshake-result",
        "project-summary-result",
        "session-result",
        "session-list-result",
        "shutdown-result",
    ]
    for request, response, schema in zip(requests, results[1:-1], schemas, strict=True):
        wire("request", request)
        wire("response", response)
        wire(schema, response["result"])
    assert "session.start" in results[1]["result"]["methods"]
    assert "sessions" not in results[2]["result"]
    assert [row["method"] for row in results if "method" in row] == [
        "system.ready",
        "system.stopping",
    ]
    session_id = results[3]["result"]["session_id"]
    assert SessionRepository(root).get(session_id).state == "INTERRUPTED"

    followup = SessionSupervisor(manager_factory=lambda *args, **kwargs: supplied)
    monkeypatch.setattr(sidecar, "SessionApplication", lambda: SessionApplication(followup))
    results = _transcript(
        [
            _call("system.handshake", 1, protocol_version=2),
            _call("session.events", 2, root=root, session_id=session_id),
        ]
    )
    wire("session-events-result", results[2]["result"])
    assert results[2]["result"]["events"][-1]["kind"] == "INTERRUPTED"
