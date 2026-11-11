# SPDX-License-Identifier: MPL-2.0
"""Synthetic frozen reports exercise actual presentation and export boundaries."""

import json
import os
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from corinthos.contracts import IntegrityError
from corinthos.contracts.model import canonical_json
from corinthos.report import rendering
from corinthos.report.rendering import (
    export_report,
    render_json,
    render_markdown,
    safe_prose,
    verify_export,
)

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def document():
    return json.loads((_ROOT / "examples/contracts/evidence-report.json").read_text("utf-8"))


@pytest.mark.parametrize("kind", ["CHECKPOINT", "MILESTONE", "PRODUCT", "HISTORY", "EVOLUTION"])
def test_frozen_markdown_keeps_all_sections_states_and_source_identities(document, kind):
    document["payload"]["report_scope"]["kind"] = kind
    before = deepcopy(document)
    private_path = "/" + "/".join(("home", "synthetic", "private-record"))
    text = render_markdown(document, {"private_path": private_path})
    assert text.startswith("# " + kind.title() + " report")
    assert text.count("\n## ") == 9
    assert "**Availability** false" in text
    assert "BLOCKED" in text and "NOT\\_DELIVERED" in text and "NOT\\_REVIEWED" in text
    assert "demo\\-snapshot" in text and "demo\\-result\\-r1" in text
    assert private_path not in text
    assert document == before
    assert json.loads(render_json(document)) == document


def test_prose_and_markdown_make_injection_and_sensitive_values_inert(document):
    credential = "sk-" + "synthetic-secret-value-0123456789"
    private_path = "C:" + "\\" + "\\".join(("Users", "Synthetic", "private.txt"))
    hostile = (
        "[run](javascript:alert(1)) <script>bad()</script>\x1b[31m\u202e "
        + credential
        + " password='do not retain this' "
        + private_path
    )
    document["payload"]["report_scope"]["objective"] = hostile
    before = deepcopy(document)
    text = render_markdown(document)
    assert "[run](" not in text and "<script>" not in text
    assert "\x1b" not in text and "\u202e" not in text
    assert "u001b" in text and "u202e" in text
    assert credential not in text and "do not retain this" not in text
    assert private_path not in text
    assert document == before
    with pytest.raises(IntegrityError, match="sensitive"):
        render_json(document)
    bounded = safe_prose("a" * 5000)
    assert len(bounded) < 4200 and bounded.endswith("[source prose truncated]")


def test_json_limit_includes_its_output_newline(document, monkeypatch):
    monkeypatch.setattr(rendering, "_LIMIT", len(canonical_json(document).encode("utf-8")))
    with pytest.raises(IntegrityError, match="presentation limit"):
        render_json(document)


def test_export_is_exact_bounded_and_verified_against_its_frozen_source(document, tmp_path):
    private_path = "/" + "/".join(("home", "synthetic", "source"))
    manifest = {"source_identity": "frozen", "private_path": private_path}
    destination = tmp_path / "report"
    outcome = export_report(document, destination, manifest=manifest)
    assert outcome["state"] == "COMPLETE" and outcome["source_verified"]
    assert (destination / "report.json").read_bytes() == (canonical_json(document) + "\n").encode(
        "utf-8"
    )
    assert (destination / "report.md").read_text("utf-8") == render_markdown(document, manifest)
    assert private_path not in (destination / "report.md").read_text("utf-8")
    prior = {path.name: path.read_bytes() for path in destination.iterdir()}
    assert export_report(document, destination, manifest=manifest) == outcome
    assert prior == {path.name: path.read_bytes() for path in destination.iterdir()}
    assert verify_export(destination)["state"] == "COMPLETE"
    changed = deepcopy(document)
    changed["payload"]["report_scope"]["objective"] = "A different frozen observation."
    with pytest.raises(IntegrityError, match="different frozen"):
        export_report(changed, destination, manifest=manifest)
    assert prior == {path.name: path.read_bytes() for path in destination.iterdir()}


def test_output_and_manifest_tampering_cannot_authenticate_a_changed_human_view(document, tmp_path):
    destination = tmp_path / "report"
    export_report(document, destination)
    changed = b"An invented successful result."
    (destination / "report.md").write_bytes(changed)
    observed = verify_export(destination, document=document)
    assert observed["state"] == "INCOMPLETE"
    manifest_path = destination / "export-manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    entry = next(item for item in manifest["outputs"] if item["path"] == "report.md")
    entry.update(sha256=sha256(changed).hexdigest(), size=len(changed))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_export(destination)["state"] == "COMPLETE"
    with pytest.raises(IntegrityError, match="frozen source"):
        verify_export(destination, document=document)
    entry["path"] = "../outside"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(IntegrityError, match="invalid output"):
        verify_export(destination)


