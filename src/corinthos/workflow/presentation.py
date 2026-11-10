# SPDX-License-Identifier: MPL-2.0
"""Complete terminal-safe presentation of a frozen planning publication set."""

from hashlib import sha256

from corinthos.contracts.model import canonical_json
from corinthos.project_manager.presentation import render_fields, render_review


def render_plan_review(snapshot: dict, *, previous=(), warnings=()) -> str:
    """Display every frozen document, source identity and predecessor difference."""
    review = snapshot["review"]
    prior = {document["metadata"]["contract_id"]: document for document in previous}
    lines = ["WORKFLOW PLANNING REVIEW", "Planning identity"]
    lines.append(
        render_fields(
            {
                key: snapshot.get(key)
                for key in (
                    "session_id",
                    "project_id",
                    "workflow_contract_id",
                    "version",
                    "state",
                    "project_ref",
                    "base_ref",
                    "authorization_version",
                )
            }
        )
    )
    lines.extend(
        (
            "Frozen publication set",
            render_fields({key: value for key, value in review.items() if key != "documents"}),
        )
    )
    if "compiled_refs" in snapshot:
        lines.extend(("Compiled exact references", render_fields(snapshot["compiled_refs"])))
    lines.extend(
        (
            "Module constraint scope explanations",
            render_fields(
                {
                    identifier: module.get("constraint_exemptions", {})
                    for identifier, module in snapshot.get("draft", {}).get("modules", {}).items()
                }
            ),
        )
    )
    if warnings:
        lines.extend(("Outstanding checks and limitations", render_fields(list(warnings))))
    for document in review["documents"]:
        lines.append(
            render_review(
                document,
                base_document=prior.get(document["metadata"]["contract_id"]),
                sha256=sha256(canonical_json(document).encode("utf-8")).hexdigest(),
                expires_at=review["expires_at"],
            )
        )
    lines.append(
        "This publication records an engineering plan. Checkpoint execution is a later step."
    )
    return "\n".join(lines)
