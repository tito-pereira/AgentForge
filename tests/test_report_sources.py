# SPDX-License-Identifier: MPL-2.0
"""Synthetic authority fixtures exercise real pinned capture and retained proof."""

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from test_validation_runtime import _review
from test_validation_runtime import audit as audit
from test_workflow_runtime import SyntheticAdapter, _accept, _seed, _spec, _write_code

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    IntegrityError,
    PublishContext,
    approval_request,
)
from corinthos.report import fileguard, sources
from corinthos.report.sources import capture, require_unchanged
from corinthos.workflow import verification
from corinthos.workflow.runtime import WorkflowRunner

_ROOT = Path(__file__).resolve().parents[1]


def _project(runner, plan):
    return ContractRef.from_json(
        next(
            raw
            for raw in runner.store.get(plan)["payload"]["source_contract_refs"]
            if raw["contract_type"] == "PROJECT"
        )
    )


def _run(audit, **kwargs):
    runner, plan, candidate = audit
    return runner.run(
        plan, candidate, evaluator="synthetic-report-evaluator", reviewer=_review, **kwargs
    )


def _report(store, project, *, acceptance=None, suffix="report", created_at=None):
    document = json.loads((_ROOT / "examples/contracts/evidence-report.json").read_text("utf-8"))
    now = datetime.now(UTC).isoformat()
    document["metadata"].update(
        contract_id=f"synthetic-capture-{suffix}",
        revision_id=f"synthetic-capture-{suffix}-r1",
        created_at=created_at or now,
    )
    payload = document["payload"]
    payload["source_refs"] = [project.to_json()]
    payload["report_scope"].update(target_id=project.project_id, as_of=now)
    payload["version_and_delivery_lineage"].update(
        project_id=project.project_id, technical_validation="NOT_VERIFIED"
    )
    payload["execution_and_validation_digest"].update(
        validation_result_refs=[], blocked_check_ids=[]
    )
    if acceptance is not None:
        approval_id = f"synthetic-{suffix}-human-review"
        document["metadata"]["approval"] = {
            "kind": "HUMAN",
            "approval_id": approval_id,
            "actor_id": "synthetic-review-owner",
        }
        payload["version_and_delivery_lineage"].update(
            acceptance=acceptance,
            delivery="DELIVERED",
            build_id="synthetic-reviewed-build",
            milestone_id="synthetic-reviewed-milestone",
        )
        payload["feedback_and_acceptance"] = {
            "review_approval_id": approval_id,
            "feedback": [
                {
                    "feedback_id": "synthetic-review-feedback",
                    "build_id": "synthetic-reviewed-build",
                    "milestone_id": "synthetic-reviewed-milestone",
                    "status": "Synthetic owner review retained for the original delivered build.",
                }
            ],
        }
    receipt = approval_request(document) if acceptance is not None else None
    return store.publish(
        document,
        context=PublishContext(
            "REPORT",
            document["metadata"]["provenance"]["actor_id"],
            (lambda actual: actual == receipt) if receipt is not None else None,
        ),
    )


def test_current_capture_is_read_only_and_pins_all_managed_gate_reads(audit):
    runner, plan, candidate = audit
    result = _run(audit)
    project = _project(runner, plan)
    before = runner.store.list_events()
    snapshot = capture(runner.store, project, kind="PRODUCT", candidate_root=candidate)
    assert runner.store.list_events() == before
    assert snapshot["selected_results"] == [runner.store.get(result)]
    assert snapshot["gates"][0]["eligibility"] == "SATISFIED"
    assert {row["state"] for row in snapshot["evidence"]} == {"VERIFIED"}
    assert snapshot["manifest"]["source_documents"]
    assert "documents" not in snapshot["manifest"]
    assert all("snapshot" not in row for row in snapshot["operations"])
    with runner.store._transaction() as connection:
        require_unchanged(runner.store, connection, snapshot["manifest"])


