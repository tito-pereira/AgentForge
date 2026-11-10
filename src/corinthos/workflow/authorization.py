# SPDX-License-Identifier: MPL-2.0
"""Exact candidate-set approval and narrowly bounded internal plan mandates."""

import hashlib
import json
import secrets
import time
from copy import deepcopy
from uuid import uuid4

from ..contracts import (
    AuthorityError,
    ConflictError,
    ContractRef,
    PublishContext,
    approval_request,
    validate_schema,
)
from ..contracts.model import canonical_json
from ..project_manager.approval import _terminal, local_actor_id
from .presentation import render_plan_review


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _invariant(document):
    """A mandate permits dependency edges only, with every obligation retained."""
    payload = deepcopy(document["payload"])
    for checkpoint in payload["checkpoints"]:
        checkpoint.pop("depends_on")
    return _digest(
        {
            "project_id": document["metadata"]["project_id"],
            "contract_id": document["metadata"]["contract_id"],
            "payload": payload,
        }
    )


def _mandate(planner, connection, mandate_id, document, actor):
    row = connection.execute(
        "SELECT * FROM wf_mandates WHERE mandate_id = ?", (mandate_id,)
    ).fetchone()
    if (
        row is None
        or document["metadata"]["contract_type"] != "WORKFLOW"
        or row["project_id"] != document["metadata"]["project_id"]
        or row["actor_id"] != actor
        or row["expires_at"] <= time.time()
        or row["invariant_sha256"] != _invariant(document)
    ):
        raise AuthorityError("No current bounded mandate authorizes this exact replan.")
    basis = planner.store._lookup(
        connection, ContractRef.from_json(json.loads(row["workflow_ref"]))
    )
    if basis is None or _invariant(basis) != row["invariant_sha256"]:
        raise AuthorityError("The mandate's approved Workflow basis is unavailable.")
    proof = approval_request(basis)
    receipt = connection.execute(
        "SELECT * FROM wf_approvals WHERE approval_id = ?", (proof.approval_id,)
    ).fetchone()
    origin = connection.execute(
        "SELECT snapshot FROM wf_sessions WHERE session_id = ?", (row["session_id"],)
    ).fetchone()
    if (
        proof.kind != "HUMAN"
        or receipt is None
        or receipt["consumed"] != 1
        or receipt["session_id"] != row["session_id"]
        or receipt["content_sha256"] != proof.content_sha256
        or receipt["actor_id"] != actor
        or origin is None
        or json.loads(origin["snapshot"])["state"] != "PUBLISHED"
    ):
        raise AuthorityError("The mandate has no completed exact human authorization.")
    return row


