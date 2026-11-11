# SPDX-License-Identifier: MPL-2.0
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from corinthos.contracts import ConflictError, IntegrityError
from corinthos.lifecycle.repository import LifecycleRepository


def test_immutable_origin_cas_and_complete_poststate_history(tmp_path):
    repo = LifecycleRepository(tmp_path)
    record = repo.create("FEEDBACK", "project-one", {"text": "Observed"}, state="OPEN")
    changed = repo.update(
        "FEEDBACK", record["record_id"], 1, state="TRIAGED", snapshot={"route": "WORKFLOW"}
    )
    assert changed["origin"] == record["origin"]
    assert changed["version"] == 2
    events = repo.events("project-one")
    assert [event["data"]["record"]["state"] for event in events] == ["OPEN", "TRIAGED"]
    assert events[-1]["data"]["record"]["snapshot"] == {"route": "WORKFLOW"}
    assert LifecycleRepository(tmp_path).get("FEEDBACK", record["record_id"]) == changed
    with pytest.raises(ConflictError):
        repo.update("FEEDBACK", record["record_id"], 1, state="CLOSED")
    with repo.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE lc_records SET origin='{}' WHERE record_id=?", (record["record_id"],)
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM lc_events")


def test_writer_rollback_and_invalid_audit_inputs_leave_no_partial_record(tmp_path):
    repo = LifecycleRepository(tmp_path)
    with pytest.raises(RuntimeError), repo.transaction() as conn:
        repo.create("BUILD", "project-one", {}, state="SEALED", connection=conn)
        raise RuntimeError("Injected interruption")
    assert repo.list("BUILD", "project-one") == []
    with repo.transaction() as conn:
        for kwargs in ({"actor_id": "bad actor"}, {"event": "bad event"}):
            with pytest.raises(IntegrityError):
                repo.create("BUILD", "project-one", {}, state="SEALED", connection=conn, **kwargs)
    assert repo.list("BUILD", "project-one") == []
    assert repo.events("project-one") == []


def test_pure_inspection_stable_tracker_and_project_pointer_boundaries(tmp_path):
    repo = LifecycleRepository(tmp_path)
    assert repo.project("project-one") is None
    assert repo.events("project-one") == []
    project = repo.project("project-one", create=True)
    assert repo.project("project-one", create=True) == project
    own = repo.create("BUILD", "project-one", {}, state="SEALED")
    foreign = repo.create("BUILD", "project-two", {}, state="SEALED")
    feedback = repo.create("FEEDBACK", "project-one", {}, state="OPEN")
    for value in (foreign, feedback):
        with pytest.raises(IntegrityError):
            repo._update_project("project-one", 1, active_build_id=value["record_id"])
    active = repo._update_project("project-one", 1, active_build_id=own["record_id"])
    assert active["tracker_id"] == project["tracker_id"]
    assert active["version"] == 2
    assert repo._update_project("project-one", 2, active_build_id=own["record_id"]) == active
    with pytest.raises(ConflictError):
        repo._update_project("project-one", 1, enabled=True)


def test_concurrent_cas_has_one_winner(tmp_path):
    repo = LifecycleRepository(tmp_path)
    record = repo.create("FEEDBACK", "project-one", {}, state="OPEN")

    def attempt(state):
        try:
            return LifecycleRepository(tmp_path).update(
                "FEEDBACK", record["record_id"], 1, state=state
            )["state"]
        except ConflictError:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("TRIAGED", "CLOSED")))
    assert results.count("CONFLICT") == 1
    assert repo.get("FEEDBACK", record["record_id"])["version"] == 2
    assert len(repo.events("project-one")) == 2


def test_integrity_and_json_trust_boundaries(tmp_path):
    repo = LifecycleRepository(tmp_path)
    for origin in ({"bad": float("nan")}, {1: "nonstring"}, {"oversized": "x" * (4 * 1024 * 1024)}):
        with pytest.raises(IntegrityError):
            repo.create("BUILD", "project-one", origin, state="SEALED")
    record = repo.create("BUILD", "project-one", {}, state="SEALED")
    with repo.transaction() as conn:
        conn.execute(
            "UPDATE lc_records SET snapshot='{}',snapshot_sha256='wrong',version=version+1 WHERE record_id=?",
            (record["record_id"],),
        )
    with pytest.raises(IntegrityError, match="integrity"):
        repo.get("BUILD", record["record_id"])
