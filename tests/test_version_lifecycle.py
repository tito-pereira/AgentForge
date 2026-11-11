# SPDX-License-Identifier: MPL-2.0
"""Real retained bytes and scoped audits; authority/reviewer fixtures are synthetic."""

from pathlib import Path

import pytest
from test_build_lifecycle import _plan, _ready, _review
from test_build_lifecycle import built as build_fixture  # noqa: F401
from test_validation_planning import _assess, _bindings

from corinthos.contracts import ConflictError, IntegrityError
from corinthos.lifecycle.playtest import PlaytestService
from corinthos.lifecycle.versions import VersionService
from corinthos.project_manager.service import ProjectManager
from corinthos.validation.runtime import ValidationRunner


@pytest.fixture
def delivered(request):
    built = request.getfixturevalue("build_fixture")
    builds, build, planner, refs, *_ = built
    draft = planner.derive(
        refs["project"],
        "PRODUCT",
        target_ref=refs["project"],
        target_ids=[refs["project"].project_id],
    )
    bindings = _bindings(draft)
    plan = planner.publish(
        draft, bindings, _assess(draft, bindings), actor_id="synthetic-product-planner"
    )
    runner = ValidationRunner(builds.store)
    result = runner.run(
        plan,
        Path(build["origin"]["candidate_root"]),
        build_id=build["record_id"],
        evaluator="synthetic-product-evaluator",
        reviewer=_review,
    )
    versions = VersionService(builds.store)
    version = versions.deliver(
        build["record_id"],
        plan,
        "fixture-1",
        package_paths=["README.md"],
        documentation_paths=["README.md"],
    )
    return versions, version, builds, build, planner, refs, runner, plan, result


def test_delivery_is_exact_idempotent_and_preserves_version_lineage(delivered):
    versions, first, _, build, _, refs, _, plan, *_ = delivered
    assert versions.require_delivered(first["record_id"]) == first
    assert (
        versions.deliver(
            build["record_id"],
            plan,
            "fixture-1",
            package_paths=["README.md"],
            documentation_paths=["README.md"],
        )
        == first
    )
    second = versions.deliver(
        build["record_id"],
        plan,
        "fixture-2",
        package_paths=["README.md"],
        previous_version_id=first["record_id"],
    )
    assert second["origin"]["previous_version_id"] == first["record_id"]
    assert second["project_id"] == first["project_id"] == refs["project"].project_id
    assert versions.get(first["record_id"]) == first
    assert versions.list(first["project_id"]) == [first, second]
    assert first["snapshot"]["acceptance"] == "NOT_REVIEWED"
    with pytest.raises(ConflictError, match="already denotes"):
        versions.deliver(build["record_id"], plan, "fixture-1", package_paths=["README.md"])


def test_operational_evolution_preserves_project_revision_and_exact_delivered_base(delivered):
    versions, version, _, _, _, refs, *_ = delivered
    before = versions.store.list_revisions(refs["project"].contract_id)
    request = versions.evolve(
        version["record_id"],
        "OPERATIONAL",
        "Repair within unchanged obligations.",
        request_id="synthetic-operational-evolution",
    )
    assert request["project_id"] == version["project_id"]
    assert request["origin"]["project_ref"] == refs["project"].to_json()
    assert request["origin"]["artifact_identity"] == version["origin"]["artifact_identity"]
    assert versions.store.list_revisions(refs["project"].contract_id) == before
    assert (
        versions.evolve(
            version["record_id"],
            "OPERATIONAL",
            "Repair within unchanged obligations.",
            request_id="synthetic-operational-evolution",
        )
        == request
    )
    with pytest.raises(ConflictError, match="different origin"):
        versions.evolve(
            version["record_id"],
            "PROJECT_CHANGE",
            "A different requirement.",
            request_id="synthetic-operational-evolution",
        )


