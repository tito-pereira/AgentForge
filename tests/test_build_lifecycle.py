# SPDX-License-Identifier: MPL-2.0
"""Labelled synthetic authority exercises real build bytes, commands and audits."""

import argparse
import json
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from test_validation_planning import _assess, _bindings
from test_validation_planning import planner as source_fixture
from test_workflow_runtime import SyntheticAdapter, _accept

from corinthos.contracts import ConflictError, IntegrityError
from corinthos.lifecycle.builds import BuildService
from corinthos.validation.runtime import ValidationRunner
from corinthos.workflow.build_cli import add_cli
from corinthos.workflow.runtime import WorkflowRunner
from corinthos.workflow.verification import (
    AuditExpectation,
    CheckpointSpec,
    CommandCheck,
    TechnicalReview,
    workspace_snapshot,
)


@pytest.fixture
def built(tmp_path):
    planner, refs = source_fixture.__wrapped__(tmp_path)
    store = planner.store
    checkpoint = store.get(refs["workflow"])["payload"]["checkpoints"][0]
    spec = CheckpointSpec(
        "greet",
        (
            CommandCheck(
                "source-check",
                checkpoint["verification_plan"][0],
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; assert Path('README.md').read_text() == 'Hello Ada'",
                ),
            ),
        ),
        {checkpoint["deliverables"][0]: ["README.md"]},
        ("README.md",),
    )

    def write(context):
        (context.workspace / "README.md").write_text("Hello Ada", encoding="utf-8")

    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=write), reviewer=_accept)
    execution = runner.configure(refs["workflow"], [spec], actor_id="synthetic-operator")
    assert runner.run_next(execution["execution_id"])["state"] == "COMPLETED"
    service = BuildService(store)
    build = service.prepare(refs["workflow"], "early", execution["execution_id"], tmp_path)
    return service, build, planner, refs, execution, spec


def _ready(service, build, *, fail=False, reviewer=True):
    checks = tuple(
        CommandCheck(
            "scenario-" + str(i),
            scenario,
            (
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('README.md').read_text() == 'Hello Ada'"
                if not fail
                else "raise SystemExit(2)",
            ),
        )
        for i, scenario in enumerate(build["origin"]["scenarios"])
    )

    def review(request):
        return TechnicalReview(
            "synthetic-technical-reviewer",
            True,
            tuple(row["criterion_id"] for row in request["criteria"]),
            request["artifact_identity"],
            ("Synthetic fixture inspected actual command results and retained candidate.",),
        )

    return service.readiness(
        build["record_id"], checks=checks, reviewer=review if reviewer else None
    )


def _plan(planner, refs, *, milestone="early"):
    draft = planner.derive(
        refs["project"], "PLAYTEST_MILESTONE", target_ref=refs["workflow"], target_ids=[milestone]
    )
    bindings = _bindings(draft)
    return planner.publish(
        draft, bindings, _assess(draft, bindings), actor_id="synthetic-validation-planner"
    )


def _review(request):
    return {
        "evaluator": request["evaluator"],
        "artifact_identity": request["artifact_identity"],
        "inspected": request["paths"],
        "status": "CONFORMANT",
        "rationale": "Synthetic independent fixture inspects the retained exact README candidate.",
    }


def _admit(service, build):
    with service.repository.transaction() as connection:
        return service.require_eligible(build["record_id"], connection)


def test_sealed_build_is_a_real_copy_with_complete_inventory_and_no_forged_commit(built, tmp_path):
    service, build, *_ = built
    origin = build["origin"]
    candidate = Path(origin["candidate_root"])
    assert candidate != tmp_path
    assert "commit" not in origin["artifact_identity"]
    assert origin["artifact_identity"]["build_id"] == build["record_id"]
    assert (
        service.identity_for_candidate(candidate, build["record_id"]) == origin["artifact_identity"]
    )
    (tmp_path / "README.md").write_text("Development changed", encoding="utf-8")
    assert (candidate / "README.md").read_text() == "Hello Ada"
    assert (
        service.identity_for_candidate(candidate, build["record_id"]) == origin["artifact_identity"]
    )
    (candidate / "dist").mkdir()
    (candidate / "dist" / "extra.whl").write_bytes(b"Unobserved generated package")
    assert "dist/extra.whl" not in workspace_snapshot(candidate)["files"]
    with pytest.raises(IntegrityError, match="bytes changed"):
        service.identity_for_candidate(candidate, build["record_id"])


