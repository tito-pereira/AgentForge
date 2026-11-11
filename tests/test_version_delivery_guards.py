# SPDX-License-Identifier: MPL-2.0
"""Delivery race regression checks; all contract/reviewer authority fixtures are synthetic."""

from pathlib import Path

import pytest
from test_version_adoption import existing_delivery as existing_delivery
from test_version_lifecycle import build_fixture as build_fixture
from test_version_lifecycle import delivered as delivered

from corinthos.contracts import ConflictError, IntegrityError


@pytest.mark.parametrize("boundary", ["PRODUCT_GATE", "VERSION_RECORD", "MANIFEST_RECORD"])
def test_delivery_change_during_gate_or_record_creation_rolls_back(
    delivered, monkeypatch, boundary
):
    versions, version, _, build, _, _, _, plan, *_ = delivered
    before = versions.repository.events(version["project_id"])

    def change_candidate():
        target = (
            Path(build["origin"]["manifest_path"])
            if boundary == "MANIFEST_RECORD"
            else Path(build["origin"]["candidate_root"]) / "README.md"
        )
        target.write_bytes(target.read_bytes() + b"Changed during delivery")

    if boundary == "PRODUCT_GATE":
        gate = versions._product_gate

        def change_after_gate(*args, **kwargs):
            result = gate(*args, **kwargs)
            change_candidate()
            return result

        monkeypatch.setattr(versions, "_product_gate", change_after_gate)
    else:
        create = versions.repository.create

        def change_after_record(kind, *args, **kwargs):
            record = create(kind, *args, **kwargs)
            if kind == "VERSION":
                change_candidate()
            return record

        monkeypatch.setattr(versions.repository, "create", change_after_record)
    with pytest.raises(ConflictError, match="metadata changed"):
        versions.deliver(
            build["record_id"], plan, "changed-during-delivery", package_paths=["README.md"]
        )
    assert versions.list(version["project_id"]) == [version]
    assert versions.repository.events(version["project_id"]) == before


def test_adoption_report_manifest_change_during_record_creation_rolls_back(
    existing_delivery, monkeypatch
):
    versions, reports, report, candidate, delivery_record, *_ = existing_delivery
    package = reports.repository.find(report)
    frozen = reports.repository._directory(package["draft_id"]) / "frozen.json"
    before = versions.repository.events(report.project_id)
    create = versions.repository.create

    def change_source_after_record(kind, *args, **kwargs):
        record = create(kind, *args, **kwargs)
        if kind == "VERSION":
            frozen.write_bytes(b"{}")
        return record

    monkeypatch.setattr(versions.repository, "create", change_source_after_record)
    with pytest.raises(ConflictError, match="metadata changed"):
        versions.adopt_delivery(report, candidate, delivery_record)
    assert versions.list(report.project_id) == []
    assert versions.repository.events(report.project_id) == before


@pytest.mark.parametrize("invalid_source", ["PROJECT_REFERENCE", "TRUNCATED_DELIVERY"])
def test_adoption_rejects_wrong_contract_type_and_malformed_delivery_before_mutation(
    existing_delivery, invalid_source
):
    versions, _, report, candidate, delivery_record, _, project = existing_delivery
    if invalid_source == "PROJECT_REFERENCE":
        report = project
    else:
        delivery_record.write_bytes(b'{"built_package":')
    before = versions.repository.events(project.project_id)
    with pytest.raises(IntegrityError):
        versions.adopt_delivery(report, candidate, delivery_record)
    assert versions.list(project.project_id) == []
    assert versions.repository.events(project.project_id) == before
