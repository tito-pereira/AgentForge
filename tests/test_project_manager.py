# SPDX-License-Identifier: MPL-2.0
"""Domain tests use a synthetic trusted publisher, never production consent."""

import json
import sqlite3
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    IntegrityError,
    PublishContext,
    approval_request,
)
from corinthos.contracts.model import canonical_json
from corinthos.project_manager.service import ProjectManager

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "contracts"
_ACTOR = "test-owner"


def _edit(manager, snapshot, **operation):
    return manager.edit(snapshot["session_id"], snapshot["version"], operation, actor_id=_ACTOR)


def _ready(manager):
    snapshot = manager.start("Create an offline greeting tool.", actor_id=_ACTOR)
    snapshot = _edit(
        manager, snapshot, action="set_scope", section="included", items=["Local greeting output"]
    )
    snapshot = _edit(
        manager,
        snapshot,
        action="upsert_requirement",
        description="Render a greeting.",
        acceptance_criteria=[{"criterion": "Input Ada produces Hello, Ada."}],
    )
    return _edit(
        manager,
        snapshot,
        action="upsert_success_criterion",
        criterion="A clean environment reproduces the greeting.",
    )


def _synthetic_publish(manager, document):
    provenance = document["metadata"]["provenance"]
    proof = approval_request(document) if document["metadata"]["approval"] is not None else None
    return manager.store.publish(
        document,
        context=PublishContext(
            provenance["engine"], provenance["actor_id"], lambda request: request == proof
        ),
    )


def _published_prr(manager):
    base = json.loads((_EXAMPLES / "project.json").read_text(encoding="utf-8"))
    base["payload"]["requirements"].append(
        {
            "requirement_id": "R2",
            "description": "Preserved requirement.",
            "acceptance_criteria": [{"criterion_id": "AC2", "criterion": "Preserved criterion."}],
        }
    )
    base["payload"]["constraints"].append(
        {"constraint_id": "C2", "description": "Preserved constraint."}
    )
    base_ref = _synthetic_publish(manager, base)
    prr = json.loads((_EXAMPLES / "project-revision-request.json").read_text(encoding="utf-8"))
    prr["payload"]["evidence"][0].update(source_ref=base_ref.to_json(), evidence_ids=[])
    prr["payload"]["impact"]["technology_decision_refs"] = []
    return base, _synthetic_publish(manager, prr)


def test_draft_review_survives_restart_without_publication(tmp_path):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    assert manager.assess(snapshot["session_id"])["issues"] == []
    reviewed = manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    document = reviewed["review"]["document"]
    assert reviewed["state"] == "AWAITING_EXPLICIT_APPROVAL"
    assert document["payload"] == snapshot["payload"]
    assert document["metadata"]["approval"]["kind"] == "HUMAN"
    assert reviewed["review"]["sha256"] == sha256(canonical_json(document).encode()).hexdigest()
    assert manager.store.get(ContractRef.from_document(document)) is None
    reopened = ProjectManager(tmp_path)
    assert reopened.get(snapshot["session_id"]) == reviewed
    assert reopened.list() == [reviewed]
    history = reopened.history(snapshot["session_id"])
    assert [turn["version"] for turn in history] == list(range(1, reviewed["version"] + 1))
    assert len({turn["turn_id"] for turn in history}) == len(history)


def test_structural_negotiation_preserves_rejected_options_outside_wire_contract(tmp_path):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    requirement_id = snapshot["payload"]["requirements"][0]["requirement_id"]
    for classification in ("REQUIREMENT", "SUGGESTION"):
        existing_proposals = set(snapshot["proposals"])
        snapshot = _edit(
            manager,
            snapshot,
            action="propose",
            kind=classification,
            description="Keep processing local.",
            requirement_ids=[requirement_id],
            constraint_ids=[],
            alternatives=["Use a local terminal.", "Use a local file."],
        )
        proposal_id = (snapshot["proposals"].keys() - existing_proposals).pop()
        assert manager.assess(snapshot["session_id"])["issues"]
        snapshot = _edit(
            manager,
            snapshot,
            action="decide_proposal",
            proposal_id=proposal_id,
            status="ACCEPTED" if classification == "REQUIREMENT" else "REJECTED",
            decision="Keep the explicit local requirement."
            if classification == "REQUIREMENT"
            else "Reject this suggestion.",
            rationale="The owner selected the terminal workflow.",
        )
    assert manager.assess(snapshot["session_id"])["issues"] == []
    assert len(snapshot["proposals"]) == 2
    assert len(snapshot["payload"]["structural_proposals"]) == 1
    assert snapshot["payload"]["structural_proposals"][0]["kind"] == "REQUIREMENT"
    assert len(snapshot["payload"]["negotiated_decisions"]) == 1
    assert (
        snapshot["proposals"][proposal_id]["last_decision"]["decision"] == "Reject this suggestion."
    )
    assert any(
        turn["snapshot"]["proposals"].get(proposal_id, {}).get("status") == "PROPOSED"
        for turn in manager.history(snapshot["session_id"])
    )