def test_real_package_bytes_are_sealed_and_command_data_paths_are_isolated(built, tmp_path):
    service, _, _, refs, execution, _ = built
    (tmp_path / "README.md").write_text("Hello Ada", encoding="utf-8")
    check = CommandCheck(
        "package",
        "Package the source",
        (
            sys.executable,
            "-c",
            "import os; from pathlib import Path; Path('packages').mkdir(); Path('packages/example.whl').write_bytes(b'actual wheel fixture'); Path('config.txt').write_text(os.environ['LOCALAPPDATA'])",
        ),
    )
    build = service.prepare(
        refs["workflow"],
        "early",
        execution["execution_id"],
        tmp_path,
        commands=(check,),
        package_paths=("packages/example.whl",),
    )
    candidate = Path(build["origin"]["candidate_root"])
    manifest = json.loads(Path(build["origin"]["manifest_path"]).read_text())
    assert manifest["candidate"]["files"]["packages/example.whl"]["size"] == 20
    assert Path((candidate / "config.txt").read_text(encoding="utf-8")).is_relative_to(
        candidate.parent
    )
    assert (tmp_path / "packages").exists() is False
    (candidate / "packages/example.whl").write_bytes(b"different wheel")
    with pytest.raises(IntegrityError):
        service.identity_for_candidate(candidate, build["record_id"])


def test_raw_marker_and_wrong_candidate_cannot_supply_a_build_identity(built, tmp_path):
    service, build, *_ = built
    (tmp_path / "build.json").write_text(json.dumps(build["origin"]["artifact_identity"]))
    with pytest.raises(IntegrityError, match="exact owned"):
        service.identity_for_candidate(tmp_path, build["record_id"])
    with pytest.raises(IntegrityError):
        service.identity_for_candidate(Path(build["origin"]["candidate_root"]), "missing-build")


def test_readiness_requires_actual_scenarios_review_and_independent_audit(built):
    service, build, planner, refs, *_ = built
    with pytest.raises(ConflictError, match="readiness"):
        _admit(service, build)
    with pytest.raises(IntegrityError, match="every exact"):
        service.readiness(build["record_id"], checks=())
    assert _ready(service, build, reviewer=False)["snapshot"]["readiness"]["state"] == "BLOCKED"
    ready = _ready(service, build)
    assert ready["snapshot"]["readiness"]["state"] == "SATISFIED"
    with pytest.raises(ConflictError, match="plan"):
        _admit(service, build)
    plan = _plan(planner, refs)
    result = service.validate(
        build["record_id"], plan, evaluator="synthetic-independent-evaluator", reviewer=_review
    )
    document = service.store.get(result)
    identity = build["origin"]["artifact_identity"]
    assert document["payload"]["target_and_execution"]["artifact_identity"] == identity
    assert all(
        item["artifact_identity"] == identity for item in document["payload"]["evidence_refs"]
    )
    admission = _admit(service, build)
    assert admission["artifact_identity"] == identity
    assert admission["milestone_ids"] == ["early"]
    assert admission["checkpoint_ids"] == ["greet"]


def test_new_failed_readiness_cannot_leave_old_pass_eligible(built):
    service, build, planner, refs, *_ = built
    _ready(service, build)
    plan = _plan(planner, refs)
    service.validate(
        build["record_id"], plan, evaluator="synthetic-independent-evaluator", reviewer=_review
    )
    assert _admit(service, build)
    assert _ready(service, build, fail=True)["snapshot"]["readiness"]["state"] == "BLOCKED"
    with pytest.raises(ConflictError, match="readiness"):
        _admit(service, build)


def test_latest_exact_unfinished_interrupted_and_blocked_audits_prevent_fallback(built):
    service, build, planner, refs, *_ = built
    _ready(service, build)
    plan = _plan(planner, refs)
    service.validate(
        build["record_id"], plan, evaluator="synthetic-independent-evaluator", reviewer=_review
    )
    runner = ValidationRunner(service.store)
    pending = runner.repository.start(
        plan,
        runner.repository.list()[-1]["context"],
        evaluator="synthetic-other-evaluator",
    )
    with pytest.raises(ConflictError, match="unfinished"):
        _admit(service, build)
    runner.recover(
        pending["run_id"],
        {
            "process_stopped": True,
            "effects_inspected": True,
            "reason": "Synthetic fixture owns no child process and inspected the untouched candidate.",
        },
    )
    with pytest.raises(ConflictError, match="proof"):
        _admit(service, build)
    service.validate(
        build["record_id"], plan, evaluator="synthetic-independent-evaluator", reviewer=_review
    )
    assert _admit(service, build)
    cancelled = threading.Event()
    cancelled.set()
    service.validate(
        build["record_id"],
        plan,
        evaluator="synthetic-independent-evaluator",
        reviewer=_review,
        cancel=cancelled,
    )
    with pytest.raises(ConflictError, match="proof"):
        _admit(service, build)