def test_evolution_pins_actual_observation_context_without_promoting_it_to_authority(delivered):
    versions, version, builds, build, planner, refs, *_ = delivered
    _ready(builds, build)
    plan = _plan(planner, refs)
    builds.validate(
        build["record_id"], plan, evaluator="synthetic-evolution-validator", reviewer=_review
    )
    playtests = PlaytestService(builds.store)
    playtests.configure(version["project_id"], enabled=True)
    playtests.promote(version["project_id"], build["record_id"])
    feedback = playtests.feedback(
        version["project_id"], build["record_id"], "Observed behavior; untrusted source text"
    )
    evolution = versions.evolve(
        version["record_id"], "OPERATIONAL", "Inspect the actual observed behavior"
    )
    context = evolution["origin"]["context_refs"]["feedback"]
    assert len(context) == 1
    assert context[0]["record_id"] == feedback["record_id"]
    assert context[0]["snapshot_sha256"] == feedback["snapshot_sha256"]
    playtests.triage(feedback["record_id"], category="BUG", reason="Relevant Workflow follow-up")
    assert (
        versions.repository.get("EVOLUTION", evolution["record_id"])["origin"]["context_refs"][
            "feedback"
        ]
        == context
    )
    assert (
        versions.store.resolve_active(refs["project"].contract_id)["metadata"]["revision_id"]
        == refs["project"].revision_id
    )


def test_delivery_rejects_missing_or_newest_unfinished_product_proof(delivered):
    versions, version, _, build, _, _, runner, plan, *_ = delivered
    last = runner.repository.list()[-1]
    runner.repository.start(plan, last["context"], evaluator="synthetic-new-product-evaluator")
    assert (
        versions.deliver(
            build["record_id"],
            plan,
            "fixture-1",
            package_paths=["README.md"],
            documentation_paths=["README.md"],
        )
        == version
    )
    with pytest.raises(ConflictError, match="newest.*unfinished"):
        versions.deliver(build["record_id"], plan, "fixture-2", package_paths=["README.md"])
    assert versions.get(version["record_id"]) == version


def test_delivered_candidate_tamper_cannot_seed_review_or_evolution(delivered):
    versions, version, _, build, *_ = delivered
    candidate = Path(build["origin"]["candidate_root"])
    (candidate / "README.md").write_text("Changed retained product", encoding="utf-8")
    with pytest.raises(IntegrityError, match="bytes changed"):
        versions.require_delivered(version["record_id"])
    with pytest.raises(IntegrityError):
        versions.evolve(version["record_id"], "OPERATIONAL", "Try a tampered base.")


def test_actual_project_change_negotiation_is_atomic_and_replay_safe(delivered, monkeypatch):
    versions, version, _, _, _, refs, *_ = delivered
    evolution = versions.evolve(
        version["record_id"], "PROJECT_CHANGE", "Discuss a new observable requirement."
    )
    manager = ProjectManager(versions.repository.root)
    before = manager.list()
    old_update = versions.repository.update

    def fail_after_session(kind, *args, **kwargs):
        if kind == "EVOLUTION":
            raise RuntimeError("Synthetic failure after actual PM session creation")
        return old_update(kind, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(versions.repository, "update", fail_after_session)
        with pytest.raises(RuntimeError, match="actual PM"):
            versions.negotiate(evolution["record_id"])
    assert manager.list() == before
    assert versions.repository.get("EVOLUTION", evolution["record_id"])["state"] == "PROPOSED"
    assert not [
        item
        for item in versions.repository.list("OPERATION", version["project_id"])
        if item["origin"].get("operation") == "EVOLUTION_PM_NEGOTIATION"
    ]
    session = versions.negotiate(evolution["record_id"])
    assert session["base_ref"] == refs["project"].to_json()
    assert session["project_id"] == version["project_id"]
    assert session["state"] == "DRAFT" and session["published_ref"] is None
    assert versions.negotiate(evolution["record_id"])["session_id"] == session["session_id"]
    assert len(manager.list()) == len(before) + 1
    assert len(versions.store.list_revisions(refs["project"].contract_id)) == 1