def test_review_edit_invalidates_frozen_identity_and_rejects_stale_version(tmp_path):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    reviewed = manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    edited = _edit(manager, reviewed, action="set_vision", text="Produce a clear offline greeting.")
    assert edited["review"] is None
    with pytest.raises(ConflictError, match="changed"):
        _edit(manager, reviewed, action="set_vision", text="Stale content")
    renewed = manager.review(edited["session_id"], edited["version"], actor_id=_ACTOR)
    assert renewed["review"]["sha256"] != reviewed["review"]["sha256"]
    assert (
        renewed["review"]["document"]["metadata"]["revision_id"]
        != reviewed["review"]["document"]["metadata"]["revision_id"]
    )


@pytest.mark.parametrize(
    "operation",
    [
        {"action": "set_scope", "section": "excluded", "items": ["  LOCAL greeting output  "]},
        {"action": "upsert_success_criterion", "criterion": "TBD"},
        {"action": "set_question", "text": "Which deployment targets matter?"},
        {
            "action": "propose",
            "kind": "REQUIREMENT",
            "description": "Remain local.",
            "requirement_ids": ["missing"],
            "constraint_ids": [],
        },
    ],
)
def test_demonstrable_missing_or_conflicting_draft_data_blocks_review(tmp_path, operation):
    manager = ProjectManager(tmp_path)
    ready = _ready(manager)
    snapshot = manager.edit(ready["session_id"], ready["version"], operation, actor_id=_ACTOR)
    assert manager.assess(snapshot["session_id"])["issues"]
    with pytest.raises(IntegrityError, match="clarification"):
        manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    assert manager.store.list_events() == []


def test_ids_cannot_cross_obligation_kinds_or_be_reused_after_deletion(tmp_path):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    requirement_id = snapshot["payload"]["requirements"][0]["requirement_id"]
    with pytest.raises(IntegrityError, match="reused"):
        _edit(
            manager,
            snapshot,
            action="upsert_constraint",
            constraint_id=requirement_id,
            description="Different kind",
        )
    snapshot = _edit(manager, snapshot, action="remove_requirement", requirement_id=requirement_id)
    with pytest.raises(IntegrityError, match="reused"):
        _edit(
            manager,
            snapshot,
            action="upsert_requirement",
            requirement_id=requirement_id,
            description="Reused identity",
            acceptance_criteria=[],
        )


@pytest.mark.parametrize("invalid_links", [["bad identifier"], ["R" * 129], ["R1", "R1"]])
def test_invalid_proposal_link_input_preserves_the_last_usable_snapshot(tmp_path, invalid_links):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    with pytest.raises(IntegrityError, match="Proposal links"):
        _edit(
            manager,
            snapshot,
            action="propose",
            kind="REQUIREMENT",
            description="Remain local.",
            requirement_ids=invalid_links,
            constraint_ids=[],
        )
    assert manager.get(snapshot["session_id"]) == snapshot
    assert manager.list() == [snapshot]


def test_question_resolution_and_feasibility_are_explicit_and_advisory(tmp_path):
    def assistance(snapshot):
        snapshot["payload"]["vision"] = "Advisory output cannot mutate persisted state"
        return ["Consider documenting the deployment assumption."]

    manager = ProjectManager(tmp_path, assistance=assistance)
    snapshot = _ready(manager)
    snapshot = _edit(
        manager, snapshot, action="set_question", text="What is the target environment?"
    )
    question_id = snapshot["questions"][0]["question_id"]
    snapshot = _edit(
        manager,
        snapshot,
        action="set_question",
        question_id=question_id,
        text="What is the target environment?",
        answer="The local terminal.",
    )
    with pytest.raises(IntegrityError, match="evidence"):
        _edit(
            manager,
            snapshot,
            action="record_feasibility",
            description="The host supports Python.",
            status="CONFIRMED",
            evidence=[],
        )
    snapshot = _edit(
        manager,
        snapshot,
        action="record_feasibility",
        description="The host supports Python.",
        status="ASSUMPTION",
        evidence=[],
    )
    result = manager.assess(snapshot["session_id"])
    assert result["issues"] == []
    assert any("NOT_VERIFIED" in item for item in result["unknowns"])
    assert any("Advisory assistance" in item for item in result["unknowns"])
    assert (
        manager.get(snapshot["session_id"])["payload"]["vision"]
        == "Create an offline greeting tool."
    )


