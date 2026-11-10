# SPDX-License-Identifier: MPL-2.0
"""Bind a foreground local terminal action to one exact contract publication."""

import getpass
import hashlib
import json
import os
import secrets
import sys
import time
from contextlib import contextmanager
from copy import deepcopy

from corinthos.contracts import (
    AuthorityError,
    ConflictError,
    ContractRef,
    PublishContext,
    approval_request,
)
from corinthos.contracts.model import canonical_json

from .presentation import render_fields, render_review, safe_text


def local_actor_id():
    """Represent any local account label within the Kernel identifier format."""
    return "local:" + hashlib.sha256(getpass.getuser().encode("utf-8")).hexdigest()


@contextmanager
def _terminal():
    """Use the foreground OS terminal, never a provided transcript or pipe."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise AuthorityError("Approval requires a foreground interactive terminal.")
    try:
        if os.name == "nt":
            reader = open("CONIN$", encoding="utf-8")
            writer = open("CONOUT$", "w", encoding="utf-8")
        else:
            reader = open("/dev/tty", encoding="utf-8")
            writer = open("/dev/tty", "w", encoding="utf-8")
        with reader, writer:
            if not reader.isatty() or not writer.isatty():
                raise AuthorityError("Approval requires the local OS terminal.")
            if os.name != "nt" and os.tcgetpgrp(reader.fileno()) != os.getpgrp():
                raise AuthorityError("Background processes cannot request approval.")
            yield reader, writer
    except (OSError, UnicodeError):
        raise AuthorityError("The local approval terminal is unavailable.") from None


def _hash(document):
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def _finish(manager, connection, snapshot, document):
    review = snapshot["review"]
    if canonical_json(document) != canonical_json(review["document"]):
        raise AuthorityError("The published contract differs from the reviewed candidate.")
    request = approval_request(document)
    receipt = connection.execute(
        "SELECT * FROM pm_approvals WHERE approval_id = ?", (request.approval_id,)
    ).fetchone()
    if receipt is None or (
        receipt["session_id"],
        receipt["session_version"],
        receipt["project_id"],
        receipt["revision_id"],
        receipt["content_sha256"],
        receipt["actor_id"],
    ) != (
        snapshot["session_id"],
        snapshot["version"],
        request.ref.project_id,
        request.ref.revision_id,
        request.content_sha256,
        request.actor_id,
    ):
        raise AuthorityError("Publication recovery requires the exact local approval receipt.")
    result = deepcopy(snapshot)
    result["state"] = "PUBLISHED"
    result["published_ref"] = ContractRef.from_document(document).to_json()
    connection.execute(
        "UPDATE pm_approvals SET consumed = 1 WHERE approval_id = ?",
        (document["metadata"]["approval"]["approval_id"],),
    )
    return manager.repository._save(
        connection,
        snapshot["session_id"],
        snapshot["version"],
        result,
        actor_id=document["metadata"]["approval"]["actor_id"],
        action="project_published",
    )


def recover_publication(manager, snapshot):
    """Reconcile a committed publication, or revoke an interrupted approval."""
    from .service import _validate_snapshot

    if snapshot["state"] != "PUBLISHING":
        return snapshot
    # shortcut: a concurrent read can revoke live consent; add a process lease if needed.
    with manager.store._transaction() as connection:
        current = _validate_snapshot(manager.repository.get(snapshot["session_id"]))
        if current["state"] != "PUBLISHING":
            return current
        review = current["review"]
        document = review["document"]
        reference = ContractRef.from_document(document)
        stored = manager.store._lookup(connection, reference)
        if stored is not None:
            return _finish(manager, connection, current, stored)
        connection.execute(
            "UPDATE pm_approvals SET consumed = 1 WHERE approval_id = ?",
            (document["metadata"]["approval"]["approval_id"],),
        )
        current["state"] = "READY_FOR_REVIEW"
        current["review"] = None
        return manager.repository._save(
            connection,
            current["session_id"],
            current["version"],
            current,
            actor_id="project-manager-recovery",
            action="interrupted_approval_revoked",
        )


def _record_consent(manager, snapshot, actor):
    review = snapshot["review"]
    document = review["document"]
    request = approval_request(document)
    if request.actor_id != actor or review["sha256"] != request.content_sha256:
        raise AuthorityError("The review identity does not match the local approval.")
    if time.time() >= review["expires_at"]:
        raise AuthorityError("This review expired. Review and approve again.")
    with manager.store._transaction() as connection:
        current = manager.repository.get(snapshot["session_id"])
        if current != snapshot or current["state"] != "AWAITING_EXPLICIT_APPROVAL":
            raise ConflictError("The reviewed session changed. Review it again.")
        current["state"] = "PUBLISHING"
        current = manager.repository._save(
            connection,
            current["session_id"],
            current["version"],
            current,
            actor_id=actor,
            action="human_terminal_approval",
        )
        connection.execute(
            "INSERT INTO pm_approvals (approval_id, session_id, session_version, project_id, "
            "revision_id, content_sha256, actor_id, expires_at, consumed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                request.approval_id,
                current["session_id"],
                current["version"],
                request.ref.project_id,
                request.ref.revision_id,
                request.content_sha256,
                actor,
                review["expires_at"],
            ),
        )
    return current


def _verifier(manager, snapshot):
    expected = approval_request(snapshot["review"]["document"])
    used = False

    def verify(request):
        nonlocal used
        if used or request != expected:
            return False
        with manager.store._connection() as connection:
            receipt = connection.execute(
                "SELECT * FROM pm_approvals WHERE approval_id = ?",
                (request.approval_id,),
            ).fetchone()
            row = connection.execute(
                "SELECT version, snapshot FROM pm_sessions WHERE session_id = ?",
                (snapshot["session_id"],),
            ).fetchone()
            if receipt is None or row is None:
                return False
            current = json.loads(row["snapshot"])
            valid = (
                receipt["consumed"] == 0
                and receipt["session_id"] == snapshot["session_id"]
                and receipt["session_version"] == row["version"] == snapshot["version"]
                and receipt["project_id"] == request.ref.project_id
                and receipt["revision_id"] == request.ref.revision_id
                and receipt["content_sha256"] == request.content_sha256
                and receipt["actor_id"] == request.actor_id
                and receipt["expires_at"] > time.time()
                and current["state"] == "PUBLISHING"
                and current["review"]["sha256"] == request.content_sha256
                and _hash(current["review"]["document"]) == request.content_sha256
            )
        used = bool(valid)
        return bool(valid)

    return verify


def approve_interactively(manager, session_id, expected_version):
    """Review and publish only after an exact challenge on the local terminal."""
    actor = local_actor_id()
    with _terminal() as (reader, writer):
        snapshot = manager.review(session_id, expected_version, actor_id=actor)
        review = snapshot["review"]
        base = (
            manager.store.get(ContractRef.from_json(snapshot["base_ref"]))
            if snapshot["base_ref"] is not None
            else None
        )
        if snapshot["source_prr"] is not None:
            request = manager.store.get(ContractRef.from_json(snapshot["source_prr"]))
            if request is None:
                raise AuthorityError("The exact source revision request is unavailable.")
            writer.write("\nSource Project Revision Request\n" + render_fields(request, 2) + "\n")
        writer.write(
            render_review(
                review["document"],
                base_document=base,
                sha256=review["sha256"],
                expires_at=review["expires_at"],
                warnings=("Technical feasibility and semantic completeness require human review.",),
            )
        )
        writer.write(
            "\nRecorded preliminary feasibility (human claims)\n"
            + render_fields(snapshot["feasibility"], 2)
            + "\n"
        )
        challenge = "APPROVE " + secrets.token_hex(6)
        writer.write(
            "\nLocal OS account label: " + safe_text(getpass.getuser()) + "\n"
            "This approves the specification shown above.\n"
            "To approve this exact review, type " + challenge + "\n"
            "Any other answer defers publication.\n> "
        )
        writer.flush()
        answer = reader.readline(256)
        if answer.rstrip("\r\n") != challenge:
            return manager.defer(session_id, snapshot["version"], actor_id=actor)
        snapshot = _record_consent(manager, snapshot, actor)
        document = review["document"]
        try:
            manager.store.publish(
                document,
                context=PublishContext(
                    engine="PROJECT_MANAGER",
                    actor_id=actor,
                    verify_approval=_verifier(manager, snapshot),
                ),
            )
        except BaseException:
            recover_publication(manager, snapshot)
            raise
        return recover_publication(manager, snapshot)
