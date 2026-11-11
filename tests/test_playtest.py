# SPDX-License-Identifier: MPL-2.0
"""Synthetic orchestration fixtures; these do not establish formal Validation proof."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from corinthos.contracts import ConflictError, IntegrityError
from corinthos.contracts.artifacts import private_directory
from corinthos.lifecycle.builds import BuildService
from corinthos.lifecycle.playtest import PlaytestService
from corinthos.lifecycle.repository import digest

INSPECTED = {
    "process_stopped": True,
    "effects_inspected": True,
    "summary": "Synthetic fixture: no process was launched; data inspected.",
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Replace only independent admission, testing real orchestration/store/filesystem."""
    root = tmp_path / "project"
    root.mkdir()
    service = PlaytestService(root)
    service.configure("project-test", enabled=True)
    admitted = {}

    def synthetic_admission(self, build_id, connection):
        assert connection.in_transaction
        record = self.repository.get("BUILD", build_id, connection=connection)
        if record["state"] != "SEALED" or not admitted.get(build_id, False):
            raise ConflictError("Synthetic fixture: exact newest gate is not admissible.")
        return {
            "build_id": build_id,
            "project_id": record["project_id"],
            **record["origin"],
            "record_version": record["version"],
        }

    monkeypatch.setattr(BuildService, "require_eligible", synthetic_admission)

    def build(
        name,
        *,
        milestone="m1",
        milestones=None,
        checkpoints=None,
        project_id="project-test",
        workflow="wf-rev1",
    ):
        folder = private_directory(root, "snapshots", create=True) / name
        folder.mkdir()
        candidate = folder / "candidate"
        candidate.mkdir()
        (candidate / "main.txt").write_text(name, encoding="utf-8")
        (candidate / "second.txt").write_text("retention test", encoding="utf-8")
        manifest = folder / "manifest.json"
        manifest.write_text("Synthetic build manifest, not formal proof.", encoding="utf-8")
        origin = {
            "artifact_identity": {"build_id": name, "content_sha256": digest({"name": name})},
            "workflow_ref": {
                "contract_id": "workflow-test",
                "revision_id": workflow,
                "project_id": project_id,
                "contract_type": "WORKFLOW",
            },
            "milestone_id": milestone,
            "milestone_ids": milestones or [milestone],
            "checkpoint_ids": checkpoints or ["cp1"],
            "candidate_root": str(candidate),
            "manifest_path": str(manifest),
            "manifest_sha256": "a" * 64,
        }
        service.repository.create("BUILD", project_id, origin, record_id=name, state="SEALED")
        admitted[name] = True
        return name

    return service, build, admitted


def test_atomic_waiting_promotion_tracker_and_idempotence(project):
    service, build, _ = project
    first = build("build-first")
    second = build(
        "build-second", milestone="m2", milestones=["m1", "m2"], checkpoints=["cp1", "cp2"]
    )
    promoted = service.promote("project-test", first, operation_id="promote-first")
    session = service.start("project-test", operation_id="start-first")
    tracker = promoted["project"]["tracker_id"]
    waiting = service.promote("project-test", second, operation_id="promote-second")
    assert waiting["state"] == "WAITING"
    assert waiting["project"]["active_build_id"] == first
    assert waiting["project"]["pending_build_id"] == second
    assert service.status("project-test")["pins"][0]["record_id"] == session["record_id"]
    service.end(session["record_id"], inspection=INSPECTED, operation_id="end-first")
    final = service.promote("project-test", second, operation_id="promote-second")
    assert final["project"]["tracker_id"] == tracker
    assert final["project"]["active_build_id"] == second
    assert final["project"]["pending_build_id"] is None
    count = len(service.repository.events("project-test"))
    assert service.promote("project-test", second, operation_id="promote-second") == final
    assert len(service.repository.events("project-test")) == count
    assert service.start("project-test", operation_id="start-first") == session
    assert service.repository.get("SESSION", session["record_id"])["origin"]["build_id"] == first


def test_invalid_queued_candidate_cannot_trap_inspected_end(project):
    service, build, admitted = project
    first, second = build("build-first"), build("build-repair")
    service.promote("project-test", first)
    session = service.start("project-test")
    service.promote("project-test", second, operation_id="queued")
    admitted[second] = False
    assert service.end(session["record_id"], inspection=INSPECTED)["state"] == "ENDED"
    with pytest.raises(ConflictError, match="newest gate"):
        service.promote("project-test", second, operation_id="queued")
    assert service.status("project-test")["project"]["active_build_id"] == first
    service.cancel_pending("project-test", second, reason="Independent gate became inadmissible.")
    assert service.repository.get("OPERATION", "queued")["state"] == "CANCELLED"


