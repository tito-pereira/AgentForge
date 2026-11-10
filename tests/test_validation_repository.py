# SPDX-License-Identifier: MPL-2.0
"""Exercise durable Validation state with explicitly synthetic Kernel fixtures."""

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Barrier

import pytest

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    ContractStore,
    IntegrityError,
    PublishContext,
    approval_request,
)
from corinthos.contracts.model import canonical_json
from corinthos.validation.repository import ValidationRepository

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/contracts"


def _load(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def _digest(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@pytest.fixture
def setup(tmp_path):
    store = ContractStore(tmp_path)
    for name in ("project", "technology-decision", "module", "workflow"):
        document = _load(name)
        metadata = document["metadata"]
        provenance = metadata["provenance"]
        proof = approval_request(document) if metadata["approval"] else None
        # Synthetic trusted fixture authority, never production consent.
        store.publish(
            document,
            context=PublishContext(
                provenance["engine"], provenance["actor_id"], lambda request: request == proof
            ),
        )
    clock = [1_770_000_000.0]
    repository = ValidationRepository(store, clock=lambda: clock[0])
    document = _load("validation")
    payload = document["payload"]
    bindings = {
        check["check_id"]: {"description": "Synthetic repository fixture"}
        for check in payload["verification_matrix"]
    }
    reviews = {key: {"reason": "Synthetic repository fixture"} for key in bindings}
    payload["execution_plan"]["procedures"].append(f"bindings-sha256:{_digest(bindings)}")
    payload["execution_plan"]["conditions"].append(f"method-reviews-sha256:{_digest(reviews)}")
    return repository, document, bindings, reviews, clock


def _publish(setup):
    repo, document, bindings, reviews, _ = setup
    return repo.publish_plan(
        document, bindings, reviews=reviews, context=PublishContext("VALIDATION", "demo-validation")
    )


def _result(run, events):
    """Freeze a fixture's interrupted result without claiming any conformity."""
    document = _load("validation-result")
    document["metadata"].update(
        contract_id=f"result-{run['run_id']}",
        revision_id=f"result-{run['run_id']}-r1",
        created_at=run["finished_at"],
    )
    document["payload"].update(validation_plan_ref=run["plan_ref"])
    document["payload"]["target_and_execution"].update(
        validation_run_id=run["run_id"],
        evaluator_ref=run["evaluator"],
        started_at=run["started_at"],
        finished_at=run["finished_at"],
        artifact_identity=run["context"]["artifact_identity"],
    )
    return document


def _start(repo, ref, **kwargs):
    return repo.start(
        ref,
        {"artifact_identity": {"snapshot_id": "fixture-snapshot"}},
        evaluator="demo-validation",
        **kwargs,
    )


def test_drafts_are_detached_and_version_checked(setup):
    repo, *_ = setup
    draft = repo.save_draft("draft-one", {"notes": ["first"]})
    draft["draft"]["notes"].append("not committed")
    assert repo.get_draft("draft-one")["draft"] == {"notes": ["first"]}
    updated = repo.save_draft("draft-one", {"notes": ["second"]}, expected_version=1)
    assert updated["version"] == 2 and repo.list_drafts() == [updated]
    with pytest.raises(ConflictError, match="Reload"):
        repo.save_draft("draft-one", {"notes": []}, expected_version=1)


def test_plan_seals_methods_and_atomic_publication(setup, monkeypatch):
    repo, document, bindings, reviews, _ = setup
    ref = ContractRef.from_document(document)
    forged = {**bindings, next(iter(bindings)): {"description": "Changed procedure"}}
    with pytest.raises(IntegrityError, match="seal"):
        repo.publish_plan(
            document,
            forged,
            reviews=reviews,
            context=PublishContext("VALIDATION", "demo-validation"),
        )
    original = repo.store._publish

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic crash inside VC publication")

    with monkeypatch.context() as patch:
        patch.setattr(repo.store, "_publish", crash)
        with pytest.raises(RuntimeError, match="Synthetic crash"):
            _publish(setup)
    assert repo.store.get(ref) is None
    assert _publish(setup) == _publish(setup) == ref
    assert repo.bindings(ref) == bindings and repo.reviews(ref) == reviews
    assert len(repo.store.list_revisions(ref.contract_id)) == 1


def test_expired_claim_needs_inspection_and_retries_use_fresh_identity(setup):
    repo, document, _, _, clock = setup
    ref = _publish(setup)
    barrier = Barrier(2, timeout=10)

    def claim(_):
        barrier.wait()
        try:
            return _start(repo, ref, ttl=10)
        except ConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        (run,) = [item for item in pool.map(claim, range(2)) if item is not None]
    run_id = run["run_id"]
    repo.observe(run_id, run["owner"], "CHECK_STARTED", {"check_id": "verify-R1"})
    repo.observe(run_id, run["owner"], "CHECK_OBSERVED", {"check_id": "verify-R1"})
    with pytest.raises(ConflictError, match="one start and one observation"):
        repo.observe(run_id, run["owner"], "CHECK_OBSERVED", {"check_id": "verify-R1"})
    clock[0] += 11
    reopened = ValidationRepository(repo.store, clock=lambda: clock[0])
    with pytest.raises(ConflictError, match="expired"):
        reopened.renew(run_id, run["owner"])
    with pytest.raises(ConflictError, match="unfinished run"):
        _start(reopened, ref)
    with pytest.raises(ConflictError, match="inspected"):
        reopened.recover(run_id, {"process_stopped": True}, _result)

    inspection = {
        "process_stopped": True,
        "effects_inspected": True,
        "reason": "Synthetic inspection.",
    }
    result = reopened.recover(run_id, inspection, _result)
    assert result["state"] == "FROZEN"
    assert [item["kind"] for item in reopened.history(run_id)] == [
        "RUN_CLAIMED",
        "CHECK_STARTED",
        "CHECK_OBSERVED",
        "RUN_RECOVERED",
        "RESULT_FROZEN",
    ]
    published = reopened.publish(run_id)
    assert reopened.publish(run_id) == published
    assert reopened.is_published_run(ref, published, run_id)
    assert not reopened.is_published_run(ref, published, "nonexistent")
    assert reopened.store.get(published)["payload"]["gate_assessment"]["state"] == "BLOCKED"
    next_run = _start(reopened, ref, previous_run_id=run_id)
    assert next_run["run_id"] != run_id and next_run["previous_run_id"] == run_id
    with pytest.raises(ConflictError, match="no longer owns"):
        repo.observe(run_id, run["owner"], "CHECK_OBSERVED", {"late": True})
    assert document["metadata"]["contract_id"] == next_run["plan_ref"]["contract_id"]


def test_freeze_and_publication_preserve_exact_binding_on_failure(setup, monkeypatch):
    repo, *_ = setup
    ref = _publish(setup)
    run = _start(repo, ref)
    run_id = run["run_id"]

    def forge(record, events):
        record["context"]["artifact_identity"] = {"snapshot_id": "forged"}
        return _result(record, events)

    with pytest.raises(IntegrityError, match="exact observed run"):
        repo.freeze(run_id, run["owner"], forge)
    assert repo.get(run_id)["state"] == "RUNNING"
    frozen = repo.freeze(run_id, run["owner"], _result)
    expected = ContractRef.from_document(frozen["frozen_result"])
    original = repo._event

    def crash(connection, identity, kind, data):
        if kind == "RESULT_PUBLISHED":
            raise RuntimeError("Synthetic crash during VRC publication")
        original(connection, identity, kind, data)

    with monkeypatch.context() as patch:
        patch.setattr(repo, "_event", crash)
        with pytest.raises(RuntimeError, match="Synthetic crash"):
            repo.publish(run_id)
    assert repo.store.get(expected) is None and repo.get(run_id)["state"] == "FROZEN"
    assert repo.publish(run_id) == repo.publish(run_id) == expected
    assert repo.store.get(expected) == frozen["frozen_result"]
    assert len(repo.store.list_revisions(expected.contract_id)) == 1


def test_claim_rejects_commit_only_and_changed_methods(setup):
    repo, *_ = setup
    ref = _publish(setup)
    with pytest.raises(IntegrityError, match="observed artifact"):
        repo.start(ref, {"artifact_identity": {"commit": "a" * 40}}, evaluator="demo-validation")
    with pytest.raises(IntegrityError, match="sealed methods"):
        repo.start(
            ref,
            {"artifact_identity": {"snapshot_id": "fixture"}, "bindings": {}},
            evaluator="demo-validation",
        )
    assert not repo.list()