def _record(planner, snapshot, actor, *, delegate=False, mandate_id=None):
    review = snapshot["review"]
    documents = review["documents"]
    if (
        not documents
        or review["sha256"] != _digest(documents)
        or review["expires_at"] <= time.time()
    ):
        raise AuthorityError("The exact planning review is missing, changed or expired.")
    references = [ContractRef.from_document(document) for document in documents]
    compiled = [ContractRef.from_json(ref) for ref in snapshot["compiled_refs"]]
    if len(set(references)) != len(references) or not set(references) <= set(compiled):
        raise AuthorityError("The planning review has inconsistent publication identities.")
    for document in documents:
        validate_schema(document)
        if document["metadata"]["contract_type"] not in {
            "TECHNOLOGY_DECISION",
            "MODULE",
            "WORKFLOW",
        }:
            raise AuthorityError("This planning bridge cannot authorize another contract type.")
        if document["metadata"]["project_id"] != snapshot["project_id"]:
            raise AuthorityError("The reviewed document belongs to another project.")
    with planner.store._transaction() as connection:
        current = planner.repository.get(snapshot["session_id"])
        if current != snapshot or current["state"] != "AWAITING_EXPLICIT_APPROVAL":
            raise ConflictError("The planning session changed. Review it again.")
        requests = [approval_request(document) for document in documents]
        if any(request.actor_id != actor for request in requests):
            raise AuthorityError("The review actor differs from the local authorization.")
        if mandate_id is not None:
            for document, request in zip(documents, requests, strict=True):
                if request.kind != "DELEGATED":
                    raise AuthorityError("A delegated replan requires delegated provenance.")
                _mandate(planner, connection, mandate_id, document, actor)
        elif any(request.kind != "HUMAN" for request in requests):
            raise AuthorityError("The terminal action must approve HUMAN candidates.")
        if delegate:
            workflow = next(
                (doc for doc in documents if doc["metadata"]["contract_type"] == "WORKFLOW"), None
            )
            if workflow is None or mandate_id is not None:
                raise AuthorityError("A mandate requires an explicit human Workflow review.")
            mandate_id = "mandate-" + uuid4().hex
            connection.execute(
                "INSERT INTO wf_mandates VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    mandate_id,
                    current["session_id"],
                    current["project_id"],
                    actor,
                    _invariant(workflow),
                    canonical_json(ContractRef.from_document(workflow).to_json()),
                    time.time() + 86_400,
                ),
            )
        if mandate_id is not None:
            current["mandate_id"] = mandate_id
        current["state"] = "PUBLISHING"
        current["authorization_version"] = current["version"] + 1
        current = planner.repository._save(
            connection,
            current["session_id"],
            current["version"],
            current,
            actor_id=actor,
            action="exact_plan_delegation"
            if requests[0].kind == "DELEGATED"
            else "human_terminal_plan_approval",
        )
        for request in requests:
            connection.execute(
                "INSERT INTO wf_approvals (approval_id, session_id, session_version, project_id, "
                "contract_id, revision_id, kind, content_sha256, actor_id, expires_at, mandate_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.approval_id,
                    current["session_id"],
                    current["authorization_version"],
                    request.ref.project_id,
                    request.ref.contract_id,
                    request.ref.revision_id,
                    request.kind,
                    request.content_sha256,
                    actor,
                    review["expires_at"],
                    mandate_id if request.kind == "DELEGATED" else None,
                ),
            )
    return current


def _receipt_matches(row, request, snapshot):
    return row is not None and (
        row["session_id"],
        row["session_version"],
        row["project_id"],
        row["contract_id"],
        row["revision_id"],
        row["kind"],
        row["content_sha256"],
        row["actor_id"],
    ) == (
        snapshot["session_id"],
        snapshot["authorization_version"],
        request.ref.project_id,
        request.ref.contract_id,
        request.ref.revision_id,
        request.kind,
        request.content_sha256,
        request.actor_id,
    )


def _verifier(planner, snapshot, document):
    expected = approval_request(document)
    used = False

    def verify(request):
        nonlocal used
        if used or request != expected:
            return False
        with planner.store._connection() as connection:
            row = connection.execute(
                "SELECT * FROM wf_approvals WHERE approval_id = ?", (request.approval_id,)
            ).fetchone()
            current = planner.repository.get(snapshot["session_id"])
            if (
                not _receipt_matches(row, request, snapshot)
                or row["consumed"] != 0
                or row["expires_at"] <= time.time()
                or current["state"] != "PUBLISHING"
                or current["authorization_version"] != snapshot["authorization_version"]
                or current["version"] != snapshot["authorization_version"]
                or current["review"] != snapshot["review"]
                or _digest(current["review"]["documents"]) != current["review"]["sha256"]
            ):
                return False
            if request.kind == "DELEGATED":
                _mandate(planner, connection, row["mandate_id"], document, request.actor_id)
        used = True
        return True

    return verify