def test_cumulative_lineage_and_foreign_project_negatives(project):
    service, build, _ = project
    active = build(
        "build-active", milestone="m2", milestones=["m1", "m2"], checkpoints=["cp1", "cp2"]
    )
    service.promote("project-test", active)
    for candidate in (
        build("build-regress", milestone="m1"),
        build("build-missing-cp", milestone="m2", milestones=["m1", "m2"]),
        build("build-other-wf", milestone="m2", milestones=["m1", "m2"], workflow="wf-rev2"),
        build("build-foreign", project_id="other-project"),
    ):
        with pytest.raises(IntegrityError):
            service.promote("project-test", candidate)
    assert service.status("project-test")["project"]["active_build_id"] == active


def test_different_pending_request_conflicts_and_operation_binding(project):
    service, build, _ = project
    first, second, third = build("build-first"), build("build-second"), build("build-third")
    service.promote("project-test", first)
    service.start("project-test")
    service.promote("project-test", second, operation_id="queued")
    with pytest.raises(ConflictError):
        service.promote("project-test", third)
    with pytest.raises(ConflictError, match="exact request"):
        service.promote("project-test", third, operation_id="queued")


def test_isolated_data_and_no_expiry_unpin(project):
    service, build, _ = project
    first = build("build-first")
    other = build("build-other")
    service.promote("project-test", first)
    with pytest.raises(ConflictError):
        service.start("project-test", build_id=other)
    a, b = service.start("project-test"), service.start("project-test")
    assert a["origin"]["data_root"] != b["origin"]["data_root"]
    assert Path(a["origin"]["data_root"]).is_dir()
    assert a["origin"]["launch_mode"] == "EXPLICIT_LOGICAL_PIN"
    assert not Path(a["origin"]["data_root"]).is_relative_to(
        Path(a["origin"]["admission"]["candidate_root"])
    )
    restarted = PlaytestService(service.root)
    assert len(restarted.status("project-test")["pins"]) == 2
    with pytest.raises(IntegrityError, match="Inspect actual"):
        restarted.end(a["record_id"], inspection={"process_stopped": True})
    with pytest.raises(ConflictError):
        restarted.configure("project-test", enabled=False)


def test_last_pin_switch_creates_successor_and_preserves_origin(project):
    service, build, _ = project
    first, second = build("build-first"), build("build-second")
    service.promote("project-test", first)
    old = service.start("project-test")
    extra = service.start("project-test")
    with pytest.raises(ConflictError, match="Other sessions"):
        service.switch(old["record_id"], second, inspection=INSPECTED)
    assert service.repository.get("SESSION", old["record_id"])["state"] == "OPEN"
    service.end(extra["record_id"], inspection=INSPECTED)
    successor = service.switch(
        old["record_id"], second, inspection=INSPECTED, operation_id="switch-id"
    )
    assert successor["origin"]["predecessor_id"] == old["record_id"]
    assert successor["origin"]["build_id"] == second
    previous = service.repository.get("SESSION", old["record_id"])
    assert previous["state"] == "SWITCHED" and previous["origin"] == old["origin"]
    assert successor["origin"]["data_root"] != old["origin"]["data_root"]
    assert (
        service.switch(old["record_id"], second, inspection=INSPECTED, operation_id="switch-id")
        == successor
    )


def test_start_crash_keeps_pin_until_inspected_recovery(project, monkeypatch):
    service, build, _ = project
    service.promote("project-test", build("build-first"))

    def fail(*args, **kwargs):
        raise OSError("Synthetic data preparation interruption")

    monkeypatch.setattr(service, "_prepare_data", fail)
    with pytest.raises(OSError):
        service.start("project-test", operation_id="crashed-start")
    restarted = PlaytestService(service.root)
    pin = restarted.status("project-test")["pins"][0]
    assert pin["state"] == "INTERRUPTED"
    with pytest.raises(ConflictError):
        restarted.start("project-test", operation_id="crashed-start")
    with pytest.raises(ConflictError):
        restarted.abandon_operation("crashed-start", inspection=INSPECTED)
    restarted.end(pin["record_id"], inspection=INSPECTED)
    assert (
        restarted.abandon_operation("crashed-start", inspection=INSPECTED)["state"] == "CANCELLED"
    )


def test_start_rechecks_newest_gate_after_outside_writer_data_preparation(project, monkeypatch):
    service, build, admitted = project
    first = build("build-first")
    service.promote("project-test", first)
    prepare = service._prepare_data

    def new_blocked_gate(*args, **kwargs):
        result = prepare(*args, **kwargs)
        admitted[first] = False
        return result

    monkeypatch.setattr(service, "_prepare_data", new_blocked_gate)
    with pytest.raises(ConflictError, match="newest gate"):
        service.start("project-test", operation_id="start-raced-gate")
    pin = service.status("project-test")["pins"][0]
    assert pin["state"] == "INTERRUPTED"
    assert service.repository.get("OPERATION", "start-raced-gate")["state"] == "INTERRUPTED"