def test_defer_resume_cancel_preserve_durable_choices_without_publish(tmp_path):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    deferred = manager.defer(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    reopened = ProjectManager(tmp_path)
    resumed = _edit(reopened, deferred, action="resume")
    assert resumed["payload"] == snapshot["payload"]
    cancelled = reopened.cancel(resumed["session_id"], resumed["version"], actor_id=_ACTOR)
    with pytest.raises(ConflictError, match="closed"):
        _edit(reopened, cancelled, action="resume")
    assert reopened.store.list_events() == []


def test_prr_change_preserves_unaffected_content_and_publishes_one_exact_successor(tmp_path):
    manager = ProjectManager(tmp_path)
    base, prr_ref = _published_prr(manager)
    snapshot = manager.receive_prr(prr_ref, "STRUCTURAL", actor_id=_ACTOR)
    with pytest.raises(IntegrityError, match="unaffected requirement"):
        _edit(
            manager,
            snapshot,
            action="upsert_requirement",
            requirement_id="R2",
            description="Forbidden drift",
            acceptance_criteria=base["payload"]["requirements"][1]["acceptance_criteria"],
        )
    with pytest.raises(IntegrityError, match="vision"):
        _edit(manager, snapshot, action="set_vision", text="Forbidden new project scope")
    snapshot = _edit(
        manager,
        snapshot,
        action="upsert_requirement",
        requirement_id="R1",
        description="Render a greeting for a supported name.",
        acceptance_criteria=base["payload"]["requirements"][0]["acceptance_criteria"],
    )
    reviewed = manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    document = reviewed["review"]["document"]
    assert document["payload"]["requirements"][1] == base["payload"]["requirements"][1]
    assert document["payload"]["constraints"] == base["payload"]["constraints"]
    assert document["metadata"]["supersedes"] == ContractRef.from_document(base).to_json()
    reference = _synthetic_publish(manager, document)
    assert _synthetic_publish(manager, document) == reference
    assert len(manager.store.list_revisions(reference.contract_id)) == 2


def test_prr_keep_unchanged_and_defer_create_no_revision(tmp_path):
    manager = ProjectManager(tmp_path)
    base, prr_ref = _published_prr(manager)
    snapshot = manager.receive_prr(prr_ref, "STRUCTURAL", actor_id=_ACTOR)
    with pytest.raises(ConflictError, match="Unchanged"):
        manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    original_decision = base["payload"]["negotiated_decisions"][0]
    snapshot = _edit(
        manager,
        snapshot,
        action="decide_proposal",
        proposal_id="P1",
        status="ACCEPTED",
        decision=original_decision["decision"],
        rationale=original_decision["rationale"],
    )
    assert snapshot["payload"] == base["payload"]
    with pytest.raises(ConflictError, match="Unchanged"):
        manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    kept = manager.keep(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    assert kept["state"] == "CLOSED_UNCHANGED"
    other = manager.receive_prr(prr_ref, "STRUCTURAL", actor_id=_ACTOR)
    deferred = manager.defer(other["session_id"], other["version"], actor_id=_ACTOR)
    assert deferred["state"] == "DEFERRED"
    assert len(manager.store.list_revisions(base["metadata"]["contract_id"])) == 1


def test_active_revision_advance_blocks_old_prr_and_concurrent_session(tmp_path):
    manager = ProjectManager(tmp_path)
    base, prr_ref = _published_prr(manager)
    snapshot = manager.receive_prr(prr_ref, "STRUCTURAL", actor_id=_ACTOR)
    advanced = deepcopy(base)
    advanced["metadata"].update(
        revision_id="advance-r2", version=2, supersedes=ContractRef.from_document(base).to_json()
    )
    advanced["payload"]["vision"] = "A separately approved new vision."
    _synthetic_publish(manager, advanced)
    with pytest.raises(ConflictError, match="stale"):
        manager.receive_prr(prr_ref, "STRUCTURAL", actor_id=_ACTOR)
    with pytest.raises(ConflictError, match="stale"):
        manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)


def test_unavailable_exact_prr_source_blocks_changes_with_a_controlled_error(tmp_path):
    manager = ProjectManager(tmp_path)
    _, prr_ref = _published_prr(manager)
    snapshot = manager.receive_prr(prr_ref, "STRUCTURAL", actor_id=_ACTOR)
    snapshot["source_prr"]["revision_id"] = "missing-source-revision"
    snapshot = manager.repository.save(
        snapshot["session_id"],
        snapshot["version"],
        snapshot,
        actor_id=_ACTOR,
        action="synthetic_missing_source",
    )
    assert manager.assess(snapshot["session_id"])["issues"]
    with pytest.raises(IntegrityError, match="exact source revision request is unavailable"):
        _edit(manager, snapshot, action="resume")


def test_direct_user_revision_needs_no_prr_and_preserves_identity(tmp_path):
    manager = ProjectManager(tmp_path)
    base, _ = _published_prr(manager)
    snapshot = manager.revise(
        ContractRef.from_document(base), "User requests a clearer product vision.", actor_id=_ACTOR
    )
    assert snapshot["source_prr"] is None
    assert snapshot["project_id"] == base["metadata"]["project_id"]
    snapshot = _edit(
        manager, snapshot, action="set_vision", text="An approved local greeting experience."
    )
    reviewed = manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    assert reviewed["review"]["document"]["metadata"]["version"] == 2


@pytest.mark.parametrize(
    "triage, state", [("RETURN", "RETURNED"), ("NEEDS_CLARIFICATION", "NEEDS_CLARIFICATION")]
)
def test_prr_triage_records_return_or_clarification_without_revision(tmp_path, triage, state):
    manager = ProjectManager(tmp_path)
    base, prr_ref = _published_prr(manager)
    snapshot = manager.receive_prr(prr_ref, triage, actor_id=_ACTOR)
    assert snapshot["state"] == state
    assert len(manager.store.list_revisions(base["metadata"]["contract_id"])) == 1


@pytest.mark.parametrize(
    "corruption",
    ["missing_state", "payload", "scope", "review_digest", "review_expiry", "base_ref"],
)
def test_corrupt_operational_state_fails_closed_before_all_service_reads(tmp_path, corruption):
    manager = ProjectManager(tmp_path)
    snapshot = _ready(manager)
    snapshot = manager.review(snapshot["session_id"], snapshot["version"], actor_id=_ACTOR)
    if corruption == "missing_state":
        del snapshot["state"]
    elif corruption == "payload":
        snapshot["payload"] = {"private-input": "Do not echo private input"}
    elif corruption == "scope":
        snapshot["payload"]["scope"]["included"] = "Do not echo private input"
    elif corruption == "review_digest":
        snapshot["review"]["sha256"] = "0" * 64
    elif corruption == "review_expiry":
        snapshot["review"]["expires_at"] = "Do not echo private input"
    else:
        snapshot["base_ref"] = {"private-input": "Do not echo private input"}
    with sqlite3.connect(manager.store.database_path) as connection:
        connection.execute(
            "UPDATE pm_sessions SET snapshot = ? WHERE session_id = ?",
            (json.dumps(snapshot), snapshot["session_id"]),
        )
    for read in (
        lambda: manager.get(snapshot["session_id"]),
        manager.list,
        lambda: manager.history(snapshot["session_id"]),
    ):
        with pytest.raises(IntegrityError, match="stored negotiation state is invalid") as caught:
            read()
        assert "private-input" not in str(caught.value)
    assert manager.store.list_events() == []


@pytest.mark.parametrize("status", ["ACCEPTED", "REJECTED"])
def test_refined_choice_supersedes_current_decision_and_preserves_other_proposal_links(
    tmp_path, status
):
    manager = ProjectManager(tmp_path)
    base = json.loads((_EXAMPLES / "project.json").read_text(encoding="utf-8"))
    other = {
        **deepcopy(base["payload"]["structural_proposals"][0]),
        "proposal_id": "P2",
        "kind": "SUGGESTION",
    }
    base["payload"]["structural_proposals"].append(other)
    base["payload"]["negotiated_decisions"][0]["proposal_ids"] = ["P1", "P2"]
    base_ref = _synthetic_publish(manager, base)
    snapshot = manager.revise(base_ref, "The owner refines one structural choice.", actor_id=_ACTOR)
    snapshot = _edit(
        manager,
        snapshot,
        action="decide_proposal",
        proposal_id="P1",
        status=status,
        decision="Use a revised local storage method.",
        rationale="The owner clarified the intended local behavior.",
    )
    decisions = snapshot["payload"]["negotiated_decisions"]
    preserved = next(item for item in decisions if item["decision_id"] == "D1")
    assert preserved == {**base["payload"]["negotiated_decisions"][0], "proposal_ids": ["P2"]}
    current = [item for item in decisions if "P1" in item["proposal_ids"]]
    assert len(current) == (1 if status == "ACCEPTED" else 0)
    if current:
        assert current[0]["decision"] == "Use a revised local storage method."
    assert any(
        turn["snapshot"]["payload"]["negotiated_decisions"]
        == base["payload"]["negotiated_decisions"]
        for turn in manager.history(snapshot["session_id"])
    )
    assert manager.assess(snapshot["session_id"])["issues"] == []
