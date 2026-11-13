# SPDX-License-Identifier: MPL-2.0
"""Preserve genuine Phase 3 databases and their verified backups through v9."""

import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_execution_storage import _EXECUTE_V4, _historical_state, _records, _version
from test_lifecycle_migration import _VALIDATE_REPORT_V5, _artifacts
from test_session_migration import _TABLES_V7, _V8, _WORK
from test_work_migration import _LIFECYCLE, _check, _tables

from corinthos.context.repository import ContextRepository
from corinthos.contracts import ContractStore, StoreError
from corinthos.contracts import store as storage
from corinthos.sessions.repository import SessionRepository

_BASELINE = "13e7bf556788e737493d767b30e12a6613c8fa73"
_V9 = {"context_projections", "context_projection_sources", "session_handoffs"}
_TABLES_V8 = (*_TABLES_V7, *sorted(_V8))
_RUN = """
from corinthos.sessions.model import EventKind
from corinthos.sessions.repository import SessionRepository

repo = SessionRepository(root, clock=lambda: 1000.0)
session = repo.create(first.work_item_id, provider='codex', owner_id='test-owner',
                      timeout_seconds=120, read_only=True)
args = session.session_id, session.owner_id, session.run_generation
repo.bind(*args, envelope_sha256='d' * 64, native_resume=True)
repo.running(*args, provider_version='1.2.3')
repo.observe(*args, EventKind.OUTPUT, {'text':'Benign fixture output'},
             native_kind='message.complete', native_session_id='fixture-native')
repo.observe(*args, EventKind.USAGE, {}, usage={'input_tokens':0,'output_tokens':3,
             'reported_cost':'0.12','reported_cost_currency':'USD'})
repo.finish(*args, 'INTERRUPTED', duration_ms=300, reason='SIMULATED_SHUTDOWN')
"""


@pytest.fixture
def current_v8(tmp_path):
    return _historical_state(tmp_path, _BASELINE, 8, _WORK + _RUN)


def _baseline_rows(database):
    records = _records(database, _TABLES_V8)
    with closing(sqlite3.connect(database)) as connection:
        names = [row[1] for row in connection.execute("PRAGMA table_info(agent_sessions)")]
    if names[-1] == "context_projection_id":
        sessions = records["agent_sessions"]
        assert all(row[-1] is None for row in sessions)
        records["agent_sessions"] = [row[:-1] for row in sessions]
    return records


def test_v8_upgrade_preserves_all_populated_owners_and_backups(tmp_path):
    project = _historical_state(
        tmp_path, _BASELINE, 8, _EXECUTE_V4 + _VALIDATE_REPORT_V5 + _LIFECYCLE + _WORK + _RUN
    )
    database = project / ".corinthos/state.db"
    expected = _baseline_rows(database)
    artifacts = _artifacts(project)
    assert len(expected) == 28 and all(expected.values()) and artifacts
    old_backups = {}
    for version in (7, 8):
        path = database.with_name(f"state.pre-v{version}-earlier.db")
        path.write_bytes(f"Preserved original v{version} backup".encode())
        old_backups[path] = path.read_bytes()
    original = database.read_bytes()
    assert ContractStore.inspect_existing(project) == 8
    with ContextRepository(project).read() as empty:
        assert empty is None
    assert database.read_bytes() == original

    with ThreadPoolExecutor(max_workers=2) as pool:
        stores = list(pool.map(ContractStore, (project, project)))
    (backup,) = database.parent.glob("state.pre-v9-*.db")
    assert _version(backup) == 8 and _version(database) == 9
    assert _tables(database) == _tables(backup) | _V9
    assert _baseline_rows(database) == _baseline_rows(backup) == expected
    assert _artifacts(project) == artifacts
    assert {path: path.read_bytes() for path in old_backups} == old_backups
    _check(database)
    _check(backup)

    (session,) = SessionRepository(project).list()
    assert session.context_projection_id is None
    assert session.provider_version == "1.2.3" and session.recoverable
    assert session.input_tokens == 0 and session.cached_tokens is None
    assert session.reported_cost == "0.12" and session.reported_cost_currency == "USD"
    assert len(SessionRepository(project).events(session.session_id)) == 5
    assert (
        ContractStore(project).list_events() == stores[0].list_events() == stores[1].list_events()
    )
    assert list(database.parent.glob("state.pre-v9-*.db")) == [backup]


def test_v9_failure_preserves_v8_and_verified_backup(current_v8, monkeypatch):
    database = current_v8 / ".corinthos/state.db"
    expected = _baseline_rows(database)
    original = database.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(storage, "_MIGRATION_V9", (*storage._MIGRATION_V9, "INVALID SQL"))
        with pytest.raises(StoreError, match="operation failed"):
            ContractStore(current_v8)
    (backup,) = database.parent.glob("state.pre-v9-*.db")
    assert _version(database) == _version(backup) == 8
    assert _baseline_rows(database) == _baseline_rows(backup) == expected
    assert _tables(database) == _tables(backup) and not _tables(database) & _V9
    assert database.read_bytes() == original
    _check(database)
    _check(backup)


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("foreign", "unsupported"),
        ("future", "unsupported"),
        ("schema", "altered schema"),
        ("foreign-table", "altered schema"),
        ("foreign-key", "foreign-key"),
        ("read-only", "read-only"),
        ("corrupt", "not SQLite"),
    ],
)
def test_invalid_v8_input_is_never_migrated(current_v8, mode, message):
    database = current_v8 / ".corinthos/state.db"
    original_mode = database.stat().st_mode
    sql = {
        "foreign": "PRAGMA application_id = 1",
        "future": "PRAGMA user_version = 10",
        "schema": "DROP TRIGGER agent_session_events_no_update",
        "foreign-table": "CREATE TABLE unsupported_v8_shape (id TEXT)",
        "foreign-key": "DELETE FROM work_item_modules",
    }.get(mode)
    if sql is not None:
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(sql)
            if mode == "foreign-key":
                connection.execute("DELETE FROM work_item_dependencies")
                connection.execute("DROP TRIGGER work_items_no_delete")
                ddl = next(sql for sql in storage._MIGRATION_V7 if "work_items_no_delete" in sql)
                connection.execute("DELETE FROM work_items WHERE parent_work_item_id IS NOT NULL")
                connection.execute("DELETE FROM work_items")
                connection.execute(ddl)
            connection.commit()
    elif mode == "read-only":
        database.chmod(original_mode & ~stat.S_IWUSR)
    else:
        database.write_bytes(b"Not SQLite.")
    original = database.read_bytes()
    try:
        with pytest.raises(StoreError, match=message):
            ContractStore(current_v8)
        assert database.read_bytes() == original
        assert not list(database.parent.glob("state.pre-v9-*.db"))
    finally:
        database.chmod(original_mode)