def test_concurrent_source_publication_cannot_split_one_capture(audit, monkeypatch):
    runner, plan, candidate = audit
    _run(audit)
    project = _project(runner, plan)
    successor = deepcopy(runner.store.get(project))
    successor["metadata"].update(
        revision_id="synthetic-concurrent-project-r2", version=2, supersedes=project.to_json()
    )
    successor["metadata"]["approval"]["approval_id"] = "synthetic-concurrent-project-approval"
    successor["payload"]["vision"] = "A changed approved synthetic vision."
    receipt = approval_request(successor)
    with runner.store._connection() as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    original = sources._rows
    fired = False
    with ThreadPoolExecutor(max_workers=1) as executor:

        def race(connection, project_id):
            nonlocal fired
            rows = original(connection, project_id)
            if not fired:
                fired = True
                executor.submit(
                    runner.store.publish,
                    successor,
                    context=PublishContext(
                        "PROJECT_MANAGER",
                        successor["metadata"]["provenance"]["actor_id"],
                        lambda actual: actual == receipt,
                    ),
                ).result(timeout=5)
            return rows

        monkeypatch.setattr(sources, "_rows", race)
        snapshot = capture(runner.store, project, kind="PRODUCT", candidate_root=candidate)
    assert snapshot["active"][project.contract_id] == project.to_json()
    assert successor not in snapshot["documents"]
    assert snapshot["gates"][0]["eligibility"] == "SATISFIED"
    assert runner.store.resolve_active(project.contract_id) == successor
    with runner.store._transaction() as connection:
        with pytest.raises(ConflictError, match="sources changed"):
            require_unchanged(runner.store, connection, snapshot["manifest"])


def test_newer_interrupted_result_blocks_older_pass_and_other_candidate_stays_separate(
    audit, tmp_path
):
    runner, plan, candidate = audit
    first = _run(audit)
    cancel = threading.Event()
    cancel.set()
    stopped = _run(audit, cancel=cancel)
    other = tmp_path / "another-candidate"
    other.mkdir()
    (other / "README.md").write_text("different", encoding="utf-8")
    unrelated = runner.run(plan, other, evaluator="synthetic-report-evaluator", reviewer=_review)
    snapshot = capture(
        runner.store, _project(runner, plan), kind="PRODUCT", candidate_root=candidate
    )
    assert snapshot["selected_results"] == [runner.store.get(stopped)]
    assert snapshot["gates"][0]["eligibility"] == "BLOCKED"
    assert snapshot["gates"][0]["recorded_state"] == "BLOCKED"
    assert runner.store.get(first) in snapshot["documents"]
    assert runner.store.get(unrelated) in snapshot["documents"]
    assert runner.store.get(unrelated) not in snapshot["selected_results"]


def test_unavailable_required_proof_is_unverified_even_when_not_chosen_for_an_index(audit):
    runner, plan, candidate = audit
    result = _run(audit)
    document = runner.store.get(result)
    evidence = document["payload"]["evidence_refs"][-1]
    path = runner.store.database_path.parent / "artifacts" / evidence["path"]
    path.write_bytes(b"altered proof")
    snapshot = capture(
        runner.store, _project(runner, plan), kind="PRODUCT", candidate_root=candidate
    )
    assert snapshot["gates"][0]["recorded_state"] == "SATISFIED"
    assert snapshot["gates"][0]["eligibility"] == "NOT_VERIFIED"
    assert any(row["ref"] == evidence and row["state"] == "CORRUPT" for row in snapshot["evidence"])
    assert runner.store.get(result) == document


def test_historical_cutoff_uses_publication_order_without_current_gate_or_mutable_rows(
    audit, monkeypatch
):
    runner, plan, candidate = audit
    first = _run(audit)
    cutoff = next(
        row["occurred_at"]
        for row in runner.store.list_events()
        if row["revision_id"] == first.revision_id
    )
    cancel = threading.Event()
    cancel.set()
    _run(audit, cancel=cancel)
    monkeypatch.setattr(
        sources.ValidationGateConsumer,
        "consume",
        lambda *_: pytest.fail("History must not consume a current gate."),
    )
    snapshot = capture(
        runner.store,
        _project(runner, plan),
        kind="HISTORY",
        artifact_identity=runner.store.get(first)["payload"]["target_and_execution"][
            "artifact_identity"
        ],
        as_of=cutoff,
    )
    assert snapshot["mode"] == "AS_OF"
    assert snapshot["selected_results"] == [runner.store.get(first)]
    assert snapshot["gates"][0]["eligibility"] == "SATISFIED"
    assert not any(
        row["type"] in {"WORKFLOW_EXECUTION", "WORKFLOW_CHECKPOINT"}
        for row in snapshot["operations"]
    )
    with runner.store._transaction() as connection:
        require_unchanged(runner.store, connection, snapshot["manifest"])