def test_tampered_seal_and_evidence_block_admission(built):
    service, build, planner, refs, *_ = built
    ready = _ready(service, build)
    plan = _plan(planner, refs)
    service.validate(
        build["record_id"], plan, evaluator="synthetic-independent-evaluator", reviewer=_review
    )
    proof = ready["snapshot"]["readiness"]["evidence"]
    path = service.root / ".corinthos/artifacts" / proof["path"]
    original = path.read_bytes()
    path.write_bytes(b"tampered readiness")
    with pytest.raises(IntegrityError):
        _admit(service, build)
    path.write_bytes(original)
    manifest = Path(build["origin"]["manifest_path"])
    manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(IntegrityError, match="manifest changed"):
        _admit(service, build)


def test_operation_id_replay_reconciles_and_changed_request_conflicts(built, tmp_path):
    service, _, _, refs, execution, _ = built
    options = (refs["workflow"], "early", execution["execution_id"], tmp_path)
    first = service.prepare(*options, operation_id="synthetic-build-operation")
    assert service.prepare(*options, operation_id="synthetic-build-operation") == first
    with pytest.raises(ConflictError, match="different"):
        service.prepare(
            refs["workflow"],
            "later",
            execution["execution_id"],
            tmp_path,
            operation_id="synthetic-build-operation",
        )


def test_frozen_build_seal_recovers_without_reexecuting_recipe(built, tmp_path, monkeypatch):
    service, _, _, refs, execution, _ = built
    finish = service._finish
    monkeypatch.setattr(
        service,
        "_finish",
        lambda operation: (_ for _ in ()).throw(
            ConflictError("Synthetic interruption after durable seal")
        ),
    )
    with pytest.raises(ConflictError, match="interruption"):
        service.prepare(
            refs["workflow"],
            "early",
            execution["execution_id"],
            tmp_path,
            operation_id="synthetic-interrupted-seal",
        )
    assert service.repository.get("OPERATION", "synthetic-interrupted-seal")["state"] == "FROZEN"
    monkeypatch.setattr(service, "_finish", finish)
    with pytest.raises(IntegrityError, match="inspection"):
        service.recover("synthetic-interrupted-seal", {})
    result = service.recover(
        "synthetic-interrupted-seal",
        {
            "process_stopped": True,
            "effects_inspected": True,
            "reason": "Synthetic fixture observed completed copy and no process.",
        },
    )
    assert result["state"] == "SEALED"
    assert service.recover("synthetic-interrupted-seal", {}) == result


def test_cumulative_scope_and_wrong_plan_target(built, tmp_path):
    service, build, planner, refs, execution, _ = built
    later = service.prepare(refs["workflow"], "later", execution["execution_id"], tmp_path)
    assert later["origin"]["milestone_ids"] == ["early", "later"]
    assert {row["criterion_id"] for row in later["origin"]["criteria"]} == {
        "early-ready",
        "later-ready",
    }
    _ready(service, build)
    with pytest.raises(IntegrityError, match="another exact"):
        service.validate(
            build["record_id"],
            _plan(planner, refs, milestone="later"),
            evaluator="synthetic-independent-evaluator",
        )


def test_circular_checkpoint_playtest_requirement_is_diagnosed(built, tmp_path):
    service, _, _, refs, execution, spec = built
    # Read-only diagnosis of the same typed placement the legacy runner supports.
    original = service.executions._view

    def circular(connection, row):
        value = original(connection, row)
        value["bindings"]["checkpoints"]["greet"] = replace(
            spec,
            audit_expectations=(
                AuditExpectation("PLAYTEST_MILESTONE", refs["workflow"], ("early",)),
            ),
        ).to_json()
        return value

    service.executions._view = circular
    with pytest.raises(ConflictError, match="Circular"):
        service.prepare(refs["workflow"], "early", execution["execution_id"], tmp_path)


def test_build_cli_parser_keeps_recipe_argv_and_reads_do_not_launch(built, capsys):
    service, build, *_ = built
    parser = argparse.ArgumentParser()
    add_cli(parser.add_subparsers(required=True))
    arguments = parser.parse_args(
        ["build", "--root", str(service.root), "show", build["record_id"]]
    )
    assert arguments.handler(arguments) == 0
    assert json.loads(capsys.readouterr().out)["record_id"] == build["record_id"]
    recipe = parser.parse_args(
        [
            "build",
            "prepare",
            "wf",
            "milestone",
            "execution",
            "--recipe-executable",
            sys.executable,
            "--recipe-arg=-m",
            "--recipe-arg=build",
        ]
    )
    assert recipe.recipe_arg == ["-m", "build"]