def recover_publication(planner, snapshot):
    """Preserve committed documents and revoke any uncertain pending approval."""
    if snapshot["state"] != "PUBLISHING":
        return snapshot
    # shortcut: a concurrent read can revoke live consent; add a process lease if needed.
    with planner.store._transaction() as connection:
        current = planner.repository.get(snapshot["session_id"])
        if current["state"] != "PUBLISHING":
            return current
        review = current["review"]
        if review["sha256"] != _digest(review["documents"]):
            raise AuthorityError("The pending planning review is inconsistent.")
        for document in review["documents"]:
            request = approval_request(document)
            row = connection.execute(
                "SELECT * FROM wf_approvals WHERE approval_id = ?", (request.approval_id,)
            ).fetchone()
            if not _receipt_matches(row, request, current):
                raise AuthorityError("Planning recovery needs each exact approval receipt.")
            stored = planner.store._lookup(connection, request.ref)
            if stored is not None and canonical_json(stored) != canonical_json(document):
                raise ConflictError("The reviewed revision identifies different stored content.")
            if row["consumed"] == 0:
                connection.execute(
                    "UPDATE wf_approvals SET consumed = 1 WHERE approval_id = ?",
                    (request.approval_id,),
                )
        published = [
            ref
            for ref in current["compiled_refs"]
            if planner.store._lookup(connection, ContractRef.from_json(ref)) is not None
        ]
        complete = len(published) == len(current["compiled_refs"])
        current["published_refs"] = published
        current["state"] = "PUBLISHED" if complete else "READY_FOR_REVIEW"
        if not complete:
            current["review"] = None
            current["authorization_version"] = None
        return planner.repository._save(
            connection,
            current["session_id"],
            current["version"],
            current,
            actor_id="workflow-recovery",
            action="plan_published" if complete else "partial_plan_approval_revoked",
        )


def _publish(planner, snapshot, actor):
    try:
        for document in snapshot["review"]["documents"]:
            planner.store.publish(
                document,
                context=PublishContext(
                    engine="WORKFLOW",
                    actor_id=actor,
                    verify_approval=_verifier(planner, snapshot, document),
                ),
            )
    except BaseException:
        recover_publication(planner, snapshot)
        raise
    return recover_publication(planner, snapshot)


def authorize_interactively(planner, session_id, expected_version):
    """One explicit terminal action authorizes the complete known candidate set."""
    actor = local_actor_id()
    with _terminal() as (reader, writer):
        snapshot = planner.review(session_id, expected_version, actor_id=actor)
        previous = [
            planner.store.get(ContractRef.from_json(doc["metadata"]["supersedes"]))
            for doc in snapshot["review"]["documents"]
            if doc["metadata"]["supersedes"] is not None
        ]
        writer.write(render_plan_review(snapshot, previous=previous))
        nonce = secrets.token_hex(6)
        approve, delegate = "APPROVE " + nonce, "DELEGATE " + nonce
        writer.write(
            "\nType " + approve + " to approve this exact complete set.\n"
            "Or type " + delegate + " to also authorize Workflow dependency-only replans\n"
            "for this local account for 24 hours, preserving every other obligation.\n"
            "Every other answer defers publication.\n> "
        )
        writer.flush()
        answer = reader.readline(256).rstrip("\r\n")
        if answer not in (approve, delegate):
            return planner.defer(session_id, snapshot["version"], actor_id=actor)
        snapshot = _record(planner, snapshot, actor, delegate=answer == delegate)
        return _publish(planner, snapshot, actor)


def publish_delegated(planner, session_id, expected_version, mandate_id):
    """Publish only a replan proved inside a recorded human mandate."""
    actor = local_actor_id()
    with planner.store._connection() as connection:
        existing = connection.execute(
            "SELECT 1 FROM wf_mandates WHERE mandate_id = ? AND actor_id = ? AND expires_at > ?",
            (mandate_id, actor, time.time()),
        ).fetchone()
        if existing is None:
            raise AuthorityError("No current recorded mandate authorizes delegation.")
    snapshot = planner.review(
        session_id, expected_version, actor_id=actor, approval_kind="DELEGATED"
    )
    snapshot = _record(planner, snapshot, actor, mandate_id=mandate_id)
    return _publish(planner, snapshot, actor)