def test_current_watermark_ignores_report_events_and_rejects_later_source_events(audit):
    runner, plan, candidate = audit
    _run(audit)
    project = _project(runner, plan)
    snapshot = capture(runner.store, project, kind="PRODUCT", candidate_root=candidate)
    _report(runner.store, project)
    with runner.store._transaction() as connection:
        require_unchanged(runner.store, connection, snapshot["manifest"])
    _run(audit)
    with runner.store._transaction() as connection:
        with pytest.raises(ConflictError, match="sources changed"):
            require_unchanged(runner.store, connection, snapshot["manifest"])


def test_human_accepted_report_history_is_exact_cutoff_bound_and_not_ordinary_report_churn(audit):
    runner, plan, candidate = audit
    _run(audit)
    project = _project(runner, plan)
    before = capture(runner.store, project, kind="HISTORY", candidate_root=candidate)
    historical = capture(
        runner.store, project, kind="HISTORY", candidate_root=candidate, as_of=before["as_of"]
    )
    assert before["review_documents"] == []
    accepted_ref = _report(
        runner.store, project, acceptance="ACCEPTED", suffix="accepted", created_at=before["as_of"]
    )
    accepted = runner.store.get(accepted_ref)
    with runner.store._connection() as connection:
        with pytest.raises(ConflictError, match="sources changed"):
            require_unchanged(runner.store, connection, before["manifest"])
        require_unchanged(runner.store, connection, historical["manifest"])
    after = capture(runner.store, project, kind="HISTORY", candidate_root=candidate)
    assert after["review_documents"] == [accepted]
    assert accepted not in after["documents"]
    (review_source,) = after["manifest"]["review_documents"]
    assert review_source["ref"] == accepted_ref.to_json()
    assert review_source["sha256"] == sources._digest(accepted)
    assert set(review_source) == {"ref", "sha256", "publication_sequence", "published_at"}
    assert after["manifest"]["source_watermark"]["review_documents"]["rows"] == 1
    _report(runner.store, project)
    with runner.store._connection() as connection:
        require_unchanged(runner.store, connection, after["manifest"])
    reserved_ref = _report(
        runner.store,
        project,
        acceptance="WITH_RESERVATIONS",
        suffix="reserved",
        created_at=before["as_of"],
    )
    with runner.store._connection() as connection:
        with pytest.raises(ConflictError, match="sources changed"):
            require_unchanged(runner.store, connection, after["manifest"])
    cutoff = capture(
        runner.store,
        project,
        kind="HISTORY",
        candidate_root=candidate,
        as_of=review_source["published_at"],
    )
    assert cutoff["review_documents"] == [accepted]
    assert runner.store.get(reserved_ref) not in cutoff["review_documents"]
    current = capture(runner.store, project, kind="HISTORY", candidate_root=candidate)
    assert current["review_documents"] == [accepted, runner.store.get(reserved_ref)]
    with runner.store._connection() as connection:
        require_unchanged(runner.store, connection, cutoff["manifest"])


def test_candidate_and_evidence_drift_reject_publication_guard(audit):
    runner, plan, candidate = audit
    result = _run(audit)
    snapshot = capture(
        runner.store, _project(runner, plan), kind="PRODUCT", candidate_root=candidate
    )
    target = candidate / "README.md"
    target.write_text("changed", encoding="utf-8")
    with runner.store._transaction() as connection:
        with pytest.raises(ConflictError, match="candidate changed"):
            require_unchanged(runner.store, connection, snapshot["manifest"])
    target.write_text("approved", encoding="utf-8")
    evidence = runner.store.get(result)["payload"]["evidence_refs"][-1]
    (runner.store.database_path.parent / "artifacts" / evidence["path"]).unlink()
    with runner.store._transaction() as connection:
        with pytest.raises(ConflictError, match="evidence changed"):
            require_unchanged(runner.store, connection, snapshot["manifest"])


