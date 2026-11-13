# SPDX-License-Identifier: MPL-2.0
"""Exercise fenced Agent Session transactions independently of provider execution."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from corinthos.bootstrap import initialize
from corinthos.contracts import ConflictError, ContractStore
from corinthos.sessions.model import EventKind, SessionError, SessionState
from corinthos.sessions.repository import SessionRepository
from corinthos.work import WorkService

_BINDING = "d" * 64
_NATIVE = "native-session-1"


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "project"
    initialize(root)
    work = WorkService(root)
    item = work.create(scope_level="TASK", objective="Check state", acceptance_criteria=["Saved"])
    clock = [100.0]
    repo = SessionRepository(root, clock=lambda: clock[0])
    return root, item, repo, clock


def _create(repo, item, owner="first-owner", **options):
    return repo.create(
        item.work_item_id, provider="test-provider", owner_id=owner, timeout_seconds=5, **options
    )


def _running(repo, item):
    session = _create(repo, item)
    fence = session.session_id, session.owner_id, session.run_generation
    repo.bind(*fence, envelope_sha256=_BINDING, native_resume=True)
    return repo.running(*fence, provider_version="9.8.7"), fence


def test_lifecycle_events_and_cancellation_do_not_edit_work(setup):
    root, item, repo, _ = setup
    running, fence = _running(repo, item)
    assert running.state == SessionState.RUNNING
    assert running.started_at and running.finished_at is None
    assert running.input_tokens is None and running.reported_cost is None
    repo.observe(*fence, EventKind.OUTPUT, {"text": "fixture"}, native_kind="fixture.output")
    second = SessionRepository(root, clock=repo.now)
    requested = second.request_cancel(running.session_id, generation=1)
    assert requested.state == SessionState.CANCELLING and requested.finished_at is None
    assert repo.owned_state(*fence) == requested
    assert second.request_cancel(running.session_id) == requested
    result = repo.finish(*fence, SessionState.SUCCEEDED, duration_ms=0)
    assert result.state == SessionState.CANCELLED and result.finished_at is not None
    assert result.duration_ms == 0 and result.owner_id is None
    assert second.get(running.session_id) == result and second.list() == [result]
    assert WorkService(root).get(item.work_item_id) == item
    events = repo.events(result.session_id, limit=5)
    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    assert [event.kind for event in events] == [
        EventKind.SESSION_CREATED,
        EventKind.SESSION_STARTED,
        EventKind.OUTPUT,
        EventKind.CANCEL_REQUESTED,
        EventKind.CANCELLED,
    ]
    assert repo.events(result.session_id, limit=2, after_sequence=3) == events[-2:]
    assert events[2].native_kind == "fixture.output"


def test_ownership_and_explicit_same_session_recovery(setup):
    _, item, repo, clock = setup
    running, fence = _running(repo, item)
    repo.observe(*fence, EventKind.OUTPUT, {}, native_session_id=_NATIVE)
    clock[0] += 31
    assert repo.expired()[0].session_id == running.session_id
    for operation in (lambda: repo.renew(*fence), lambda: repo.finish(*fence, "FAILED")):
        with pytest.raises(ConflictError):
            operation()
    with pytest.raises(ConflictError, match="active"):
        _create(repo, item, "second-owner")
    assert repo.reconcile_expired(running.session_id, owner_id="wrong", generation=1) is None
    interrupted = repo.reconcile_expired(running.session_id, owner_id=fence[1], generation=fence[2])
    assert interrupted.recoverable and interrupted.state == SessionState.INTERRUPTED
    with pytest.raises(ConflictError):
        repo.recover(running.session_id, owner_id="second-owner", envelope_sha256="e" * 64)
    recovered = repo.recover(running.session_id, owner_id="second-owner", envelope_sha256=_BINDING)
    assert recovered.state == SessionState.STARTING and recovered.run_generation == 2
    assert recovered.work_item_id == running.work_item_id and recovered.provider == running.provider
    assert recovered.native_session_id == _NATIVE
    with pytest.raises(ConflictError):
        repo.renew(*fence)
    with pytest.raises(ConflictError):
        repo.request_cancel(running.session_id, generation=1)
    new_fence = recovered.session_id, recovered.owner_id, recovered.run_generation
    repo.bind(*new_fence, envelope_sha256=_BINDING, native_resume=True)
    repo.running(*new_fence)
    with pytest.raises(ConflictError):
        repo.observe(*new_fence, EventKind.OUTPUT, {}, native_session_id="wrong-native")
    assert repo.finish(*new_fence, "SUCCEEDED").state == SessionState.SUCCEEDED
    history = repo.events(running.session_id, limit=25)
    assert [event.run_generation for event in history[-3:]] == [2, 2, 2]


def test_cleanup_uncertainty_keeps_writer_slot_and_unsupported_recovery_is_explicit(setup):
    _, item, repo, clock = setup
    interrupted = _create(repo, item)
    interrupted = repo.finish(interrupted.session_id, interrupted.owner_id, 1, "INTERRUPTED")
    assert not interrupted.recoverable
    with pytest.raises(ConflictError):
        repo.recover(interrupted.session_id, owner_id="second-owner", envelope_sha256=_BINDING)
    running, fence = _running(repo, item)
    clock[0] += 31
    flagged = repo.block_reconciliation(*fence)
    assert flagged.cleanup_unconfirmed
    assert repo.expired() == []
    assert repo.reconcile_expired(running.session_id, owner_id=fence[1], generation=1) is None
    with pytest.raises(ConflictError, match="active"):
        _create(repo, item, "second-owner")
    assert repo.events(running.session_id, limit=25)[-1].payload == {
        "reason": "CLEANUP_UNCONFIRMED"
    }


def test_cumulative_usage_keeps_zero_unknown_and_exact_decimal(setup):
    _, item, repo, _ = setup
    _, fence = _running(repo, item)
    cost = "123456789012345678901234567890.123456789012345678901234567890"
    expected = "123456789012345678901234567890.12345678901234567890123456789"
    for usage in (
        {
            "input_tokens": 0,
            "output_tokens": 9,
            "reported_cost": cost,
            "reported_cost_currency": "USD",
        },
        {
            "input_tokens": 0,
            "output_tokens": 9,
            "reported_cost": cost,
            "reported_cost_currency": "USD",
        },
        {"output_tokens": 8},
    ):
        observed = repo.observe(*fence, EventKind.USAGE, {}, usage=usage, model="known-model")
    assert (observed.input_tokens, observed.output_tokens, observed.cached_tokens) == (0, 9, None)
    assert (observed.reported_cost, observed.reported_cost_currency) == (expected, "USD")
    assert observed.model == "known-model"
    for payload, usage in (
        ({"text": "A" * 4096}, None),
        ({}, {"input_tokens": True}),
        ({}, {"reported_cost": "1.2", "reported_cost_currency": "JPY"}),
        ({}, {"reported_cost": 1.2, "reported_cost_currency": "USD"}),
    ):
        with pytest.raises(SessionError):
            repo.observe(*fence, EventKind.USAGE, payload, usage=usage)
    assert repo.get(fence[0]) == observed
    assert len(repo.events(fence[0])) == 5


def test_sqlite_retains_identity_terminal_sessions_and_append_only_events(setup):
    root, item, repo, _ = setup
    _, fence = _running(repo, item)
    with ContractStore(root)._transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE agent_sessions SET work_item_id = 'another' WHERE session_id = ?",
                (fence[0],),
            )
        for sql in (
            "UPDATE agent_session_events SET payload = '{}' WHERE session_id = ?",
            "DELETE FROM agent_session_events WHERE session_id = ?",
            """INSERT OR REPLACE INTO agent_session_events
               SELECT * FROM agent_session_events WHERE session_id = ?""",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql, (fence[0],))
    assert repo.finish(*fence, "TIMED_OUT").state == SessionState.TIMED_OUT
    with ContractStore(root)._transaction() as connection:
        for sql in (
            "UPDATE agent_sessions SET state = 'FAILED' WHERE session_id = ?",
            "DELETE FROM agent_sessions WHERE session_id = ?",
            """INSERT OR REPLACE INTO agent_sessions
               SELECT * FROM agent_sessions WHERE session_id = ?""",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql, (fence[0],))


def test_concurrent_claims_are_one_per_root_and_independent_across_roots(setup, tmp_path):
    root, item, repo, _ = setup
    peers = (SessionRepository(root, clock=repo.now), SessionRepository(root, clock=repo.now))
    gate = Barrier(2)

    def claim(index):
        gate.wait(timeout=5)
        try:
            return _create(peers[index], item, owner=f"owner-{index}")
        except ConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(result is not None for result in pool.map(claim, [0, 1])) == 1
    different = tmp_path / "second"
    initialize(different)
    work = WorkService(different)
    other_item = work.create(scope_level="TASK", objective="Other", acceptance_criteria=["Tracked"])
    other_repo = SessionRepository(different, clock=repo.now)
    with pytest.raises(SessionError):
        _create(other_repo, item)
    other = _create(other_repo, other_item)
    assert other.state == SessionState.STARTING
    assert repo.list()[0].state == SessionState.STARTING