def test_old_raw_result_cannot_be_relabelled_as_a_build_audit(built):
    service, build, planner, refs, *_ = built
    _ready(service, build)
    plan = _plan(planner, refs)
    raw = ValidationRunner(service.store).run(
        plan,
        build["origin"]["candidate_root"],
        evaluator="synthetic-independent-evaluator",
        reviewer=_review,
    )
    identity = service.store.get(raw)["payload"]["target_and_execution"]["artifact_identity"]
    assert "build_id" not in identity
    assert identity["snapshot_id"] == build["origin"]["artifact_identity"]["snapshot_id"]
    with pytest.raises(ConflictError, match="missing or unfinished"):
        _admit(service, build)


def test_build_frozen_publication_rechecks_the_sealed_identity(built, monkeypatch):
    service, build, planner, refs, *_ = built
    _ready(service, build)
    plan = _plan(planner, refs)
    runner = ValidationRunner(service.store)
    monkeypatch.setattr(runner.repository, "finalize", runner.repository.freeze)
    frozen = runner.run(
        plan,
        build["origin"]["candidate_root"],
        build_id=build["record_id"],
        evaluator="synthetic-independent-evaluator",
        reviewer=_review,
    )
    assert frozen["state"] == "FROZEN"
    candidate = Path(build["origin"]["candidate_root"])
    (candidate / "README.md").write_text("changed after freeze", encoding="utf-8")
    with pytest.raises(IntegrityError, match="bytes changed"):
        runner.publish_frozen(frozen["run_id"])
    (candidate / "README.md").write_text("Hello Ada", encoding="utf-8")
    result = runner.publish_frozen(frozen["run_id"])
    assert (
        service.store.get(result)["payload"]["target_and_execution"]["artifact_identity"]
        == build["origin"]["artifact_identity"]
    )
    assert _admit(service, build)


def test_interrupted_preparation_blocks_blind_retry_until_real_inspection(built, tmp_path):
    service, _, _, refs, execution, _ = built
    failed = CommandCheck(
        "failed-package", "Package source", (sys.executable, "-c", "raise SystemExit(2)")
    )
    with pytest.raises(ConflictError, match="Build command failed"):
        service.prepare(
            refs["workflow"],
            "early",
            execution["execution_id"],
            tmp_path,
            commands=(failed,),
            operation_id="synthetic-failed-preparation",
        )
    with pytest.raises(ConflictError, match="previous build preparation"):
        service.prepare(refs["workflow"], "early", execution["execution_id"], tmp_path)
    recovered = service.recover(
        "synthetic-failed-preparation",
        {
            "process_stopped": True,
            "effects_inspected": True,
            "reason": "Synthetic test inspected the failed child and isolated partial files.",
        },
    )
    assert recovered["state"] == "CANCELLED"
    assert (
        service.prepare(refs["workflow"], "early", execution["execution_id"], tmp_path)["state"]
        == "SEALED"
    )


def test_exception_during_readiness_requires_inspection_and_does_not_preserve_pass(built):
    service, build, *_ = built
    _ready(service, build)
    check = CommandCheck(
        "readiness", build["origin"]["scenarios"][0], (sys.executable, "-c", "pass")
    )

    def interrupted(_):
        raise ConflictError("Synthetic disappearance before review completed")

    with pytest.raises(ConflictError, match="disappearance"):
        service.readiness(build["record_id"], checks=(check,), reviewer=interrupted)
    record = service.get(build["record_id"])
    assert record["snapshot"]["readiness"]["state"] == "RUNNING"
    with pytest.raises(ConflictError, match="unfinished readiness"):
        _ready(service, build)
    operation = record["snapshot"]["readiness"]["operation_id"]
    service.recover(
        operation,
        {
            "process_stopped": True,
            "effects_inspected": True,
            "reason": "Synthetic test inspected the completed isolated child and review interruption.",
        },
    )
    assert service.repository.get("OPERATION", operation)["state"] == "CANCELLED"
    assert service.get(build["record_id"])["snapshot"]["readiness"]["state"] == "BLOCKED"
    assert _ready(service, build)["snapshot"]["readiness"]["state"] == "SATISFIED"