def test_failed_export_preserves_completed_files_and_recovers_exact_missing_output(
    document, tmp_path, monkeypatch
):
    destination = tmp_path / "report"
    real_write = rendering._write_new

    def fail_markdown(path, data):
        if path.name == "report.md":
            raise OSError("Synthetic export failure before the human output.")
        return real_write(path, data)

    monkeypatch.setattr(rendering, "_write_new", fail_markdown)
    with pytest.raises(OSError, match="Synthetic"):
        export_report(document, destination)
    assert not (destination / "export-manifest.json").exists()
    canonical_bytes = (destination / "report.json").read_bytes()
    assert verify_export(destination)["state"] == "INCOMPLETE"
    monkeypatch.setattr(rendering, "_write_new", real_write)
    assert export_report(document, destination)["state"] == "COMPLETE"
    assert (destination / "report.json").read_bytes() == canonical_bytes


def test_export_preserves_unowned_existing_paths_and_rejects_traversal(document, tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.txt").write_bytes(b"Existing user output")
    with pytest.raises(IntegrityError, match="manifest"):
        export_report(document, destination)
    assert (destination / "keep.txt").read_bytes() == b"Existing user output"
    with pytest.raises(IntegrityError, match="traversal"):
        export_report(document, tmp_path / "existing" / ".." / "outside")
    assert not (tmp_path / "outside").exists()


def test_export_rejects_linked_parent(document, tmp_path):
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    redirect = tmp_path / "redirect"
    try:
        redirect.symlink_to(ordinary, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks requires unavailable local privileges.")
    with pytest.raises(IntegrityError, match="links"):
        export_report(document, redirect / "report")


def test_export_rejects_hardlinked_output(document, tmp_path):
    destination = tmp_path / "report"
    export_report(document, destination)
    original = (destination / "report.md").read_bytes()
    (destination / "report.md").unlink()
    preserved = tmp_path / "preserved.md"
    preserved.write_bytes(original)
    os.link(preserved, destination / "report.md")
    with pytest.raises(IntegrityError, match="unlinked"):
        verify_export(destination)
    assert preserved.read_bytes() == original


def test_partial_owned_write_is_removed_before_exact_export_recovery(
    document, tmp_path, monkeypatch
):
    destination = tmp_path / "report"
    real_fsync = rendering.os.fsync
    calls = 0

    def fail_second_fsync(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Synthetic durability failure in the newly created JSON output.")
        return real_fsync(descriptor)

    monkeypatch.setattr(rendering.os, "fsync", fail_second_fsync)
    with pytest.raises(OSError, match="Synthetic"):
        export_report(document, destination)
    assert (destination / ".export-pending.json").is_file()
    assert not (destination / "report.json").exists()
    assert not (destination / "export-manifest.json").exists()
    monkeypatch.setattr(rendering.os, "fsync", real_fsync)
    assert export_report(document, destination)["state"] == "COMPLETE"


def test_first_pending_fsync_failure_releases_only_its_empty_reservation(
    document, tmp_path, monkeypatch
):
    destination = tmp_path / "report"
    real_fsync = rendering.os.fsync

    def fail_first_fsync(descriptor):
        raise OSError("Synthetic durability failure in the initial export descriptor.")

    monkeypatch.setattr(rendering.os, "fsync", fail_first_fsync)
    with pytest.raises(OSError, match="initial export descriptor"):
        export_report(document, destination)
    assert not destination.exists()
    monkeypatch.setattr(rendering.os, "fsync", real_fsync)
    assert export_report(document, destination)["state"] == "COMPLETE"


def test_failed_first_pending_write_preserves_unexpected_directory_contents(
    document, tmp_path, monkeypatch
):
    destination = tmp_path / "report"

    def fail_with_concurrent_file(descriptor):
        (destination / "keep.txt").write_bytes(b"Unrelated concurrent output")
        raise OSError("Synthetic failure after another file appeared.")

    monkeypatch.setattr(rendering.os, "fsync", fail_with_concurrent_file)
    with pytest.raises(OSError, match="another file appeared"):
        export_report(document, destination)
    assert (destination / "keep.txt").read_bytes() == b"Unrelated concurrent output"
    assert not (destination / ".export-pending.json").exists()


def test_failed_first_pending_write_preserves_a_replaced_directory(document, tmp_path, monkeypatch):
    destination = tmp_path / "report"
    moved = tmp_path / "moved-reservation"

    def replace_before_pending_write(path, data):
        destination.rename(moved)
        destination.mkdir()
        raise OSError("Synthetic failure after the directory was replaced.")

    monkeypatch.setattr(rendering, "_write_new", replace_before_pending_write)
    with pytest.raises(OSError, match="directory was replaced"):
        export_report(document, destination)
    assert destination.is_dir() and moved.is_dir()
