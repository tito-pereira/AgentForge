# SPDX-License-Identifier: MPL-2.0
"""Enforce the publication boundary between trusted callers and JSON input."""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from .model import AuthorityError, ContractRef, ContractType, canonical_json

_PUBLISHERS = {
    ContractType.PROJECT: "PROJECT_MANAGER",
    ContractType.WORKFLOW: "WORKFLOW",
    ContractType.MODULE: "WORKFLOW",
    ContractType.TECHNOLOGY_DECISION: "WORKFLOW",
    ContractType.VALIDATION: "VALIDATION",
    ContractType.VALIDATION_RESULT: "VALIDATION",
    ContractType.EVIDENCE_REPORT: "REPORT",
    ContractType.PROJECT_REVISION_REQUEST: "WORKFLOW",
}


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    ref: ContractRef
    approval_id: str
    kind: str
    actor_id: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class PublishContext:
    """Authenticated publisher identity and an optional trusted approval verifier."""

    engine: str
    actor_id: str
    verify_approval: Callable[[ApprovalRequest], bool] | None = None


def approval_request(document: dict) -> ApprovalRequest:
    """Bind a recorded approval to the exact proposed published document."""
    ref = ContractRef.from_document(document)
    approval = document["metadata"].get("approval")
    if not isinstance(approval, dict) or not all(
        isinstance(approval.get(key), str) for key in ("approval_id", "kind", "actor_id")
    ):
        raise AuthorityError("An approval request needs recorded approval provenance.")
    return ApprovalRequest(
        ref=ref,
        approval_id=approval["approval_id"],
        kind=approval["kind"],
        actor_id=approval["actor_id"],
        content_sha256=sha256(canonical_json(document).encode("utf-8")).hexdigest(),
    )


def _human_required(kind: ContractType, payload: dict, prior: dict) -> bool:
    if kind in {ContractType.PROJECT, ContractType.TECHNOLOGY_DECISION}:
        return True
    if kind == ContractType.WORKFLOW:
        return payload["playtest_milestones"] != prior.get("playtest_milestones", [])
    if kind == ContractType.MODULE:
        return any(
            payload[field] != prior.get(field, [])
            for field in ("provided_interfaces", "consumed_interfaces")
        )
    if kind == ContractType.EVIDENCE_REPORT:
        return payload["version_and_delivery_lineage"]["acceptance"] != "NOT_REVIEWED"
    return False


def require_authority(document: dict, previous: dict | None, context: PublishContext) -> None:
    """Validate authority for a schema-checked document in its revision lineage."""
    ref = ContractRef.from_document(document)
    kind = ref.contract_type
    metadata = document["metadata"]
    payload = document["payload"]
    provenance = metadata["provenance"]
    approval = metadata["approval"]
    if (
        not isinstance(context, PublishContext)
        or context.engine != _PUBLISHERS[kind]
        or context.engine != provenance["engine"]
        or context.actor_id != provenance["actor_id"]
    ):
        raise AuthorityError("Publisher identity or Engine is not authorized for this contract.")
    if kind == ContractType.PROJECT_REVISION_REQUEST and approval is not None:
        raise AuthorityError("A revision request cannot carry approval of a product change.")

    prior = previous["payload"] if previous is not None else {}
    human_required = _human_required(kind, payload, prior)
    if human_required and (approval is None or approval["kind"] != "HUMAN"):
        raise AuthorityError("This publication requires explicit human approval.")
    if previous is not None and kind in {ContractType.WORKFLOW, ContractType.MODULE}:
        if approval is None:
            raise AuthorityError("A changed plan requires verified human or delegated authority.")
    if kind == ContractType.EVIDENCE_REPORT:
        recorded_review = payload["feedback_and_acceptance"]["review_approval_id"]
        if human_required and recorded_review != approval["approval_id"]:
            raise AuthorityError("Report acceptance must cite its verified review approval.")
        if not human_required and recorded_review is not None:
            raise AuthorityError("An unreviewed report cannot claim a review approval.")

    if approval is not None:
        if context.verify_approval is None:
            raise AuthorityError("No trusted approval verifier was supplied.")
        try:
            verified = context.verify_approval(approval_request(document))
        except Exception:
            raise AuthorityError("The trusted approval verifier failed.") from None
        if verified is not True:
            raise AuthorityError("The approval was not verified for this exact publication.")
