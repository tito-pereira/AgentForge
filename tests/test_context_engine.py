# SPDX-License-Identifier: MPL-2.0
"""Exercise Context selection, immutable captures, secrecy and replay."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from test_validation_repository import _publish as publish_plan
from test_validation_repository import _result, _start
from test_validation_repository import setup as setup
from test_work_items import _create, _example, _publish

from corinthos.bootstrap import initialize
from corinthos.context import ContextError, ContextService, HandoffService
from corinthos.context import projection as context_projection
from corinthos.context.index import ContextIndex
from corinthos.context.model import MAX_PROJECTION_BYTES, canonical_bytes, digest
from corinthos.context.redaction import redact, sanitize_text
from corinthos.lifecycle.repository import LifecycleRepository
from corinthos.sessions.repository import SessionRepository
from corinthos.work import WorkService


def test_replay_uses_same_order_digest_and_no_unselected_state(tmp_path, monkeypatch):
    initialize(tmp_path)
    work = WorkService(tmp_path)
    root = _create(work, "Parent")
    dependency = _create(work, "Dependency")
    unrelated = _create(work, "Unrelated requirement")
    item = _create(work, "Selected requirement", parent_work_item_id=root.work_item_id)
    work.add_dependency(item.work_item_id, dependency.work_item_id)

    service = ContextService(tmp_path)
    original = service.create(item.work_item_id, "codex")
    captures = service.sources(original.projection_id)
    assert [(row.reason, row.identity) for row in captures] == [
        ("WORK_ITEM", item.work_item_id),
        ("PARENT", root.work_item_id),
        ("DEPENDENCY", dependency.work_item_id),
    ]
    assert all(
        row.authority == "OPERATIONAL" and row.digest == digest(row.capture) for row in captures
    )
    work.update(unrelated.work_item_id, objective="A change outside the source tree.")
    select = ContextIndex.select

    def reverse_discovery(self, work_id):
        identity, rows = select(self, work_id)
        return identity, list(reversed(rows))

    monkeypatch.setattr(ContextIndex, "select", reverse_discovery)
    reopened = ContextService(tmp_path)
    assert reopened.create(item.work_item_id, "codex") == original
    assert reopened.verify(original.projection_id) == original
    assert reopened.sources(original.projection_id) == captures

    other_process = subprocess.run(
        [
            sys.executable,
            "-c",
            "from corinthos.context import ContextService; import sys; "
            "print(ContextService(sys.argv[1]).create(sys.argv[2], 'codex').projection_digest)",
            str(tmp_path),
            item.work_item_id,
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=15,
    )
    assert other_process.stdout.strip() == original.projection_digest

    work.update(dependency.work_item_id, objective="Dependency changed.")
    updated = reopened.create(item.work_item_id, "codex")
    assert updated.projection_digest != original.projection_digest
    assert updated.source_set_digest != original.source_set_digest
    assert reopened.get(original.projection_id) == original
    assert reopened.sources(original.projection_id) == captures
    same_sources_new_provider = reopened.create(item.work_item_id, "claude")
    assert same_sources_new_provider.source_set_digest == updated.source_set_digest
    assert same_sources_new_provider.projection_digest != updated.projection_digest


def test_exact_owners_and_selected_contract_successor(setup):
    validation, *_ = setup
    store = validation.store
    root = store.database_path.parent.parent
    work = WorkService(root)
    task = _create(work, "Check greeting", affected_modules=["greeting", "unresolved"])
    LifecycleRepository(store).project(task.project_id, create=True)
    plan = publish_plan(setup)
    run = _start(validation, plan)
    validation.freeze(run["run_id"], run["owner"], _result)
    validation.publish(run["run_id"])

    service = ContextService(root)
    original = service.create(task.work_item_id, "codex")
    records = service.sources(original.projection_id, limit=25)
    assert {entry.reason for entry in records} >= {
        "WORK_ITEM",
        "PROJECT_BASE",
        "AFFECTED_MODULE",
        "TECH_DECISION",
        "WORKFLOW",
        "VALIDATION",
        "LIFECYCLE",
    }
    assert {entry.kind for entry in records} >= {"VALIDATION_RESULT", "VALIDATION_RUN"}
    assert sum(entry.reason == "AFFECTED_MODULE" for entry in records) == 1
    base = next(entry for entry in records if entry.reason == "PROJECT_BASE")
    assert base.authority == "CANONICAL"
    assert base.capture.get("exact_document_sha256")
    project = _example("project")
    project["metadata"].update(
        revision_id="context-project-r2",
        version=2,
        supersedes=base.capture["ref"],
        approval={"kind": "HUMAN", "approval_id": "context-fixture-approval", "actor_id": "owner"},
    )
    project["payload"]["scope"]["included"].append("An approved scope addition.")
    _publish(store, project)
    updated = service.create(task.work_item_id, "codex")
    assert updated.projection_digest != original.projection_digest
    current = service.sources(updated.projection_id, limit=25)
    assert (
        next(entry for entry in current if entry.reason == "PROJECT_BASE").revision
        == "context-project-r2"
    )
    assert service.verify(original.projection_id) == original
    assert next(entry for entry in records if entry.reason == "PROJECT_BASE") == base


def test_projections_are_bounded_and_select_only_explicit_relations(tmp_path):
    initialize(tmp_path)
    work = WorkService(tmp_path)
    parents = [None]
    for _ in range(8):
        parents.append(
            _create(
                work,
                "Parent",
                parent_work_item_id=parents[-1].work_item_id if parents[-1] else None,
            )
        )
    options = {"acceptance_criteria": ["🧪" * 300] * 8}
    dependencies = [_create(work, "Dependency", **options) for _ in range(12)]
    task = _create(work, "Task", parent_work_item_id=parents[-1].work_item_id)
    for item in dependencies:
        work.add_dependency(task.work_item_id, item.work_item_id)
    (tmp_path / "unreferenced.txt").write_text("Ordinary unrelated contents.", encoding="utf-8")
    service = ContextService(tmp_path)
    projection = service.create(task.work_item_id, "codex")
    assert len(canonical_bytes(projection.canonical_payload)) <= MAX_PROJECTION_BYTES
    sources = service.sources(projection.projection_id, limit=25)
    assert len([row for row in sources if row.reason == "PARENT"]) == 6
    assert len([row for row in sources if row.reason == "DEPENDENCY"]) <= 8
    assert all(row.kind == "WORK_ITEM" for row in sources)
    assert service.create(task.work_item_id, "codex") == projection


def test_redaction_normalizes_low_entropy_secrets_and_excludes_artifact_rows():
    assignments = "OPENAI_API_KEY=short_fixture; password: tiny_fixture"
    private_key = "-----BEGIN RSA PRIVATE KEY-----\nkey-body-fixture\n-----END RSA PRIVATE KEY-----"
    original = {
        "description": f"{assignments}\n{private_key}\nAuthorization: Bearer bearer_fixture",
        "access_token": "bare-field-fixture",
        "refs": [
            {"path": "config/.env.stage", "sha256": "a" * 64},
            {"relative_path": r"config\.env.stage", "sha256": "b" * 64},
            {"location": r"C:\secret-root-fixture\credentials.json", "sha256": "c" * 64},
        ],
    }
    value, categories = redact(original)
    assert set(categories) == {
        "PRIVATE_KEY",
        "SECRET_PATH",
        "SENSITIVE_ASSIGNMENT",
        "SENSITIVE_FIELD",
    }
    assert value["refs"] == [{"excluded": "SECRET_PATH"}] * 3
    assert "access_token" not in value
    encoded = canonical_bytes(value).decode()
    assert "fixture" not in encoded
    assert sanitize_text("C:\\fixture\\work.cpp") == sanitize_text("/tmp/fixture/work.cpp")
    assert (
        sanitize_text("Authorization: Basic low_basic_fixture") == "[redacted sensitive assignment]"
    )
    assert sanitize_text("Look at .env.local") == "Look at [excluded secret path]"
    assert redact(original) == (value, categories)


def test_handoff_is_redacted_idempotent_and_retains_generation_cutoff(tmp_path):
    initialize(tmp_path)
    work = WorkService(tmp_path)
    item = _create(work, "Use password=low_context_fixture; retain scope")
    sessions = SessionRepository(tmp_path)
    source = sessions.create(
        item.work_item_id,
        provider="codex",
        owner_id="fixture-owner",
        timeout_seconds=15,
        native_resume=True,
        envelope_sha256="a" * 64,
    )
    fence = (source.session_id, source.owner_id, source.run_generation)
    sessions.running(*fence)
    sessions.observe(
        *fence,
        "OUTPUT",
        {"text": "API_KEY=low_handoff_fixture; useful observation"},
        native_session_id="fixture-resume",
    )
    handoffs = HandoffService(tmp_path)
    with pytest.raises(ContextError, match="stable terminal"):
        handoffs.create(source.session_id)
    sessions.finish(*fence, "INTERRUPTED")
    old = handoffs.create(source.session_id)
    assert handoffs.create(source.session_id) == old
    assert old.canonical_payload["authority"] == "DERIVED"
    assert old.canonical_payload["observations"][-1]["sequence"] == old.event_cutoff
    assert "[redacted sensitive assignment]" in json.dumps(old.canonical_payload)
    assert "low_handoff_fixture" not in json.dumps(old.canonical_payload)
    resumed = sessions.recover(source.session_id, owner_id="second-owner", envelope_sha256="a" * 64)
    new_fence = (resumed.session_id, resumed.owner_id, resumed.run_generation)
    sessions.running(*new_fence)
    sessions.finish(*new_fence, "FAILED")
    new = handoffs.create(source.session_id)
    assert (new.run_generation, old.run_generation) == (2, 1)
    assert new.event_cutoff > old.event_cutoff and new.digest != old.digest
    assert handoffs.get(old.handoff_id) == old
    assert handoffs.list(item.work_item_id, source.session_id) == [new, old]
    with handoffs.repository.read() as connection:
        assert handoffs.for_source(connection, sessions.get(source.session_id)) == new
    with pytest.raises(ContextError, match="generation changed"):
        handoffs.create(source.session_id, generation=old.run_generation)
    assert handoffs.create(source.session_id, generation=new.run_generation) == new
    assert work.get(item.work_item_id) == item

    context = ContextService(tmp_path)
    projection = context.create(item.work_item_id, "codex")
    captures = context.sources(projection.projection_id)
    assert [(row.authority, row.identity) for row in captures if row.reason == "HANDOFF"] == [
        ("DERIVED", new.handoff_id)
    ]
    assert "low_context_fixture" not in json.dumps(projection.canonical_payload)
    # Source owners own their preexisting bytes. Newly derived records carry only redacted captures.
    db = Path(tmp_path) / ".corinthos" / "state.db"
    with closing(sqlite3.connect(db)) as connection:
        for table in ("context_projections", "context_projection_sources", "session_handoffs"):
            values = json.dumps(connection.execute(f"SELECT * FROM {table}").fetchall())
            assert "low_context_fixture" not in values and "low_handoff_fixture" not in values


def _terminal_handoff(root, item, *, provider="codex"):
    sessions = SessionRepository(root)
    session = sessions.create(
        item.work_item_id,
        provider=provider,
        owner_id="fixture-owner",
        timeout_seconds=15,
        envelope_sha256="a" * 64,
    )
    fence = session.session_id, session.owner_id, session.run_generation
    sessions.running(*fence)
    sessions.observe(*fence, "OUTPUT", {"text": "First useful observation."})
    sessions.finish(*fence, "SUCCEEDED")
    return HandoffService(root).create(session.session_id, generation=session.run_generation)


def test_required_handoff_is_exact_and_replay_freezes_its_first_projection(tmp_path):
    initialize(tmp_path)
    work = WorkService(tmp_path)
    item = _create(work, "Use the first exact handoff")
    first = _terminal_handoff(tmp_path, item)
    latest = _terminal_handoff(tmp_path, item)
    service = ContextService(tmp_path)
    normal = service.create(item.work_item_id, "claude")
    assert "required_handoff_id" not in normal.canonical_payload
    assert [
        row.identity for row in service.sources(normal.projection_id) if row.reason == "HANDOFF"
    ] == [latest.handoff_id]

    def lookup():
        with service.repository.read() as connection:
            return service.switch_projection(
                connection, item.project_id, item.work_item_id, "claude", first.handoff_id
            )

    assert lookup() is None
    exact = service.create(item.work_item_id, "claude", required_handoff_id=first.handoff_id)
    assert exact.canonical_payload["required_handoff_id"] == first.handoff_id
    captures = service.sources(exact.projection_id)
    assert captures[0].identity == item.work_item_id
    required = [row for row in captures if row.reason == "HANDOFF"]
    assert required == [captures[1]]
    assert (
        required[0].kind,
        required[0].authority,
        required[0].identity,
        required[0].revision,
    ) == (
        "SESSION_HANDOFF",
        "DERIVED",
        first.handoff_id,
        first.digest,
    )
    assert required[0].capture == first.canonical_payload
    work.update(item.work_item_id, objective="Changed after the switch projection was sealed.")
    assert (
        lookup()
        == service.create(item.work_item_id, "claude", required_handoff_id=first.handoff_id)
        == exact
    )
    assert service.verify(exact.projection_id) == exact
    assert service.create(item.work_item_id, "claude") != normal
    unrelated = _create(work, "Other Work Item")
    with pytest.raises(ContextError, match="does not match"):
        service.create(unrelated.work_item_id, "claude", required_handoff_id=first.handoff_id)
    with pytest.raises(ContextError, match="does not match"):
        service.create(item.work_item_id, "codex", required_handoff_id=first.handoff_id)
    with pytest.raises(ContextError, match="was not found"):
        service.create(item.work_item_id, "claude", required_handoff_id="handoff-absent")


def test_required_handoff_reserves_projection_capacity(tmp_path, monkeypatch):
    initialize(tmp_path)
    work = WorkService(tmp_path)
    parent = _create(work, "Optional ancestor")
    item = _create(work, "Budget test", parent_work_item_id=parent.work_item_id)
    handoff = _terminal_handoff(tmp_path, item)
    service = ContextService(tmp_path)
    monkeypatch.setattr(context_projection, "MAX_SOURCES", 2)
    ordinary = service.create(item.work_item_id, "claude")
    assert [source.reason for source in service.sources(ordinary.projection_id)] == [
        "WORK_ITEM",
        "PARENT",
    ]
    exact = service.create(item.work_item_id, "claude", required_handoff_id=handoff.handoff_id)
    assert [source.reason for source in service.sources(exact.projection_id)] == [
        "WORK_ITEM",
        "HANDOFF",
    ]

    too_large = _terminal_handoff(tmp_path, item)
    monkeypatch.setattr(
        context_projection,
        "MAX_PROJECTION_BYTES",
        len(canonical_bytes(exact.canonical_payload)) - 512,
    )
    with pytest.raises(ContextError, match="exceeds the Context budget"):
        service.create(item.work_item_id, "claude", required_handoff_id=too_large.handoff_id)
    with service.repository.read() as connection:
        assert (
            service.switch_projection(
                connection, item.project_id, item.work_item_id, "claude", too_large.handoff_id
            )
            is None
        )


@pytest.mark.parametrize(
    "column", ["canonical_payload", "projection_digest", "source_set_digest", "capture"]
)
def test_tampered_projection_fails_closed(tmp_path, column):
    initialize(tmp_path)
    item = _create(WorkService(tmp_path))
    context = ContextService(tmp_path)
    projection = context.create(item.work_item_id, "codex")
    original = context.repository.projection_sources
    if column == "capture":
        values = context.repository.projection_sources

        def tamper(*args, **kwargs):
            from dataclasses import replace

            sources = values(*args, **kwargs)
            sources[0] = replace(sources[0], capture={"project_id": projection.project_id})
            return sources

        context.repository.projection_sources = tamper
    else:
        values = context.repository.get_projection

        def tamper(*args, **kwargs):
            from dataclasses import replace

            result = values(*args, **kwargs)
            return replace(result, **{column: {} if column == "canonical_payload" else "f" * 64})

        context.repository.get_projection = tamper
    with pytest.raises(ContextError, match="failed verification"):
        context.verify(projection.projection_id)
    assert original
