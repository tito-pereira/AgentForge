# SPDX-License-Identifier: MPL-2.0
"""Observe isolated synthetic delivery files without executing an application."""

import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from corinthos.contracts import ContractRef, IntegrityError
from corinthos.report.delivery import observe_delivery, require_delivery_unchanged
from corinthos.validation.procedures import file_hash
from corinthos.workflow.verification import workspace_snapshot


@pytest.fixture
def delivery(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "README.md").write_text("Synthetic delivered source", encoding="utf-8")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(candidate), *args], text=True).strip()

    git("init", "--quiet")
    git("add", "README.md")
    git(
        "-c",
        "user.name=Synthetic fixture",
        "-c",
        "user.email=tests@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "Synthetic delivery",
    )
    wheel = candidate / "synthetic_tasks-2.3-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            "synthetic_tasks-2.3.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: synthetic-tasks\nVersion: 2.3\n",
        )
    launcher = tmp_path / "launcher.exe"
    launcher.write_bytes(b"Synthetic launcher metadata only")
    project = ContractRef(
        "synthetic-project", "synthetic-project-r1", "PROJECT", "synthetic-project"
    )
    workflow = ContractRef(
        "synthetic-workflow", "synthetic-workflow-r1", "WORKFLOW", "synthetic-project"
    )
    document = {
        "project_ref": project.to_json(),
        "plan_refs": [workflow.to_json()],
        "execution": "synthetic-delivery-execution",
        "state": "COMPLETED",
        "built_package": {
            "wheel": str(wheel),
            "sha256": file_hash(wheel),
            "commit": git("rev-parse", "HEAD"),
        },
        "installed": {"launcher": str(launcher)},
        "human_product_acceptance": "A synthetic statement supplies no acceptance authority.",
    }
    path = tmp_path / "delivery-record.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    executions = [
        {
            "execution_id": document["execution"],
            "workflow_ref": workflow.to_json(),
            "state": "SUPERSEDED",
            "completion_recorded": True,
        }
    ]
    return path, document, project, candidate, executions


def test_observed_delivery_version_and_availability_have_exact_provenance(delivery):
    path, _, project, candidate, executions = delivery
    identity = workspace_snapshot(candidate)["artifact_identity"]
    observed = observe_delivery(
        path, project, identity, candidate_root=candidate, executions=executions
    )
    assert observed["product_version"] == "2.3"
    assert observed["delivery"] == "DELIVERED" and observed["availability"]
    assert observed["provenance"]["artifact_identity"] == identity
    assert "acceptance" not in observed
    require_delivery_unchanged(observed["provenance"])
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(IntegrityError, match="provenance changed"):
        require_delivery_unchanged(observed["provenance"])


def test_unknown_execution_and_missing_inventory_do_not_establish_delivery(delivery):
    path, _, project, candidate, executions = delivery
    identity = workspace_snapshot(candidate)["artifact_identity"]
    missing = observe_delivery(path, project, identity, candidate_root=candidate)
    assert missing["delivery"] == "NOT_DELIVERED" and missing["gaps"]
    no_candidate = observe_delivery(path, project, identity, executions=executions)
    assert no_candidate["delivery"] == "NOT_DELIVERED" and no_candidate["gaps"]


def test_wrong_project_or_changed_package_is_rejected(delivery):
    path, document, project, candidate, executions = delivery
    identity = workspace_snapshot(candidate)["artifact_identity"]
    other = ContractRef("other-project", "other-r1", "PROJECT", "other-project")
    with pytest.raises(IntegrityError, match="another Project"):
        observe_delivery(path, other, identity, candidate_root=candidate, executions=executions)
    Path(document["built_package"]["wheel"]).write_bytes(b"changed")
    with pytest.raises(IntegrityError, match="package digest"):
        observe_delivery(path, project, identity, candidate_root=candidate, executions=executions)


def test_same_commit_and_original_wheel_do_not_deliver_a_dirty_candidate(delivery):
    path, _, project, candidate, executions = delivery
    (candidate / "README.md").write_text(
        "A different candidate at the same commit", encoding="utf-8"
    )
    identity = workspace_snapshot(candidate)["artifact_identity"]
    with pytest.raises(IntegrityError, match="delivered source revision"):
        observe_delivery(path, project, identity, candidate_root=candidate, executions=executions)


def test_normal_relative_delivery_paths_preserve_exact_identity(delivery, monkeypatch):
    path, _, project, candidate, executions = delivery
    identity = workspace_snapshot(candidate)["artifact_identity"]
    monkeypatch.chdir(candidate)
    observed = observe_delivery(
        Path("..") / path.name, project, identity, candidate_root=Path("."), executions=executions
    )
    assert observed["delivery"] == "DELIVERED"
    assert observed["provenance"]["artifact_identity"] == identity
