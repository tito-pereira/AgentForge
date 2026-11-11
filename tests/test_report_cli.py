# SPDX-License-Identifier: MPL-2.0
"""The actual Report CLI uses synthetic approved Project and source fixtures."""

import json
import subprocess
import sys
from pathlib import Path

from test_contract_store import _context

from corinthos.cli import main
from corinthos.contracts import ContractRef, ContractStore
from corinthos.report.service import ReportService

_ROOT = Path(__file__).resolve().parents[1]


def _seed(root):
    store = ContractStore(root)
    project = json.loads((_ROOT / "examples/contracts/project.json").read_text("utf-8"))
    reference = store.publish(project, context=_context(project))
    return store, reference


def test_owner_can_generate_publish_reopen_export_and_verify_without_contract_json(
    tmp_path, capsys
):
    store, project = _seed(tmp_path)
    prefix = ["report", "--root", str(tmp_path)]
    assert (
        main(
            [
                *prefix,
                "generate",
                project.contract_id,
                "--snapshot-id",
                "synthetic-cli-candidate",
                "--report-id",
                "synthetic-cli-report",
            ]
        )
        == 0
    )
    generated = json.loads(capsys.readouterr().out)
    draft = generated["draft_id"]
    assert generated["states"]["technical_validation"] == "NOT_VERIFIED"
    assert generated["states"]["acceptance"] == "NOT_REVIEWED"
    assert "manifest" not in generated
    assert main([*prefix, "show-draft", draft]) == 0
    assert "Product report" in capsys.readouterr().out
    assert main([*prefix, "drafts"]) == 0
    assert draft in capsys.readouterr().out
    assert main([*prefix, "publish", draft]) == 0
    report = ContractRef.from_json(json.loads(capsys.readouterr().out))
    assert store.resolve_active(report.contract_id) is None
    published_events = store.list_events()
    assert main([*prefix, "recover", draft]) == 0
    assert ContractRef.from_json(json.loads(capsys.readouterr().out)) == report
    assert store.list_events() == published_events
    assert main([*prefix, "list", project.project_id]) == 0
    assert report.revision_id in capsys.readouterr().out
    assert main([*prefix, "history", report.contract_id]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert main([*prefix, "show", report.contract_id, "--revision", report.revision_id]) == 0
    assert "Execution and Validation" in capsys.readouterr().out
    assert main([*prefix, "show", report.contract_id, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == ReportService(store).get(report)
    destination = tmp_path / "exported-report"
    assert main([*prefix, "export", report.contract_id, "--destination", str(destination)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["state"] == "COMPLETE" and exported["source_verified"]
    assert main([*prefix, "verify-export", str(destination)]) == 0
    assert json.loads(capsys.readouterr().out)["source_verified"]
    assert main([*prefix, "verify", report.contract_id]) == 0
    assert json.loads(capsys.readouterr().out)["complete"]
    assert main([*prefix, "compare", report.contract_id, report.contract_id]) == 0
    assert json.loads(capsys.readouterr().out)["changes"] == []
    assert store.list_events() == published_events


def test_cli_rejects_mixed_candidate_inputs_and_preserves_frozen_actor(tmp_path, capsys):
    store, project = _seed(tmp_path)
    prefix = ["report", "--root", str(tmp_path)]
    events = store.list_events()
    assert (
        main(
            [
                *prefix,
                "generate",
                project.contract_id,
                "--candidate",
                str(tmp_path),
                "--snapshot-id",
                "synthetic-conflicting-id",
            ]
        )
        == 1
    )
    assert "candidate directory or explicit artifact identity" in capsys.readouterr().err
    assert store.list_events() == events
    draft = ReportService(store).generate(
        project, artifact_identity={"snapshot_id": "synthetic-cli-candidate"}
    )
    assert (
        main([*prefix, "publish", draft["draft_id"], "--actor", "different-synthetic-actor"]) == 1
    )
    assert "frozen report actor" in capsys.readouterr().err
    assert store.list_events() == events


def test_report_help_runs_from_an_unrelated_directory_without_creating_state(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "corinthos", "report", "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "generate" in result.stdout and "verify-export" in result.stdout
    assert not (tmp_path / ".corinthos").exists()
