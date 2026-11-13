# SPDX-License-Identifier: MPL-2.0
"""Exercise the v7 migration from actual Phase 0 baseline code and databases."""

import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_execution_storage import (
    _CONTRACT_SETUP,
    _EXECUTE_V4,
    _historical_state,
    _records,
    _version,
)
from test_lifecycle_migration import _TABLES_V5, _VALIDATE_REPORT_V5, _artifacts

from corinthos.contracts import ContractStore, StoreError
from corinthos.contracts import store as storage
from corinthos.project_manager import ProjectManager
from corinthos.report.service import ReportService
from corinthos.work import WorkService
from corinthos.workflow import WorkflowPlanner

V6_BASELINE = "5a2a8e682b1389d96318feb636b8f52828f943d3"
_TABLES_V6 = (*_TABLES_V5, "lc_records", "lc_projects", "lc_events")
_MIGRATED_TABLES = {"work_items", "work_item_dependencies", "work_item_modules"}
_MINIMAL = """
import json
from copy import deepcopy
from corinthos.contracts import ContractRef
source = json.loads((examples / 'project.json').read_text('utf-8'))
baseline_ref = ContractRef.from_document(source)
successor = deepcopy(source)
successor['metadata'].update(
    revision_id='baseline-fixture-project-r2', version=2, supersedes=baseline_ref.to_json(),
    approval={'kind':'HUMAN','approval_id':'baseline-fixture-approval','actor_id':'demo-owner'},
)
successor['payload']['scope']['included'].append('Record a synthetic migration fixture')
proof = approval_request(successor)
origin = successor['metadata']['provenance']
store.publish(successor, context=PublishContext(origin['engine'], origin['actor_id'],
                                               lambda request: request == proof))
before = store.database_path.read_bytes()
reopened = ContractStore(root)
assert reopened.get(baseline_ref) == source
assert reopened.resolve_active(baseline_ref.contract_id) == successor
assert reopened.list_events() == store.list_events()
assert reopened.database_path.read_bytes() == before
assert not list(reopened.database_path.parent.glob('state.pre-v*.db'))
"""
_LIFECYCLE = """
from corinthos.lifecycle.repository import LifecycleRepository
repository = LifecycleRepository(store)
repository.create('OPERATION', 'demo-project', {'fixture':'v6'}, state='COMPLETED',
                  actor_id='fixture-owner', record_id='fixture-operation')
repository.project('demo-project', create=True)
"""


@pytest.fixture
def real_v6(tmp_path):
    return _historical_state(tmp_path, V6_BASELINE, 6, _MINIMAL, base_setup=_CONTRACT_SETUP)


@pytest.fixture
def populated_v6(tmp_path):
    return _historical_state(
        tmp_path, V6_BASELINE, 6, _EXECUTE_V4 + _VALIDATE_REPORT_V5 + _LIFECYCLE
    )


def _tables(database):
    with closing(sqlite3.connect(database)) as connection:
        return {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        }


def _check(database):
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA application_id").fetchone() == (0x4E554B59,)
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_real_baseline_v6_migrates_once_with_verified_v6_backup(real_v6):
    database = real_v6 / ".corinthos/state.db"
    expected = _records(database, _TABLES_V6)
    assert len(expected) == 23
    assert ContractStore.inspect_existing(real_v6) == 6
    before = database.read_bytes()
    assert WorkService(real_v6).list() == []
    assert database.read_bytes() == before
    first = ContractStore(real_v6)
    (backup,) = database.parent.glob("state.pre-v7-*.db")
    assert _version(database) == 7
    assert _version(backup) == 6
    assert _records(database, _TABLES_V6) == _records(backup, _TABLES_V6) == expected
    assert _tables(database) == _tables(backup) | _MIGRATED_TABLES
    _check(database)
    _check(backup)
    after = database.read_bytes()
    assert ContractStore(real_v6).list_events() == first.list_events()
    assert (
        first.resolve_active("demo-intent")["metadata"]["revision_id"]
        == "baseline-fixture-project-r2"
    )
    assert database.read_bytes() == after
    assert list(database.parent.glob("state.pre-v7-*.db")) == [backup]


def test_populated_v6_preserves_all_histories_and_handles_concurrent_openers(populated_v6):
    database = populated_v6 / ".corinthos/state.db"
    expected = _records(database, _TABLES_V6)
    expected_artifacts = _artifacts(populated_v6)
    assert all(expected.values()) and expected_artifacts
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(ContractStore, (populated_v6, populated_v6))
    (backup,) = database.parent.glob("state.pre-v7-*.db")
    assert _version(database) == 7 and _version(backup) == 6
    assert _records(database, _TABLES_V6) == _records(backup, _TABLES_V6) == expected
    assert _artifacts(populated_v6) == expected_artifacts
    assert first.list_events() == second.list_events()
    assert ProjectManager(populated_v6).list()[0]["state"] == "PUBLISHED"
    assert WorkflowPlanner(populated_v6).list()[0]["state"] == "PUBLISHED"
    assert ReportService(first).list("demo-project")
    _check(first.database_path)
    _check(backup)


def test_failed_v7_migration_keeps_v6_and_verified_original_backup(populated_v6, monkeypatch):
    database = populated_v6 / ".corinthos/state.db"
    expected = _records(database, _TABLES_V6)
    with monkeypatch.context() as patch:
        patch.setattr(storage, "_MIGRATION_V7", (*storage._MIGRATION_V7, "INVALID SQL"))
        with pytest.raises(StoreError, match="operation failed"):
            ContractStore(populated_v6)
    (backup,) = database.parent.glob("state.pre-v7-*.db")
    assert _version(database) == _version(backup) == 6
    assert _tables(database) == _tables(backup)
    assert _records(database, _TABLES_V6) == _records(backup, _TABLES_V6) == expected
    _check(database)
    _check(backup)
    assert ContractStore(populated_v6).list_events()
    assert _version(database) == 7
    assert _records(database, _TABLES_V6) == expected


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("foreign", "unsupported"),
        ("future", "unsupported"),
        ("schema", "altered schema"),
        ("foreign-key", "foreign-key"),
        ("read-only", "read-only"),
        ("corrupt", "corrupt or is not SQLite"),
    ],
)
def test_invalid_v6_sources_are_refused_without_mutation(real_v6, replacement, message):
    database = real_v6 / ".corinthos/state.db"
    mode = database.stat().st_mode
    ddl = {
        "foreign": "PRAGMA application_id = 1",
        "future": "PRAGMA user_version = 8",
        "schema": "DROP TRIGGER lc_records_no_delete",
        "foreign-key": """
            UPDATE contracts SET active_revision_id = 'missing'
            WHERE contract_id = 'demo-intent'
        """,
    }
    if replacement in ddl:
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(ddl[replacement])
            connection.commit()
    elif replacement == "read-only":
        database.chmod(mode & ~stat.S_IWUSR)
    else:
        database.write_bytes(b"Not an SQLite database.")
    before = database.read_bytes()
    try:
        with pytest.raises(StoreError, match=message):
            ContractStore(real_v6)
        assert database.read_bytes() == before
        assert not list(database.parent.glob("state.pre-v7-*.db"))
    finally:
        database.chmod(mode)
