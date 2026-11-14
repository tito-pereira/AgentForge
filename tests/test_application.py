# SPDX-License-Identifier: MPL-2.0
"""Passive application reads reuse the current project and provider boundaries."""

import json
import os
import sqlite3
from contextlib import closing

import pytest
from test_execution_storage import _historical_state

from corinthos import __version__
from corinthos.adapters.service import AdapterManager
from corinthos.application import project_status, providers_status, version
from corinthos.bootstrap import configure_adapter, initialize
from corinthos.cli import main
from corinthos.contracts import ContractStore
from corinthos.contracts import store as storage


@pytest.fixture
def isolated_user(tmp_path, monkeypatch):
    path = tmp_path / "user"
    monkeypatch.setattr("corinthos.user_state.state_root", lambda: path)
    return path


def _snapshot(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_project_status_is_read_only_for_missing_ordinary_and_bootstrap(tmp_path):
    root = tmp_path / "project"
    assert not project_status(root).exists
    assert not root.exists()
    root.mkdir()
    assert project_status(root).storage == "ABSENT"
    assert not project_status(root).initialized
    assert list(root.iterdir()) == []
    file = tmp_path / "file"
    file.write_text("ordinary file")
    assert project_status(file).exists
    assert not project_status(file).is_directory

    initialize(root)
    before = _snapshot(root)
    result = project_status(root)
    assert (result.initialized, result.storage, result.schema_version) == (True, "ABSENT", None)
    assert _snapshot(root) == before
    assert not (root / ".corinthos/state.db").exists()


@pytest.mark.parametrize("marker", [1, 6, 7, 8, 9, 10, None])
def test_project_status_checks_existing_storage_without_creating_or_migrating(tmp_path, marker):
    if marker == 6:
        tmp_path = _historical_state(tmp_path, "5a2a8e682b1389d96318feb636b8f52828f943d3", 6)
    if marker == 7:
        tmp_path = _historical_state(tmp_path, "5d913b7b18ef720f963e7614046a4062a4b2367f", 7)
    if marker == 8:
        tmp_path = _historical_state(tmp_path, "13e7bf556788e737493d767b30e12a6613c8fa73", 8)
    private = tmp_path / ".corinthos"
    private.mkdir(exist_ok=True)
    database = private / "state.db"
    if marker == 9:
        ContractStore(tmp_path)
    elif marker is None:
        database.write_bytes(b"not SQLite")
    elif marker not in {6, 7, 8}:
        with closing(sqlite3.connect(database)) as connection:
            for statement in storage._MIGRATION_V1:
                connection.execute(statement)
            connection.execute(f"PRAGMA application_id = {storage._APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {marker}")
            connection.commit()
    before = _snapshot(tmp_path)
    result = project_status(tmp_path)
    assert result.is_directory
    if marker in {1, 6, 7, 8, 9}:
        assert (result.initialized, result.storage, result.schema_version) == (
            True,
            "CURRENT" if marker == 9 else "LEGACY",
            marker,
        )
    else:
        assert (result.initialized, result.storage, result.schema_version) == (
            False,
            "INVALID",
            None,
        )
    assert _snapshot(tmp_path) == before
    assert not list(private.glob("state.pre-v*.db"))


def test_project_status_does_not_touch_active_journal_or_wal(tmp_path):
    initialize(tmp_path)
    database = ContractStore(tmp_path).database_path
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        connection.execute("CREATE TABLE transient_fixture (id INTEGER PRIMARY KEY)")
        connection.commit()
        before = _snapshot(tmp_path)
        assert database.with_name("state.db-wal").exists()
        result = project_status(tmp_path)
        assert (result.initialized, result.storage, result.schema_version) == (
            True,
            "UNVERIFIED",
            None,
        )
        assert _snapshot(tmp_path) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows drive and device syntax")
@pytest.mark.parametrize(
    "root", [r"\\example\share\project", r"\\?\C:\project", "C:project", "file:stream"]
)
def test_windows_external_path_forms_are_rejected_before_io(root):
    with pytest.raises(ValueError, match="Invalid project root"):
        project_status(root)


def test_read_only_status_does_not_follow_project_links(tmp_path, isolated_user):
    original = tmp_path / "project"
    initialize(original)
    link = tmp_path / "redirected"
    try:
        link.symlink_to(original, target_is_directory=True)
    except OSError:
        pytest.skip("The filesystem or local account does not support directory symlinks.")
    before = _snapshot(original)
    for read in (project_status, providers_status):
        with pytest.raises(ValueError, match="unredirected"):
            read(link)
        with pytest.raises(ValueError):
            read(link / "nested")
    assert _snapshot(original) == before
    assert not isolated_user.exists()


def _registry(executable, *, observed_path=None, discovery="explicit"):
    return {
        "version": 1,
        "providers": {
            "codex": {
                "executable": str(executable) if executable else None,
                "observed": {
                    "available": True,
                    "json_events": True,
                    "stdin_prompt": True,
                    "native_resume": False,
                    "read_only": True,
                    "version": "9.8.7",
                    "reason": "private provider diagnostic",
                    "executable": str(observed_path) if observed_path else None,
                    "discovery": discovery,
                },
            },
        },
    }


def test_providers_status_reads_known_choices_without_probing(
    tmp_path, isolated_user, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        pytest.fail("Passive application operations must not discover or invoke providers")

    monkeypatch.setattr(AdapterManager, "discover", forbidden)
    monkeypatch.setattr(AdapterManager, "invoke", forbidden)
    assert version().version == __version__
    assert all(row.observation == "NOT_OBSERVED" for row in providers_status())
    assert not isolated_user.exists()
    global_executable = tmp_path / "global.exe"
    project_executable = tmp_path / "project.exe"
    project_executable.write_bytes(b"fixture executable")
    isolated_user.mkdir()
    registry = isolated_user / "providers.json"
    registry.write_text(json.dumps(_registry(global_executable, observed_path=global_executable)))
    (isolated_user / "recent-projects.json").write_text('{"version":1,"projects":[]}')
    root = tmp_path / "project"
    initialize(root, commands={"codex": [str(project_executable)]})
    before = _snapshot(tmp_path)

    (global_row,) = [row for row in providers_status() if row.provider == "codex"]
    assert (global_row.configuration, global_row.executable, global_row.observation) == (
        "global",
        str(global_executable),
        "OBSERVED",
    )
    assert global_row.capabilities.version == "9.8.7"
    assert global_row.capabilities.available
    (project_row,) = [row for row in providers_status(root) if row.provider == "codex"]
    assert (project_row.configuration, project_row.executable, project_row.observation) == (
        "initial",
        str(project_executable),
        "UNKNOWN",
    )
    assert project_row.capabilities is None
    assert main(["status", "--root", str(root)]) == 0
    output = capsys.readouterr()
    assert "private provider diagnostic" not in output.out
    assert json.loads(output.out)["project"]["initialized"]
    assert _snapshot(tmp_path) == before

    configure_adapter(root, "codex", None)
    (reset_row,) = [row for row in providers_status(root) if row.provider == "codex"]
    assert (reset_row.configuration, reset_row.executable, reset_row.observation) == (
        "operational",
        None,
        "UNKNOWN",
    )
    assert reset_row.capabilities is None


def test_cli_status_keeps_project_result_when_provider_state_cannot_be_read(
    tmp_path, isolated_user, capsys
):
    private = tmp_path / ".corinthos"
    private.mkdir()
    profile = private / "bootstrap.json"
    profile.write_bytes(b"corrupt bootstrap")
    assert main(["status", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "version": __version__,
        "project": {
            "root": str(tmp_path),
            "exists": True,
            "is_directory": True,
            "initialized": False,
            "storage": "INVALID",
            "schema_version": None,
        },
        "providers": None,
    }
    assert profile.read_bytes() == b"corrupt bootstrap"
    assert not isolated_user.exists()
