# SPDX-License-Identifier: MPL-2.0
"""Exercise process supervision behind the shared application and RPC."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
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
from corinthos.project_state import ProjectStateService
from corinthos.sessions.model import SessionError
from corinthos.sessions.repository import SessionRepository
from corinthos.sessions.supervisor import SessionSupervisor
from corinthos.work import WorkService


class SyntheticManager:
    def __init__(self, *, linger=False, resumable=True, start_gate=None):
        self.linger = linger
        self.resumable = resumable
        self.start_gate = start_gate
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
            futures = [pool.submit(s.start, a, one.work_item_id, "codex") for s in (first, second)]
            winners = []
            for future in futures:
                try:
                    winners.append(future.result())
                except ConflictError:
                    continue
        [session] = winners
        other = second.start(b, two.work_item_id, "claude", timeout_seconds=1)
        cross = second if session.owner_id != other.owner_id else first
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