def test_interrupted_switch_retains_old_pin_and_restarts_exact_intent(project, monkeypatch):
    service, build, _ = project
    first, second = build("build-first"), build("build-second")
    service.promote("project-test", first)
    old = service.start("project-test")
    prepare = service._prepare_data

    def prepare_then_interrupt(*args, **kwargs):
        prepare(*args, **kwargs)
        raise OSError("Synthetic crash after owned data creation")

    monkeypatch.setattr(service, "_prepare_data", prepare_then_interrupt)
    with pytest.raises(OSError):
        service.switch(
            old["record_id"], second, inspection=INSPECTED, operation_id="switch-restart"
        )
    restarted = PlaytestService(service.root)
    assert restarted.status("project-test")["project"]["active_build_id"] == first
    assert restarted.status("project-test")["pins"][0]["record_id"] == old["record_id"]
    assert (
        restarted.switch(
            old["record_id"], second, inspection=INSPECTED, operation_id="switch-restart"
        )["origin"]["build_id"]
        == second
    )


def test_old_feedback_keeps_origin_and_treatment_history(project):
    service, build, _ = project
    first, second = build("build-first"), build("build-second")
    service.promote("project-test", first)
    session = service.start("project-test")
    service.end(session["record_id"], inspection=INSPECTED)
    service.promote("project-test", second)
    feedback = service.feedback(
        "project-test",
        first,
        "Old build issue\x1b[31m",
        session_id=session["record_id"],
        operation_id="feedback-retry",
    )
    assert feedback["origin"]["build_id"] == first
    assert feedback["origin"]["observer"] == "OPERATOR"
    assert feedback["state"] == "OPEN"
    treated = service.triage(
        feedback["record_id"],
        category="BUG",
        reason="Reproduce under exact original scope.",
        expected_version=1,
    )
    assert treated["snapshot"]["route"] == "WORKFLOW_VALIDATION"
    assert treated["snapshot"]["dispatch"] == "RECORDED_FOR_EXPLICIT_ACTION"
    assert treated["origin"] == feedback["origin"]
    with pytest.raises(ConflictError):
        service.triage(
            feedback["record_id"], category="REQUIREMENT", reason="stale", expected_version=1
        )
    assert (
        service.feedback(
            "project-test",
            first,
            "Old build issue\x1b[31m",
            session_id=session["record_id"],
            operation_id="feedback-retry",
        )
        == feedback
    )
    assert len(service.repository.events("project-test", record_id=feedback["record_id"])) == 2
    requirement = service.feedback("project-test", second, "New product choice.", synthetic=True)
    assert requirement["origin"]["observer"] == "SYNTHETIC"
    assert (
        service.triage(
            requirement["record_id"], category="REQUIREMENT", reason="Owner decision required."
        )["snapshot"]["route"]
        == "PROJECT_MANAGER"
    )


def test_feedback_cannot_claim_unpromoted_build_or_other_session(project):
    service, build, _ = project
    first, second = build("build-first"), build("build-second")
    service.promote("project-test", first)
    session = service.start("project-test")
    with pytest.raises(ConflictError, match="historical"):
        service.feedback("project-test", second, "Not an actual available build.")
    service.end(session["record_id"], inspection=INSPECTED)
    service.promote("project-test", second)
    with pytest.raises(IntegrityError, match="actual eligible session"):
        service.feedback("project-test", second, "Wrong session", session_id=session["record_id"])


def test_retention_protects_active_pending_pins_versions_and_previous(project):
    service, build, _ = project
    versioned, old, rollback, active, pending = [
        build("build-" + name) for name in ("version", "old", "rollback", "active", "pending")
    ]
    identity = service.repository.get("BUILD", versioned)["origin"]["artifact_identity"]
    service.repository.create(
        "VERSION", "project-test", {"artifact_identity": identity}, state="DELIVERED"
    )
    service.promote("project-test", active)
    service.start("project-test")
    service.promote("project-test", pending)
    preview = service.retention_preview("project-test")
    assert preview["protected_build_ids"] == sorted([versioned, rollback, active, pending])
    assert [row["build_id"] for row in preview["targets"]] == [old]
    result = service.retention_apply(preview, operation_id="prune-old")
    assert result["retired_build_ids"] == [old]
    record = service.repository.get("BUILD", old)
    assert record["state"] == "RETIRED"
    assert not Path(record["origin"]["candidate_root"]).exists()
    assert Path(record["origin"]["manifest_path"]).is_file()
    assert service.retention_apply(preview, operation_id="prune-old") == result


