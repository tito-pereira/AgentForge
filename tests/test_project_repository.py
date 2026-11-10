# SPDX-License-Identifier: MPL-2.0
"""Exercise operational persistence without synthetic production approval."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest

from corinthos.contracts import ConflictError, ContractStore, StoreError
from corinthos.project_manager.repository import MAX_SNAPSHOT_BYTES, SessionRepository


@pytest.fixture
def repository(tmp_path):
    return SessionRepository(ContractStore(tmp_path))


def _snapshot(session_id="session-one", project_id="project-one"):
    return {
        "session_id": session_id,
        "project_id": project_id,
        "state": "DRAFT",
        "payload": {"vision": "A human-defined project with Unicode \u03bb."},
    }


def _create(repository, snapshot=None):
    return repository.create(snapshot or _snapshot(), actor_id="local-user", action="start")


def test_session_snapshot_and_turns_survive_reopen_as_detached_data(repository, tmp_path):
    draft = _create(repository)
    assert draft["version"] == 1
    draft["payload"]["vision"] = "An accepted clarification."
    saved = repository.save(draft["session_id"], 1, draft, actor_id="local-user", action="clarify")
    assert saved["version"] == 2
    reopened = SessionRepository(ContractStore(tmp_path))
    assert reopened.get(draft["session_id"]) == saved
    assert reopened.list() == [saved]
    turns = reopened.history(draft["session_id"])
    assert [turn["version"] for turn in turns] == [1, 2]
    assert len({turn["turn_id"] for turn in turns}) == 2
    assert [turn["action"] for turn in turns] == ["start", "clarify"]
    assert all(turn["actor_id"] == "local-user" and turn["occurred_at"] for turn in turns)
    saved["payload"]["vision"] = "An unsaved caller mutation."
    turns[0]["snapshot"]["state"] = "CANCELLED"
    assert reopened.get(draft["session_id"])["payload"]["vision"] == "An accepted clarification."
    assert reopened.history(draft["session_id"])[0]["snapshot"]["state"] == "DRAFT"
    assert reopened.store.list_events() == []


def test_missing_and_duplicate_session_fail_without_changing_history(repository):
    with pytest.raises(StoreError, match="does not exist"):
        repository.get("missing-session")
    _create(repository)
    with pytest.raises(ConflictError):
        _create(repository)
    assert len(repository.history("session-one")) == 1


@pytest.mark.parametrize(
    "malformed",
    ['{"private-sentinel":', "[" * 2000 + '"private-sentinel"' + "]" * 2000],
)
def test_malformed_stored_json_fails_without_exposing_its_contents(repository, malformed):
    _create(repository)
    with repository.store._transaction() as connection:
        connection.execute(
            "UPDATE pm_sessions SET snapshot = ? WHERE session_id = ?",
            (malformed, "session-one"),
        )
    with pytest.raises(StoreError, match="stored session snapshot is invalid") as error:
        repository.get("session-one")
    assert "private-sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "field,value", [("session_id", "another-session"), ("project_id", "other")]
)
def test_save_cannot_reassign_session_or_project(repository, field, value):
    draft = _create(repository)
    draft[field] = value
    with pytest.raises(ConflictError):
        repository.save("session-one", 1, draft, actor_id="local-user", action="edit")
    assert repository.get("session-one")["version"] == 1
    assert len(repository.history("session-one")) == 1


@pytest.mark.parametrize(
    "actor,action", [("invalid actor", "edit"), ("local-user", "\n"), ("local-user", "x" * 129)]
)
def test_invalid_turn_provenance_rolls_back_snapshot_and_history(repository, actor, action):
    draft = _create(repository)
    draft["state"] = "NEEDS_CLARIFICATION"
    with pytest.raises(StoreError):
        repository.save("session-one", 1, draft, actor_id=actor, action=action)
    assert repository.get("session-one")["state"] == "DRAFT"
    assert len(repository.history("session-one")) == 1


def test_snapshot_size_and_version_are_bounded(repository):
    large = _snapshot()
    large["text"] = "x" * MAX_SNAPSHOT_BYTES
    with pytest.raises(StoreError, match="1 MiB"):
        _create(repository, large)
    invalid = {**_snapshot(), "version": True}
    with pytest.raises(StoreError, match="version 1"):
        _create(repository, invalid)
    assert repository.list() == []


def test_concurrent_session_edits_have_one_winner(repository):
    draft = _create(repository)
    barrier = Barrier(2, timeout=10)

    def save(index):
        snapshot = deepcopy(draft)
        snapshot["choice"] = index
        barrier.wait()
        try:
            return repository.save("session-one", 1, snapshot, actor_id="local-user", action="edit")
        except ConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ConflictError) for result in results) == 1
    assert repository.get("session-one")["version"] == 2
    assert len(repository.history("session-one")) == 2


def _insert_receipt(connection, *, approval_id="test-receipt"):
    """Insert a synthetic storage fixture, never an approval capability."""
    connection.execute(
        "INSERT INTO pm_approvals (approval_id, session_id, session_version, project_id, "
        "revision_id, content_sha256, actor_id, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (approval_id, "session-one", 1, "project-one", "revision-one", "a" * 64, "local-user", 1.0),
    )


def test_bridge_transaction_rolls_back_session_turn_and_receipt_together(repository):
    draft = _create(repository)
    with pytest.raises(StoreError):
        with repository.store._transaction() as connection:
            repository._save(
                connection, "session-one", 1, draft, actor_id="local-user", action="review"
            )
            _insert_receipt(connection)
            connection.execute("INSERT INTO pm_approvals DEFAULT VALUES")
    assert repository.get("session-one")["version"] == 1
    assert len(repository.history("session-one")) == 1
    with repository.store._connection() as connection:
        assert connection.execute("SELECT * FROM pm_approvals").fetchall() == []


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE pm_approvals SET actor_id = 'other'",
        "UPDATE pm_approvals SET content_sha256 = 'forged'",
        "DELETE FROM pm_approvals",
        "INSERT OR REPLACE INTO pm_approvals SELECT * FROM pm_approvals",
    ],
)
def test_receipt_bindings_cannot_be_rewritten_or_deleted(repository, statement):
    _create(repository)
    with repository.store._transaction() as connection:
        _insert_receipt(connection)
    with pytest.raises(StoreError):
        with repository.store._transaction() as connection:
            connection.execute(statement)
    with repository.store._transaction() as connection:
        assert connection.execute("SELECT actor_id FROM pm_approvals").fetchone()[0] == "local-user"
        connection.execute("UPDATE pm_approvals SET consumed = 1")
    with pytest.raises(StoreError):
        with repository.store._transaction() as connection:
            connection.execute("UPDATE pm_approvals SET consumed = 0")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE pm_turns SET actor_id = 'other'",
        "DELETE FROM pm_turns",
        "INSERT OR REPLACE INTO pm_turns SELECT * FROM pm_turns",
    ],
)
def test_accepted_turn_history_is_append_only(repository, statement):
    _create(repository)
    with pytest.raises(StoreError):
        with repository.store._transaction() as connection:
            connection.execute(statement)
    assert len(repository.history("session-one")) == 1
