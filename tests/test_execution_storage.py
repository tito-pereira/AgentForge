# SPDX-License-Identifier: MPL-2.0
"""Upgrade an actual A-D database without reinterpreting contracts or approvals."""

import io
import os
import sqlite3
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import pytest

from corinthos.contracts import ContractStore, StoreError
from corinthos.contracts import store as storage
from corinthos.project_manager import ProjectManager
from corinthos.workflow import WorkflowPlanner

_BASE = "eb7dabbe443657524c6cf79880c9584d25675b91"
_TABLES = (
    "contracts",
    "revisions",
    "contract_references",
    "audit_events",
    "pm_sessions",
    "pm_turns",
    "pm_approvals",
    "wf_sessions",
    "wf_turns",
    "wf_approvals",
    "wf_mandates",
)
_SETUP = """
# Synthetic trusted fixture authority, never production terminal consent.
import json
import sqlite3
from pathlib import Path
from corinthos.contracts import ContractRef, ContractStore, PublishContext, approval_request
from corinthos.project_manager import ProjectManager
from corinthos.project_manager.approval import _record_consent, _verifier, recover_publication
from corinthos.workflow import WorkflowPlanner
from corinthos.workflow.authorization import _record, _publish

root = Path.cwd()
store = ContractStore(root)
examples = Path(__import__('sys').argv[1])
for name in ('project', 'technology-decision', 'module', 'workflow', 'validation',
             'validation-result', 'evidence-report', 'project-revision-request'):
    document = json.loads((examples / (name + '.json')).read_text(encoding='utf-8'))
    proof = approval_request(document) if document['metadata']['approval'] else None
    metadata = document['metadata']['provenance']
    store.publish(document, context=PublishContext(metadata['engine'], metadata['actor_id'],
                                                 lambda request, proof=proof: request == proof))
manager = ProjectManager(root)
s = manager.start('A synthetic migration project.', actor_id='fixture-owner')
for operation in (
    {'action':'set_scope','section':'included','items':['Offline greeting']},
    {'action':'upsert_requirement','description':'Render a greeting.',
     'acceptance_criteria':[{'criterion':'Ada produces Hello, Ada.'}]},
    {'action':'upsert_success_criterion','criterion':'A clean environment runs the greeting.'},
):
    s = manager.edit(s['session_id'], s['version'], operation, actor_id='fixture-owner')
s = manager.review(s['session_id'], s['version'], actor_id='fixture-owner')
s = _record_consent(manager, s, 'fixture-owner')
d = s['review']['document']
store.publish(d, context=PublishContext('PROJECT_MANAGER','fixture-owner',_verifier(manager,s)))
recover_publication(manager,s)
planner = WorkflowPlanner(root)
s = planner.start(ContractRef.from_document(d), actor_id='fixture-owner')
requirement = d['payload']['requirements'][0]['requirement_id']
checkpoint = json.loads((examples/'workflow.json').read_text(encoding='utf-8'))['payload']['checkpoints'][0]
checkpoint['module_ids'] = ['migration-greeting']
checkpoint['requirement_ids'] = [requirement]
for operation in (
    {'action':'upsert_module','module_id':'migration-greeting',
     'purpose_and_boundaries':{'purpose':'Render the greeting.', 'responsibilities':['Greeting'],
                               'exclusions':['Network access']},
     'requirement_ids':[requirement], 'constraint_ids':[]},
    {'action':'upsert_checkpoint','checkpoint':checkpoint},
):
    s = planner.edit(s['session_id'], s['version'], operation, actor_id='fixture-owner')
s = planner.review(s['session_id'], s['version'], actor_id='fixture-owner')
s = _record(planner,s,'fixture-owner',delegate=True)
_publish(planner,s,'fixture-owner')
assert sqlite3.connect(store.database_path).execute('PRAGMA user_version').fetchone()[0] == 3
"""


def _records(database):
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in _TABLES
        }


def _version(database):
    with sqlite3.connect(database) as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0]


@pytest.fixture
def phase3_state(tmp_path):
    repository = Path(__file__).resolve().parents[1]
    archive = subprocess.run(
        ["git", "archive", "--format=zip", _BASE, "src/corinthos"],
        cwd=repository,
        capture_output=True,
        check=True,
    ).stdout
    old = tmp_path / "phase3-ad-code"
    with ZipFile(io.BytesIO(archive)) as zipped:
        zipped.extractall(old)
    project = tmp_path / "project"
    project.mkdir()
    environment = {**os.environ, "PYTHONPATH": str(old / "src"), "PYTHONUTF8": "1"}
    result = subprocess.run(
        [sys.executable, "-B", "-c", _SETUP, str(repository / "examples/contracts")],
        cwd=project,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return project


def test_actual_v3_upgrade_preserves_every_old_row_and_verified_backup(phase3_state):
    database = phase3_state / ".corinthos/state.db"
    before = _records(database)
    assert all(before[table] for table in _TABLES)
    store = ContractStore(phase3_state)
    assert _version(database) == 4 and _records(database) == before
    (backup,) = database.parent.glob("state.pre-v4-*.db")
    assert _version(backup) == 3 and _records(backup) == before
    assert ProjectManager(phase3_state).list()[0]["state"] == "PUBLISHED"
    assert WorkflowPlanner(phase3_state).list()[0]["state"] == "PUBLISHED"
    with store._connection() as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert connection.execute("SELECT COUNT(*) FROM wf_executions").fetchone()[0] == 0
    ContractStore(phase3_state)
    assert list(database.parent.glob("state.pre-v4-*.db")) == [backup]


def test_failed_v4_upgrade_rolls_back_schema_and_retains_old_backup(phase3_state, monkeypatch):
    database = phase3_state / ".corinthos/state.db"
    before = _records(database)
    with monkeypatch.context() as patch:
        patch.setattr(storage, "_MIGRATION_V4", (*storage._MIGRATION_V4, "INVALID SQL"))
        with pytest.raises(StoreError):
            ContractStore(phase3_state)
    assert _version(database) == 3 and _records(database) == before
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_schema WHERE name='wf_executions'"
            ).fetchone()
            is None
        )
    assert _records(next(database.parent.glob("state.pre-v4-*.db"))) == before
    assert ContractStore(phase3_state).list_events()


def test_concurrent_v4_openers_create_one_verified_backup(phase3_state):
    database = phase3_state / ".corinthos/state.db"
    before = _records(database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        stores = list(pool.map(ContractStore, (phase3_state, phase3_state)))
    assert len(stores) == 2 and _version(database) == 4 and _records(database) == before
    assert len(list(database.parent.glob("state.pre-v4-*.db"))) == 1


def test_read_only_v3_is_preserved_without_upgrade(phase3_state):
    database = phase3_state / ".corinthos/state.db"
    before = database.read_bytes()
    original_mode = database.stat().st_mode
    database.chmod(stat.S_IREAD)
    try:
        with pytest.raises(StoreError, match="read-only"):
            ContractStore(phase3_state)
        assert database.read_bytes() == before
        assert not list(database.parent.glob("state.pre-v4-*.db"))
    finally:
        database.chmod(original_mode)
