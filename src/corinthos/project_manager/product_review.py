# SPDX-License-Identifier: MPL-2.0
"""Optional delivered-product review, with exact foreground HUMAN authority."""

import secrets
import time
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from corinthos.contracts import (
    AuthorityError,
    ConflictError,
    ContractRef,
    IntegrityError,
    PublishContext,
    approval_request,
    validate_schema,
)
from corinthos.lifecycle.repository import LifecycleRepository, digest
from corinthos.report.rendering import safe_prose
from corinthos.report.service import ReportService, _public
from corinthos.report.sources import require_file_guard

from .approval import _terminal, local_actor_id
from .presentation import render_fields

_DECISIONS = {"ACCEPTED", "WITH_RESERVATIONS"}
_STATES = {"DRAFT", "AWAITING_EXPLICIT_APPROVAL", "DEFERRED", "PUBLISHING", "PUBLISHED"}


class ProductReviewService:
    """PM owns the human journey; Kernel REPORT authority publishes the exact ERC."""

    def __init__(self, store_or_root):
        from corinthos.lifecycle.versions import VersionService

        self.repository = LifecycleRepository(store_or_root)
        self.store = self.repository.store
        self.versions = VersionService(self.store)
        self.reports = ReportService(self.store)

    def _delivered(self, version_id, *, connection=None):
        return self.versions.require_delivered(version_id, connection=connection)

    def _record(self, review_id, *, connection=None):
        record = self.repository.get("REVIEW", review_id, connection=connection)
        try:
            origin, snapshot = record["origin"], record["snapshot"]
            if (
                record["state"] not in _STATES
                or set(origin)
                != {
                    "purpose",
                    "version_id",
                    "version_origin_sha256",
                    "project_ref",
                    "artifact_identity",
                    "source_draft_id",
                    "source_report_sha256",
                    "source_manifest_sha256",
                }
                or set(snapshot) != {"decision", "observations", "review", "published_ref"}
                or origin["purpose"] != "PRODUCT_ACCEPTANCE"
                or snapshot["decision"] not in _DECISIONS
                or not isinstance(snapshot["observations"], list)
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in snapshot["observations"]
                )
            ):
                raise ValueError
            project = ContractRef.from_json(origin["project_ref"])
            if project.contract_type != "PROJECT" or project.project_id != record["project_id"]:
                raise ValueError
            frozen = snapshot["review"]
            if frozen is not None:
                validate_schema(frozen["document"])
                if (
                    set(frozen) != {"document", "sha256", "expires_at", "receipt_id"}
                    or frozen["document"]["metadata"]["contract_type"] != "EVIDENCE_REPORT"
                    or frozen["document"]["metadata"]["project_id"] != record["project_id"]
                    or frozen["document"]["metadata"]["provenance"]
                    != {
                        "engine": "REPORT",
                        "actor_id": frozen["document"]["metadata"]["approval"]["actor_id"],
                        "source": "pm-product-review-sha256:" + digest(origin),
                    }
                    or frozen["document"]["metadata"]["approval"]["kind"] != "HUMAN"
                    or frozen["document"]["payload"]["feedback_and_acceptance"][
                        "review_approval_id"
                    ]
                    != frozen["document"]["metadata"]["approval"]["approval_id"]
                    or digest(frozen["document"]) != frozen["sha256"]
                    or type(frozen["expires_at"]) not in (int, float)
                    or frozen["expires_at"] <= 0
                    or frozen["document"]["payload"]["version_and_delivery_lineage"]["acceptance"]
                    != snapshot["decision"]
                ):
                    raise ValueError
            if (
                record["state"] in {"AWAITING_EXPLICIT_APPROVAL", "PUBLISHING", "PUBLISHED"}
                and frozen is None
            ):
                raise ValueError
            if record["state"] == "PUBLISHED":
                ContractRef.from_json(snapshot["published_ref"])
        except (KeyError, TypeError, ValueError, RecursionError):
            raise IntegrityError(
                "The stored product review is invalid; preserve it for inspection."
            ) from None
        return record

    def get(self, review_id):
        return self._record(review_id)

    def list(self, project_id):
        return [
            self._record(item["record_id"]) for item in self.repository.list("REVIEW", project_id)
        ]

    def start(self, version_id, *, decision, observations=(), actor_id="project-manager-review"):
        if decision not in _DECISIONS:
            raise IntegrityError(
                "Choose ACCEPTED or WITH_RESERVATIONS for an optional product review."
            )
        if (
            not isinstance(observations, (tuple, list))
            or len(observations) > 100
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item) > 8192
                or safe_prose(item) != item
                for item in observations
            )
        ):
            raise IntegrityError("Use bounded, nonempty public product-review observations.")
        if decision == "WITH_RESERVATIONS" and not observations:
            raise IntegrityError("A review with reservations must explain those reservations.")
        version = self._delivered(version_id)
        project_ref = ContractRef.from_json(version["origin"]["project_ref"])
        draft = self.reports.generate(
            project_ref,
            kind="PRODUCT",
            candidate=version["snapshot"]["candidate_root"],
            artifact_identity=version["origin"]["artifact_identity"],
            actor_id=actor_id,
        )
        if draft["document"]["payload"]["version_and_delivery_lineage"]["delivery"] != "DELIVERED":
            raise IntegrityError(
                "The source-backed Product report does not establish this delivery."
            )
        origin = {
            "purpose": "PRODUCT_ACCEPTANCE",
            "version_id": version_id,
            "version_origin_sha256": version["origin_sha256"],
            "project_ref": project_ref.to_json(),
            "artifact_identity": version["origin"]["artifact_identity"],
            "source_draft_id": draft["draft_id"],
            "source_report_sha256": digest(draft["document"]),
            "source_manifest_sha256": digest(
                self.reports.repository.get(draft["draft_id"])["manifest"]
            ),
        }
        with self.repository.transaction() as connection:
            current = self._delivered(version_id, connection=connection)
            if current != version:
                raise ConflictError("The delivered version changed during review preparation.")
            return self.repository.create(
                "REVIEW",
                project_ref.project_id,
                origin,
                state="DRAFT",
                snapshot={
                    "decision": decision,
                    "observations": list(observations),
                    "review": None,
                    "published_ref": None,
                },
                actor_id=actor_id,
                connection=connection,
            )

    def _source(self, record, connection):
        origin = record["origin"]
        version = self._delivered(origin["version_id"], connection=connection)
        if (
            version["origin_sha256"] != origin["version_origin_sha256"]
            or version["origin"]["artifact_identity"] != origin["artifact_identity"]
            or version["origin"]["project_ref"] != origin["project_ref"]
        ):
            raise ConflictError("This review no longer identifies its exact delivered version.")
        package = self.reports.repository.get(origin["source_draft_id"])
        if (
            digest(package["document"]) != origin["source_report_sha256"]
            or digest(package["manifest"]) != origin["source_manifest_sha256"]
        ):
            raise IntegrityError("The original ordinary Report capture changed.")
        ignored = [record["record_id"]]
        receipt_id = (record["snapshot"].get("review") or {}).get("receipt_id")
        if receipt_id is not None:
            ignored.append(receipt_id)
        guard = self.reports.require_review_source(
            origin["source_draft_id"],
            connection=connection,
            ignored_record_ids=tuple(ignored),
        )
        return package["document"], guard

    def freeze(self, review_id, expected_version, *, actor_id):
        """Freeze complete content for inspection; this creates no consent receipt."""
        with self.repository.transaction() as connection:
            record = self._record(review_id, connection=connection)
            if record["version"] != expected_version or record["state"] == "PUBLISHED":
                raise ConflictError("The product review changed or has already been published.")
            document, guard = self._source(record, connection)
            document = deepcopy(document)
            report_id = (
                "product-review-" + digest({"version_id": record["origin"]["version_id"]})[:32]
            )
            previous = self.reports.history(report_id)
            prior = previous[-1] if previous else None
            approval_id = "product-approval-" + uuid4().hex
            document["metadata"].update(
                contract_id=report_id,
                revision_id="product-review-revision-" + uuid4().hex,
                version=1 if prior is None else prior["metadata"]["version"] + 1,
                supersedes=None if prior is None else ContractRef.from_document(prior).to_json(),
                created_at=datetime.now(UTC).isoformat(),
                provenance={
                    "engine": "REPORT",
                    "actor_id": actor_id,
                    "source": "pm-product-review-sha256:" + digest(record["origin"]),
                },
                approval={"kind": "HUMAN", "approval_id": approval_id, "actor_id": actor_id},
            )
            document["payload"]["version_and_delivery_lineage"]["acceptance"] = record["snapshot"][
                "decision"
            ]
            document["payload"]["feedback_and_acceptance"]["review_approval_id"] = approval_id
            document["payload"]["decisions_and_change_history"]["notes"].extend(
                "Human product review observation. " + item
                for item in record["snapshot"]["observations"]
            )
            _public(document)
            validate_schema(document)
            snapshot = deepcopy(record["snapshot"])
            snapshot["review"] = {
                "document": document,
                "sha256": digest(document),
                "expires_at": time.time() + 900,
                "receipt_id": None,
            }
            require_file_guard(guard)
            return self.repository.update(
                "REVIEW",
                review_id,
                expected_version,
                state="AWAITING_EXPLICIT_APPROVAL",
                snapshot=snapshot,
                connection=connection,
                actor_id=actor_id,
                event="PRODUCT_REVIEW_FROZEN",
            )

    def defer(self, review_id, expected_version, *, actor_id):
        record = self._record(review_id)
        if record["state"] == "PUBLISHED":
            raise ConflictError("A published human review cannot be deferred.")
        snapshot = deepcopy(record["snapshot"])
        snapshot["review"] = None
        return self.repository.update(
            "REVIEW",
            review_id,
            expected_version,
            state="DEFERRED",
            snapshot=snapshot,
            actor_id=actor_id,
        )

    def _publish_consented(self, record, actor_id):
        """Trusted terminal bridge only; callers cannot supply consent claims or challenges."""
        frozen = record["snapshot"]["review"]
        request = approval_request(frozen["document"])
        if request.actor_id != actor_id or request.content_sha256 != frozen["sha256"]:
            raise AuthorityError("The local actor and complete product review do not match.")
        with self.repository.transaction() as connection:
            current = self._record(record["record_id"], connection=connection)
            if current != record or current["state"] != "AWAITING_EXPLICIT_APPROVAL":
                raise ConflictError("The product review changed after it was displayed.")
            if time.time() >= frozen["expires_at"]:
                raise AuthorityError("This review expired; review and approve it again.")
            _, guard = self._source(current, connection)
            receipt = self.repository.create(
                "OPERATION",
                current["project_id"],
                {
                    "operation": "HUMAN_PRODUCT_CONSENT",
                    "review_id": current["record_id"],
                    "review_version": current["version"],
                    "version_id": current["origin"]["version_id"],
                    "report_ref": request.ref.to_json(),
                    "content_sha256": request.content_sha256,
                    "actor_id": actor_id,
                    "approval_id": request.approval_id,
                    "expires_at": frozen["expires_at"],
                },
                state="AVAILABLE",
                connection=connection,
                actor_id=actor_id,
            )
            snapshot = deepcopy(current["snapshot"])
            snapshot["review"]["receipt_id"] = receipt["record_id"]
            publishing = self.repository.update(
                "REVIEW",
                current["record_id"],
                current["version"],
                state="PUBLISHING",
                snapshot=snapshot,
                connection=connection,
                actor_id=actor_id,
            )
            used = False

            def verify(actual):
                nonlocal used
                saved = self.repository.get(
                    "OPERATION", receipt["record_id"], connection=connection
                )
                review = self._record(publishing["record_id"], connection=connection)
                valid = (
                    not used
                    and actual == request
                    and saved == receipt
                    and saved["state"] == "AVAILABLE"
                    and review == publishing
                    and review["state"] == "PUBLISHING"
                    and time.time() < saved["origin"]["expires_at"]
                    and digest(review["snapshot"]["review"]["document"]) == request.content_sha256
                )
                used = bool(valid)
                return bool(valid)

            require_file_guard(guard)
            reference = self.store._publish(
                connection,
                frozen["document"],
                context=PublishContext("REPORT", actor_id, verify),
            )
            require_file_guard(guard)
            self.repository.update(
                "OPERATION",
                receipt["record_id"],
                receipt["version"],
                state="CONSUMED",
                connection=connection,
                actor_id=actor_id,
            )
            snapshot["published_ref"] = reference.to_json()
            return self.repository.update(
                "REVIEW",
                publishing["record_id"],
                publishing["version"],
                state="PUBLISHED",
                snapshot=snapshot,
                connection=connection,
                actor_id=actor_id,
                event="PRODUCT_REVIEW_PUBLISHED",
            )

    def approve_interactively(self, review_id, expected_version):
        """Publish only after a fresh exact challenge at the foreground OS terminal."""
        actor_id = local_actor_id()
        with _terminal() as (reader, writer):
            record = self.freeze(review_id, expected_version, actor_id=actor_id)
            frozen = record["snapshot"]["review"]
            writer.write(
                "\nDELIVERED PRODUCT ACCEPTANCE REVIEW\n"
                + render_fields(
                    {
                        "delivered_version": record["origin"],
                        "canonical_sha256": frozen["sha256"],
                        "expires_at": frozen["expires_at"],
                        "complete_candidate": frozen["document"],
                    }
                )
                + "\nThis records the displayed human product decision. It does not grant technical Validation or build promotion.\n"
            )
            challenge = "APPROVE " + secrets.token_hex(6)
            writer.write(
                "To publish this exact review, type "
                + challenge
                + "\nAny other answer defers publication.\n> "
            )
            writer.flush()
            if reader.readline(256).rstrip("\r\n") != challenge:
                return self.defer(review_id, record["version"], actor_id=actor_id)
            return self._publish_consented(record, actor_id)
