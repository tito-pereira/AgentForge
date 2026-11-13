# SPDX-License-Identifier: MPL-2.0
"""Ensure SQLite retains exact context sources, handoffs, and session bindings."""

from dataclasses import replace
from uuid import uuid4

import pytest

from corinthos.context.model import Handoff, Projection, Source, digest
from corinthos.context.repository import ContextRepository
from corinthos.contracts import ConflictError, ContractStore, StoreError
from corinthos.sessions.repository import SessionRepository
from corinthos.work import WorkService

_DATE = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def setup(tmp_path):
    ContractStore(tmp_path)
    work = WorkService(tmp_path)
    item = work.create(
        scope_level="TASK", objective="Check persisted state", acceptance_criteria=["Stable"]
    )
    repository = ContextRepository(tmp_path)
    return tmp_path, work, item, repository


def _projection(item, target="codex"):
    payload = {"objective": item.objective}
    source = Source(
        0,
        "WORK_ITEM",
        "OPERATIONAL",
        item.work_item_id,
        item.updated_at,
        digest(payload),
        "WORK_ITEM",
        (),
        payload,
    )
    projection = Projection(
        "projection-" + uuid4().hex,
        item.project_id,
        item.work_item_id,
        target,
        1,
        1,
        payload,
        digest([target, item.work_item_id, payload]),
        digest([source.descriptor()]),
        _DATE,
    )
    return projection, source


def test_projection_deduplication_and_sources_are_sealed(setup):
    root, _, item, repo = setup
    original, source = _projection(item)
    with repo.write() as connection:
        assert repo.save_projection(connection, original, [source]) == original
        same = replace(original, projection_id="projection-" + uuid4().hex)
        assert repo.save_projection(connection, same, [source]) == original
        with pytest.raises(ConflictError):
            repo.save_projection(connection, same, [replace(source, capture={"changed": True})])

    with repo.read() as connection:
        assert repo.get_projection(connection, original.projection_id) == original
        assert repo.projection_sources(connection, original.projection_id) == [source]
        assert repo.list_projections(connection, item.work_item_id) == [original]
        summary = repo.snapshot_summary(connection)
        assert summary["projection_count"] == 1
        assert summary["latest_projection"]["projection_id"] == original.projection_id
        assert "canonical_payload" not in summary["latest_projection"]
        assert summary["handoff_count"] == 0 and summary["latest_handoff"] is None

    store = ContractStore(root)
    for sql in (
        "UPDATE context_projections SET canonical_payload = '{}' WHERE projection_id = ?",
        "DELETE FROM context_projections WHERE projection_id = ?",
        "INSERT OR REPLACE INTO context_projections SELECT * FROM context_projections WHERE projection_id = ?",
        "UPDATE context_projection_sources SET capture = '{}' WHERE projection_id = ?",
        "DELETE FROM context_projection_sources WHERE projection_id = ?",
        """INSERT INTO context_projection_sources
           SELECT projection_id, 1, kind, authority, identity, revision, digest, reason, redaction, capture
           FROM context_projection_sources WHERE projection_id = ?""",
    ):
        with pytest.raises(StoreError), store._transaction() as connection:
            connection.execute(sql, (original.projection_id,))


def test_projection_binding_checks_exact_work_and_provider_and_preserves_handoffs(setup):
    root, work, item, repo = setup
    other = work.create(scope_level="TASK", objective="Other task", acceptance_criteria=["Tracked"])
    selected, source = _projection(item)
    another, another_source = _projection(item, "claude")
    with repo.write() as connection:
        repo.save_projection(connection, selected, [source])
        repo.save_projection(connection, another, [another_source])
    sessions = SessionRepository(root)
    args = {
        "owner_id": "test-owner",
        "timeout_seconds": 120,
        "context_projection_id": selected.projection_id,
    }
    with pytest.raises(StoreError):
        sessions.create(other.work_item_id, provider="codex", **args)
    with pytest.raises(StoreError):
        sessions.create(item.work_item_id, provider="claude", **args)
    session = sessions.create(item.work_item_id, provider="codex", **args)
    assert session.context_projection_id == selected.projection_id
    with pytest.raises(StoreError), repo.write() as connection:
        connection.execute(
            "UPDATE agent_sessions SET context_projection_id = ? WHERE session_id = ?",
            (another.projection_id, session.session_id),
        )
    with pytest.raises(StoreError), repo.write() as connection:
        connection.execute(
            "UPDATE agent_sessions SET context_projection_id = NULL WHERE session_id = ?",
            (session.session_id,),
        )

    payload = {"observation": "Interrupted, exact stable history"}
    handoff = Handoff(
        "handoff-" + uuid4().hex,
        item.project_id,
        item.work_item_id,
        session.session_id,
        1,
        "codex",
        "INTERRUPTED",
        1,
        payload,
        digest(payload),
        _DATE,
    )
    with pytest.raises(StoreError), repo.write() as connection:
        repo.save_handoff(connection, handoff)
    fence = session.session_id, session.owner_id, session.run_generation
    sessions.bind(*fence, envelope_sha256="d" * 64, native_resume=True)
    sessions.running(*fence)
    sessions.observe(*fence, "OUTPUT", {"text": "Fixture"}, native_session_id="fixture-native")
    sessions.finish(*fence, "INTERRUPTED")
    events = sessions.events(session.session_id)
    with pytest.raises(StoreError), repo.write() as connection:
        repo.save_handoff(connection, handoff)
    handoff = replace(handoff, event_cutoff=events[-1].sequence)
    with repo.write() as connection:
        assert repo.save_handoff(connection, handoff) == handoff
        assert (
            repo.save_handoff(connection, replace(handoff, handoff_id="handoff-" + uuid4().hex))
            == handoff
        )
    for sql in (
        "UPDATE session_handoffs SET canonical_payload = '{}' WHERE handoff_id = ?",
        "DELETE FROM session_handoffs WHERE handoff_id = ?",
        "INSERT OR REPLACE INTO session_handoffs SELECT * FROM session_handoffs WHERE handoff_id = ?",
    ):
        with pytest.raises(StoreError), repo.write() as connection:
            connection.execute(sql, (handoff.handoff_id,))
    resumed = sessions.recover(session.session_id, owner_id="next-owner", envelope_sha256="d" * 64)
    assert resumed.context_projection_id == selected.projection_id and resumed.run_generation == 2
    with repo.read() as connection:
        assert repo.get_handoff(connection, handoff.handoff_id) == handoff
        assert repo.list_handoffs(connection, item.work_item_id, session.session_id) == [handoff]
        assert repo.snapshot_summary(connection)["latest_handoff"]["digest"] == handoff.digest
