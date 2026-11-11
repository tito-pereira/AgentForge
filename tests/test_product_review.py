# SPDX-License-Identifier: MPL-2.0
"""Synthetic terminal consent tests real delivered bytes, reports and Kernel checks."""

import io
from contextlib import contextmanager
from copy import deepcopy

import pytest
from test_build_lifecycle import built as build_fixture  # noqa: F401
from test_version_lifecycle import delivered as delivered_fixture  # noqa: F401

from corinthos.contracts import AuthorityError, ConflictError, ContractRef
from corinthos.lifecycle.repository import digest
from corinthos.project_manager import product_review
from corinthos.project_manager.product_review import ProductReviewService


@pytest.fixture
def delivered(request):
    return request.getfixturevalue("delivered_fixture")


def _synthetic_terminal(monkeypatch, *, approve=True, after_display=None):
    output = io.StringIO()

    class Reader:
        def readline(self, limit):
            if after_display:
                after_display()
            if not approve:
                return "DEFER\n"
            challenge = (
                output.getvalue().split("To publish this exact review, type ")[-1].splitlines()[0]
            )
            return challenge + "\n"

    @contextmanager
    def terminal():
        yield Reader(), output

    monkeypatch.setattr(product_review, "_terminal", terminal)
    return output


def _start(delivered, *, decision="ACCEPTED"):
    versions, version, *_ = delivered
    service = ProductReviewService(versions.store)
    record = service.start(
        version["record_id"],
        decision=decision,
        observations=["Synthetic fixture observation, not owner acceptance."],
    )
    return service, record


@pytest.mark.parametrize("decision", ["ACCEPTED", "WITH_RESERVATIONS"])
def test_exact_synthetic_foreground_receipt_and_kernel_publication_are_atomic(
    delivered, monkeypatch, decision
):
    service, record = _start(delivered, decision=decision)
    source_id = record["origin"]["source_draft_id"]
    original = deepcopy(service.reports.repository.get(source_id))
    output = _synthetic_terminal(monkeypatch)
    published = service.approve_interactively(record["record_id"], record["version"])
    assert published["state"] == "PUBLISHED"
    reference = ContractRef.from_json(published["snapshot"]["published_ref"])
    document = service.store.get(reference)
    assert document["payload"]["version_and_delivery_lineage"]["acceptance"] == decision
    assert document["metadata"]["approval"]["kind"] == "HUMAN"
    assert document["metadata"]["provenance"]["engine"] == "REPORT"
    assert document["metadata"]["provenance"]["source"].startswith("pm-product-review-sha256:")
    receipt = service.repository.get("OPERATION", published["snapshot"]["review"]["receipt_id"])
    assert receipt["state"] == "CONSUMED"
    assert receipt["origin"]["content_sha256"] == digest(document)
    assert "Complete candidate" in output.getvalue()
    assert "Implementation and validation follow later" not in output.getvalue()
    assert service.reports.repository.get(source_id) == original
    assert original["document"]["metadata"]["approval"] is None
    assert (
        original["document"]["payload"]["version_and_delivery_lineage"]["acceptance"]
        == "NOT_REVIEWED"
    )
    assert ProductReviewService(service.store).get(record["record_id"]) == published
    with pytest.raises(ConflictError, match="already"):
        service.freeze(record["record_id"], published["version"], actor_id="synthetic-owner")


def test_freeze_and_defer_create_no_consent_receipt(delivered, monkeypatch):
    service, record = _start(delivered)
    frozen = service.freeze(record["record_id"], record["version"], actor_id="synthetic-owner")
    assert frozen["snapshot"]["review"]["receipt_id"] is None
    assert _receipts(service, record) == []
    _synthetic_terminal(monkeypatch, approve=False)
    deferred = service.approve_interactively(record["record_id"], frozen["version"])
    assert deferred["state"] == "DEFERRED" and deferred["snapshot"]["review"] is None
    assert _receipts(service, record) == []
    assert (
        service.reports.history(
            "product-review-" + digest({"version_id": record["origin"]["version_id"]})[:32]
        )
        == []
    )


def test_actual_noninteractive_approval_fails_before_freezing(delivered, monkeypatch):
    service, record = _start(delivered)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(AuthorityError, match="foreground"):
        service.approve_interactively(record["record_id"], record["version"])
    assert service.get(record["record_id"]) == record
    assert _receipts(service, record) == []


def test_changed_review_cannot_consume_displayed_consent(delivered, monkeypatch):
    service, record = _start(delivered)

    def concurrent_change():
        current = service.get(record["record_id"])
        service.defer(current["record_id"], current["version"], actor_id="synthetic-other-owner")

    _synthetic_terminal(monkeypatch, after_display=concurrent_change)
    with pytest.raises(ConflictError, match="changed"):
        service.approve_interactively(record["record_id"], record["version"])
    assert _receipts(service, record) == []
    assert service.get(record["record_id"])["state"] == "DEFERRED"


def test_kernel_failure_rolls_back_receipt_and_requires_fresh_terminal_action(
    delivered, monkeypatch
):
    service, record = _start(delivered)
    _synthetic_terminal(monkeypatch)
    original = service.store._publish

    def interrupted(*args, **kwargs):
        raise RuntimeError("Synthetic interruption inside the writer")

    with monkeypatch.context() as patch:
        patch.setattr(service.store, "_publish", interrupted)
        with pytest.raises(RuntimeError, match="inside the writer"):
            service.approve_interactively(record["record_id"], record["version"])
    pending = service.get(record["record_id"])
    assert pending["state"] == "AWAITING_EXPLICIT_APPROVAL"
    assert _receipts(service, record) == []
    assert service.store._publish == original
    _synthetic_terminal(monkeypatch)
    assert (
        service.approve_interactively(record["record_id"], pending["version"])["state"]
        == "PUBLISHED"
    )


def _receipts(service, record):
    return [
        item
        for item in service.repository.list("OPERATION", record["project_id"])
        if item["origin"].get("operation") == "HUMAN_PRODUCT_CONSENT"
    ]


def test_expired_foreground_review_cannot_create_a_receipt(delivered, monkeypatch):
    service, record = _start(delivered)
    clock = product_review.time.time

    def expire():
        monkeypatch.setattr(product_review.time, "time", lambda: clock() + 1000)

    _synthetic_terminal(monkeypatch, after_display=expire)
    with pytest.raises(AuthorityError, match="expired"):
        service.approve_interactively(record["record_id"], record["version"])
    assert _receipts(service, record) == []


def test_unrelated_lifecycle_source_change_invalidates_displayed_review(delivered, monkeypatch):
    service, record = _start(delivered)

    def change_source():
        service.repository.create(
            "OPERATION",
            record["project_id"],
            {"operation": "SYNTHETIC_UNRELATED_CHANGE"},
            state="COMPLETED",
        )

    _synthetic_terminal(monkeypatch, after_display=change_source)
    with pytest.raises(ConflictError, match="sources changed"):
        service.approve_interactively(record["record_id"], record["version"])
    assert _receipts(service, record) == []