def test_retention_stale_preview_and_forged_paths_never_delete(project):
    service, build, _ = project
    old, active = build("build-old"), build("build-active")
    service.promote("project-test", active)
    preview = service.retention_preview("project-test", keep_previous=0)
    source = Path(service.repository.get("BUILD", old)["origin"]["candidate_root"])
    (source / "new.txt").write_text("Unexpected new file", encoding="utf-8")
    with pytest.raises(ConflictError, match="changed"):
        service.retention_apply(preview)
    assert source.exists()
    preview = service.retention_preview("project-test", keep_previous=0)
    preview["targets"][0]["path"] = str(service.root)
    with pytest.raises(IntegrityError, match="hash"):
        service.retention_apply(preview)
    assert (source / "main.txt").exists()


def test_retention_prefers_actual_previous_promotion_for_rollback(project):
    service, build, _ = project
    old = build("build-previous-active")
    service.promote("project-test", old)
    current = build("build-current")
    service.promote("project-test", current)
    unused = build("build-later-unpromoted")
    preview = service.retention_preview("project-test")
    assert old in preview["protected_build_ids"]
    assert [row["build_id"] for row in preview["targets"]] == [unused]


def test_retention_rejects_hardlinks_and_preserves_daily_data(project):
    service, build, _ = project
    old = build("build-old")
    daily = service.root / "daily.txt"
    daily.write_text("Keep daily application data", encoding="utf-8")
    source = Path(service.repository.get("BUILD", old)["origin"]["candidate_root"])
    try:
        (source / "daily-link.txt").hardlink_to(daily)
    except OSError:
        pytest.skip("Hardlinks are unavailable on this filesystem.")
    with pytest.raises(IntegrityError, match="ordinary unlinked"):
        service.retention_preview("project-test", keep_previous=0)
    assert daily.read_text(encoding="utf-8") == "Keep daily application data"


def test_retention_partial_delete_requires_actual_inspection_and_recovers(project, monkeypatch):
    service, build, _ = project
    old = build("build-old")
    plan = service.retention_preview("project-test", keep_previous=0)
    unlink = Path.unlink
    calls = []

    def interrupted(path, *args, **kwargs):
        if path.name == "second.txt":
            raise OSError("Synthetic crash after first exact deletion")
        calls.append(str(path))
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted)
    with pytest.raises(OSError):
        service.retention_apply(plan, operation_id="partial-prune")
    assert calls
    assert service.repository.get("BUILD", old)["state"] == "RETIRING"
    restarted = PlaytestService(service.root)
    with pytest.raises(IntegrityError, match="Inspect actual"):
        restarted.retention_apply(plan, operation_id="partial-prune")
    monkeypatch.setattr(Path, "unlink", unlink)
    result = restarted.retention_apply(plan, operation_id="partial-prune", inspection=INSPECTED)
    assert result["retired_build_ids"] == [old]
    assert restarted.repository.get("BUILD", old)["state"] == "RETIRED"


def test_retention_rechecks_bytes_before_unlink_even_for_same_inode_edit(project, monkeypatch):
    from corinthos.lifecycle import playtest

    service, build, _ = project
    build("build-old")
    plan = service.retention_preview("project-test", keep_previous=0)
    candidate = Path(plan["targets"][0]["path"]) / "main.txt"
    original_inode = candidate.stat().st_ino
    inventory = playtest._inventory
    calls = []

    def edit_after_inventory(path):
        result = inventory(path)
        calls.append(str(path))
        if len(calls) == 2:
            candidate.write_text("Changed in place after final inventory", encoding="utf-8")
        return result

    monkeypatch.setattr(playtest, "_inventory", edit_after_inventory)
    with pytest.raises(IntegrityError, match="changed before deletion"):
        service.retention_apply(plan, operation_id="prune-raced-bytes")
    assert candidate.stat().st_ino == original_inode
    assert candidate.read_text(encoding="utf-8") == "Changed in place after final inventory"
    assert service.repository.get("OPERATION", "prune-raced-bytes")["state"] == "INTERRUPTED"


def test_start_promotion_race_preserves_single_active_and_real_pin(project):
    service, build, _ = project
    first, second = build("build-first"), build("build-second")
    service.promote("project-test", first)

    def start():
        return PlaytestService(service.root).start("project-test", operation_id="race-start")

    def promote():
        return PlaytestService(service.root).promote(
            "project-test", second, operation_id="race-promote"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(start), pool.submit(promote)
        session, promotion = a.result(), b.result()
    status = service.status("project-test")
    assert len(status["pins"]) == 1
    assert session["origin"]["build_id"] == status["project"]["active_build_id"]
    assert promotion["state"] in {"PROMOTED", "WAITING"}