def test_as_of_excludes_sources_published_after_cutoff_despite_old_document_dates(audit):
    runner, plan, candidate = audit
    first = _run(audit)
    cutoff = next(
        row["occurred_at"]
        for row in runner.store.list_events()
        if row["revision_id"] == first.revision_id
    )
    second = _run(audit)
    snapshot = capture(
        runner.store, _project(runner, plan), kind="PRODUCT", candidate_root=candidate, as_of=cutoff
    )
    assert runner.store.get(second) not in snapshot["documents"]
    assert snapshot["selected_results"] == [runner.store.get(first)]
    earlier = (datetime.fromisoformat(cutoff) - timedelta(days=1)).isoformat()
    with pytest.raises(IntegrityError, match="Project revision"):
        capture(runner.store, _project(runner, plan), kind="PRODUCT", as_of=earlier)
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    with pytest.raises(IntegrityError, match="future"):
        capture(runner.store, _project(runner, plan), kind="PRODUCT", as_of=future)


def test_missing_target_is_an_explicit_gap_and_individual_checkpoints_do_not_form_a_combined_gate(
    audit,
):
    runner, plan, _ = audit
    _run(audit)
    project = _project(runner, plan)
    snapshot = capture(runner.store, project, kind="PRODUCT")
    assert snapshot["artifact_identity"] == {}
    assert all(gate["eligibility"] == "NOT_VERIFIED" for gate in snapshot["gates"])
    assert any("candidate" in gap for gap in snapshot["gaps"])
    combined = capture(
        runner.store, project, kind="CHECKPOINT", checkpoint_ids=("greet", "another")
    )
    assert combined["selected_results"] == []
    assert any("exact requested" in gap for gap in combined["gaps"])


def test_workspace_limits_stop_before_hashing_and_preserve_default_identity(tmp_path, monkeypatch):
    (tmp_path / "first.txt").write_bytes(b"1234")
    (tmp_path / "second.txt").write_bytes(b"5678")
    expected = verification.workspace_snapshot(tmp_path)
    assert verification.workspace_snapshot(tmp_path, max_bytes=8, max_files=2) == expected
    called = []
    digest = verification._digest_file

    def observe(path, **kwargs):
        called.append(path.name)
        return digest(path, **kwargs)

    monkeypatch.setattr(verification, "_digest_file", observe)
    with pytest.raises(IntegrityError, match="inventory"):
        verification.workspace_snapshot(tmp_path, max_files=1)
    assert called == ["first.txt"]
    with pytest.raises(IntegrityError, match="snapshot limit"):
        verification.workspace_snapshot(tmp_path, max_bytes=3)
    monkeypatch.setattr(sources, "_MAX_CANDIDATE_BYTES", 3)
    with pytest.raises(IntegrityError, match="snapshot limit"):
        sources._candidate_snapshot(tmp_path)


def test_execution_completion_is_reconstructed_and_survives_supersession(tmp_path):
    store, workflow = _seed(tmp_path)
    runner = WorkflowRunner(tmp_path, SyntheticAdapter(store, effect=_write_code), reviewer=_accept)
    execution = runner.configure(workflow, [_spec()], actor_id="synthetic-report-owner")
    before = next(
        row
        for row in runner.repository.history(execution["execution_id"])
        if row["kind"] == "EXECUTION_REGISTERED"
    )["occurred_at"]
    attempt = runner.run_next(execution["execution_id"])
    assert attempt["state"] == "COMPLETED"
    project = ContractRef.from_json(store.get(workflow)["payload"]["project_contract_ref"])
    current = capture(store, project, kind="PRODUCT")
    (completed,) = current["executions"]
    assert completed["state"] == "COMPLETED"
    assert completed["completion_recorded"] is True
    assert completed["completed_at"]
    older = capture(store, project, kind="HISTORY", as_of=before)
    assert older["executions"][0]["state"] == "UNKNOWN"
    assert older["executions"][0]["completion_recorded"] is False
    with store._connection() as connection:
        rows = sources._rows(connection, project.project_id)
    now = datetime.now(UTC)
    rows["wf_execution_events"].append(
        {
            "execution_id": execution["execution_id"],
            "checkpoint_id": None,
            "kind": "EXECUTION_SUPERSEDED",
            "occurred_at": now.isoformat(),
            "data": "{}",
        }
    )
    # Explicitly synthetic event input tests projection without altering retained source history.
    historical = sources._executions(
        rows,
        {row["metadata"]["revision_id"]: row for row in current["documents"]},
        now,
        True,
        now.isoformat(),
    )
    assert historical[0]["state"] == "SUPERSEDED"
    assert historical[0]["completion_recorded"] is True
    assert historical[0]["completed_at"] == completed["completed_at"]


