# SPDX-License-Identifier: MPL-2.0
"""Preserve real Phase 2 state when upgrading to SQLite v8."""

import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_execution_storage import _EXECUTE_V4, _historical_state, _records, _version
from test_lifecycle_migration import _VALIDATE_REPORT_V5, _artifacts
from test_work_migration import _LIFECYCLE, _MIGRATED_TABLES, _TABLES_V6, _check, _tables

from corinthos.contracts import ContractStore, StoreError
from corinthos.contracts import store as storage
from corinthos.sessions.repository import SessionRepository
from corinthos.work import WorkService

_BASELINE = "5d913b7b18ef720f963e7614046a4062a4b2367f"
_TABLES_V7 = (*_TABLES_V6, *sorted(_MIGRATED_TABLES))
_V8 = {"agent_sessions", "agent_session_events"}
_WORK = """
from corinthos.work import WorkService
work = WorkService(root)
first = work.create(
    project_id='demo-project', scope_level='TASK', objective='Fixture root',
    acceptance_criteria=['Old exact'],
)
second = work.create(
    scope_level='CHANGE', objective='Fixture child', acceptance_criteria=['Second exact'],
    parent_work_item_id=first.work_item_id, depends_on=[first.work_item_id],
    affected_modules=['greeting', 'proposed-module'],
)
assert first.project_id == second.project_id
assert work.transition(first.work_item_id, 'ACTIVE').status == 'ACTIVE'
"""


@pytest.fixture
def real_v7(tmp_path):
    return _historical_state(tmp_path, _BASELINE, 7, _WORK)


@pytest.fixture
def populated_v7(tmp_path):
    return _historical_state(
        tmp_path, _BASELINE, 7, _EXECUTE_V4 + _VALIDATE_REPORT_V5 + _LIFECYCLE + _WORK
    )


def test_real_populated_v7_upgrade_keeps_history_and_pre_v7_backups(populated_v7):
    database = populated_v7 / ".corinthos/state.db"
    expected = _records(database, _TABLES_V7)
    artifacts = _artifacts(populated_v7)
    assert len(expected) == 26 and all(expected.values()) and artifacts
    old_backup = database.with_name("state.pre-v7-earlier.db")
    old_backup.write_bytes(b"Preserved previous backup")
    before = database.read_bytes()
    assert SessionRepository(populated_v7).list() == []
    assert len(WorkService(populated_v7).list()) == 2
    assert database.read_bytes() == before

    with ThreadPoolExecutor(max_workers=2) as pool:
        stores = list(pool.map(ContractStore, (populated_v7, populated_v7)))
    (backup,) = database.parent.glob("state.pre-v8-*.db")
    assert _version(database) == 8 and _version(backup) == 7
    assert _tables(database) == _tables(backup) | _V8
    assert _records(database, _TABLES_V7) == _records(backup, _TABLES_V7) == expected
    assert _artifacts(populated_v7) == artifacts
    assert old_backup.read_bytes() == b"Preserved previous backup"
    _check(database)
    _check(backup)

    items = WorkService(populated_v7).list()
    assert len(items) == 2 and items[1].parent_work_item_id == items[0].work_item_id
    assert items[0].work_item_id in items[1].dependencies
    assert any(link.module_ref is not None for link in items[1].affected_modules)
    assert any(link.module_ref is None for link in items[1].affected_modules)
    assert (
        ContractStore(populated_v7).list_events()
        == stores[0].list_events()
        == stores[1].list_events()
    )
    assert list(database.parent.glob("state.pre-v8-*.db")) == [backup]


def test_injected_v8_failure_rolls_back_and_preserves_v7_backup(real_v7, monkeypatch):
    database = real_v7 / ".corinthos/state.db"
    original = database.read_bytes()
    expected = _records(database, _TABLES_V7)
    with monkeypatch.context() as patch:
        patch.setattr(storage, "_MIGRATION_V8", (*storage._MIGRATION_V8, "INVALID SQL"))
        with pytest.raises(StoreError, match="operation failed"):
            ContractStore(real_v7)
    (backup,) = database.parent.glob("state.pre-v8-*.db")
    assert _version(database) == _version(backup) == 7
    assert not _tables(database) & _V8
    assert database.read_bytes() == original
    assert _records(database, _TABLES_V7) == _records(backup, _TABLES_V7) == expected
    _check(backup)
    assert WorkService(real_v7).list()


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("foreign", "unsupported"),
        ("future", "unsupported"),
        ("schema", "altered schema"),
        ("foreign-key", "foreign-key"),
        ("read-only", "read-only"),
        ("corrupt", "not SQLite"),
    ],
)
def test_invalid_v7_migration_input_is_never_rewritten(real_v7, replacement, message):
    database = real_v7 / ".corinthos/state.db"
    original_mode = database.stat().st_mode
    sql = {
        "foreign": "PRAGMA application_id = 1",
        "future": "PRAGMA user_version = 9",
        "schema": "DROP INDEX work_items_parent",
        "foreign-key": """
            UPDATE work_item_dependencies SET dependency_id = 'missing'
        """,
    }.get(replacement)
    if sql is not None:
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(sql)
            connection.commit()
    elif replacement == "read-only":
        database.chmod(original_mode & ~stat.S_IWUSR)
    else:
        database.write_bytes(b"Not SQLite.")
    original = database.read_bytes()
    try:
        with pytest.raises(StoreError, match=message):
            ContractStore(real_v7)
        assert database.read_bytes() == original
        assert not list(database.parent.glob("state.pre-v8-*.db"))
    finally:
        database.chmod(original_mode)
