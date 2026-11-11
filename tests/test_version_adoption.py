# SPDX-License-Identifier: MPL-2.0
"""Actual legacy delivery/report path; contract authority is explicitly synthetic."""

import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest
from test_workflow_runtime import SyntheticAdapter, _accept, _seed, _spec, _write_code

from corinthos.contracts import ContractRef, IntegrityError
from corinthos.lifecycle.versions import VersionService
from corinthos.report import delivery
from corinthos.report.service import ReportService
from corinthos.validation.procedures import file_hash
from corinthos.workflow.runtime import WorkflowRunner
from corinthos.workflow.verification import workspace_snapshot


@pytest.fixture
def existing_delivery(tmp_path):
    root = tmp_path / "retained-baseline"
    root.mkdir()
    store, workflow = _seed(root)
    runner = WorkflowRunner(root, SyntheticAdapter(store, effect=_write_code), reviewer=_accept)
    execution = runner.configure(workflow, [_spec()], actor_id="synthetic-baseline-owner")
    assert runner.run_next(execution["execution_id"])["state"] == "COMPLETED"
    project = ContractRef.from_json(store.get(workflow)["payload"]["project_contract_ref"])

    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

    git("init", "--quiet")
    git("config", "core.autocrlf", "false")
    git("add", "greeting.py")
    git(
        "-c",
        "user.name=Synthetic fixture",
        "-c",
        "user.email=tests@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Synthetic retained baseline",
    )
    wheel = root / "synthetic_tasks-2.3-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.write(root / "greeting.py", "greeting.py")
        archive.writestr(
            "synthetic_tasks-2.3.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: synthetic-tasks\nVersion: 2.3\n",
        )
    launcher = tmp_path / "existing-daily-launcher.exe"
    launcher.write_bytes(b"Synthetic launcher; adoption must not inspect this file")
    record = tmp_path / "existing-delivery.json"
    record.write_text(
        json.dumps(
            {
                "project_ref": project.to_json(),
                "plan_refs": [workflow.to_json()],
                "execution": execution["execution_id"],
                "state": "COMPLETED",
                "built_package": {
                    "wheel": str(wheel),
                    "sha256": file_hash(wheel),
                    "commit": git("rev-parse", "HEAD"),
                },
                "installed": {"launcher": str(launcher)},
            }
        ),
        encoding="utf-8",
    )
    reports = ReportService(store)
    draft = reports.generate(project, candidate=root, delivery_record=record)
    report = reports.publish(draft["draft_id"])
    assert reports.get(report)["payload"]["version_and_delivery_lineage"]["delivery"] == "DELIVERED"
    return VersionService(store), reports, report, root, record, launcher, project


def test_existing_delivery_enters_real_version_evolution_without_relabelling(
    existing_delivery, monkeypatch
):
    versions, reports, report, candidate, record, launcher, project = existing_delivery
    old_document, old_manifest = reports.get(report), reports.manifest(report)
    original = delivery._observe_file

    def guard(path, limit):
        assert Path(path) != launcher, "Baseline adoption must not inspect the daily launcher"
        return original(path, limit)

    monkeypatch.setattr(delivery, "_observe_file", guard)
    version = versions.adopt_delivery(report, candidate, record)
    assert versions.adopt_delivery(report, candidate, record) == version
    assert versions.require_delivered(version["record_id"]) == version
    assert (
        version["origin"]["artifact_identity"] == workspace_snapshot(candidate)["artifact_identity"]
    )
    assert "build_id" not in version["origin"]["artifact_identity"]
    assert version["origin"]["source_kind"] == "EXISTING_DELIVERY"
    assert version["snapshot"]["acceptance"] == "NOT_REVIEWED"
    assert (
        version["origin"]["validation_result_refs"]
        == old_document["payload"]["execution_and_validation_digest"]["validation_result_refs"]
    )
    evolution = versions.evolve(
        version["record_id"], "OPERATIONAL", "Repair an existing obligation"
    )
    assert evolution["project_id"] == project.project_id
    assert reports.get(report) == old_document
    assert reports.manifest(report) == old_manifest


def test_changed_baseline_cannot_be_adopted_or_used_as_evolution_base(existing_delivery):
    versions, _, report, candidate, record, *_ = existing_delivery
    version = versions.adopt_delivery(report, candidate, record)
    (candidate / "greeting.py").write_text("changed source", encoding="utf-8")
    with pytest.raises(IntegrityError, match="whole-candidate"):
        versions.adopt_delivery(report, candidate, record)
    with pytest.raises(IntegrityError, match="whole-candidate"):
        versions.evolve(version["record_id"], "OPERATIONAL", "Repair under the old obligations")