def test_corrupt_proof_consumes_the_budget_before_another_file_is_read(audit, monkeypatch):
    runner, plan, _ = audit
    result = _run(audit)
    first, second = runner.store.get(result)["payload"]["evidence_refs"][:2]
    first_path = runner.store.database_path.parent / "artifacts" / first["path"]
    first_path.write_bytes(b"corrupt")
    monkeypatch.setattr(sources, "_MAX_EVIDENCE_BYTES", 7)
    read = sources._read_artifact
    calls = []

    def observe(path, *args):
        calls.append(path)
        return read(path, *args)

    monkeypatch.setattr(sources, "_read_artifact", observe)
    with pytest.raises(IntegrityError, match="total verification budget"):
        sources._proof(runner.store, [{"payload": {"evidence_refs": [first, second]}}])
    assert calls == [first_path]


def test_publication_file_guard_uses_metadata_only_and_rejects_real_input_drift(audit, monkeypatch):
    runner, plan, candidate = audit
    _run(audit)
    snapshot = capture(
        runner.store, _project(runner, plan), kind="PRODUCT", candidate_root=candidate
    )
    with runner.store._connection() as connection:
        guard = require_unchanged(runner.store, connection, snapshot["manifest"])
    monkeypatch.setattr(
        sources,
        "_candidate_snapshot",
        lambda *_: pytest.fail("Writer guard cannot hash a candidate."),
    )
    monkeypatch.setattr(
        fileguard, "_git_paths", lambda *_: pytest.fail("Writer guard cannot invoke Git.")
    )
    monkeypatch.setattr(
        fileguard.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("Writer guard cannot start a process."),
    )
    cache = candidate / ".pytest_cache"
    cache.mkdir()
    (cache / "noise.txt").write_text("Ignored generated cache", encoding="utf-8")
    with runner.store._transaction():
        sources.require_file_guard(guard)
    (candidate / "README.md").write_text("drift", encoding="utf-8")
    with pytest.raises(ConflictError, match="metadata changed"):
        sources.require_file_guard(guard)


def test_empty_git_commit_is_detected_without_rehashing_source_content(audit):
    runner, plan, candidate = audit

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(candidate), *args], stderr=subprocess.DEVNULL
        )

    git("init", "--quiet")
    args = (
        "-c",
        "user.name=Synthetic report test",
        "-c",
        "user.email=tests@example.invalid",
        "commit",
        "--quiet",
        "--allow-empty",
        "-m",
    )
    git(*args, "Synthetic source identity")
    _run(audit)
    snapshot = capture(
        runner.store, _project(runner, plan), kind="PRODUCT", candidate_root=candidate
    )
    with runner.store._connection() as connection:
        guard = require_unchanged(runner.store, connection, snapshot["manifest"])
    sources.require_file_guard(guard)
    git(*args, "Synthetic metadata-only source identity change")
    with pytest.raises(ConflictError, match="metadata changed"):
        sources.require_file_guard(guard)


def test_managed_evidence_content_retains_its_exact_run_and_candidate(audit):
    runner, _, _ = audit
    result = _run(audit)
    reference = runner.store.get(result)["payload"]["evidence_refs"][0]
    assert sources._evidence_state(runner.store, reference)["state"] == "VERIFIED"
    wrong_run = deepcopy(reference)
    wrong_run["execution_context"]["validation_run_id"] = "another-observation-run"
    assert sources._evidence_state(runner.store, wrong_run)["state"] == "CORRUPT"
    wrong_candidate = deepcopy(reference)
    wrong_candidate["artifact_identity"]["snapshot_id"] = "another-candidate"
    assert sources._evidence_state(runner.store, wrong_candidate)["state"] == "CORRUPT"


def test_verified_windows_check_log_summary_preserves_original_artifact_bytes(audit):
    runner, _, _ = audit
    path = runner.store.database_path.parent / "artifacts/runtime/synthetic-log/test.log"
    path.parent.mkdir(parents=True)
    content = b"Ran 20 tests in 0.200s\r\n\r\nOK\r\n"
    path.write_bytes(content)
    reference = {"path": "runtime/synthetic-log/test.log", "sha256": sha256(content).hexdigest()}
    assert sources._log_summary(runner.store, reference) == {
        "framework": "unittest",
        "reported_tests": 20,
        "successful": True,
    }
    assert path.read_bytes() == content
