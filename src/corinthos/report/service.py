# SPDX-License-Identifier: MPL-2.0
"""Deterministic source-backed reporting through the existing Contract Kernel."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from corinthos.contracts import (
    AuthorityError,
    ConflictError,
    ContractRef,
    ContractStore,
    IntegrityError,
    PublishContext,
    validate_schema,
)
from corinthos.contracts.model import ID_PATTERN

from .composition import compose
from .delivery import observe_delivery
from .rendering import render_markdown, safe_prose
from .repository import ReportRepository, content_digest
from .sources import capture, require_file_guard, require_unchanged


def _now():
    return datetime.now(UTC).isoformat()


def _reference(value):
    ref = value if isinstance(value, ContractRef) else ContractRef.from_json(value)
    if ref.contract_type != "EVIDENCE_REPORT":
        raise IntegrityError("An exact Evidence & Report Contract reference is required.")
    return ref


def _public(value):
    if isinstance(value, dict):
        for key, item in value.items():
            _public(key)
            _public(item)
    elif isinstance(value, list):
        for item in value:
            _public(item)
    elif isinstance(value, str) and safe_prose(value) != value:
        raise IntegrityError(
            "Report fields contain unsafe source text or an unintended private value."
        )


def _same_content(left, right, prior_reason):
    left, right = deepcopy(left), deepcopy(right)
    left["report_scope"].pop("as_of", None)
    right["report_scope"].pop("as_of", None)
    owned_note = "Report revision reason. " + safe_prose(prior_reason)
    left["decisions_and_change_history"]["notes"] = [
        note for note in left["decisions_and_change_history"]["notes"] if note != owned_note
    ]
    return left == right


class ReportService:
    """Generate, publish and reopen immutable technical report snapshots."""

    def __init__(self, store_or_root):
        self.store = (
            store_or_root
            if isinstance(store_or_root, ContractStore)
            else ContractStore(store_or_root)
        )
        self.repository = ReportRepository(self.store)

    def _project(self, value, as_of):
        if isinstance(value, ContractRef):
            if value.contract_type != "PROJECT":
                raise IntegrityError("Report generation requires an exact Project Contract.")
            return value
        if not isinstance(value, str):
            raise IntegrityError("Use a Project Contract identity or project ID.")
        try:
            cutoff = datetime.fromisoformat(as_of) if as_of is not None else None
            if cutoff is not None and cutoff.utcoffset() is None:
                raise ValueError
        except (TypeError, ValueError):
            raise IntegrityError("Use a timezone-aware ISO cutoff.") from None
        eligible = {}
        for event in self.store.list_events():
            if event["contract_type"] != "PROJECT" or value not in {
                event["project_id"],
                event["contract_id"],
            }:
                continue
            if cutoff is not None and datetime.fromisoformat(event["occurred_at"]) > cutoff:
                continue
            ref = ContractRef(
                event["contract_id"], event["revision_id"], "PROJECT", event["project_id"]
            )
            document = self.store.get(ref)
            if (
                cutoff is None
                or datetime.fromisoformat(document["metadata"]["created_at"]) <= cutoff
            ):
                eligible[ref.contract_id] = ref
        if len(eligible) != 1:
            raise IntegrityError("The Project identity is missing or ambiguous at this cutoff.")
        return next(iter(eligible.values()))

    def generate(
        self,
        project,
        *,
        kind="PRODUCT",
        candidate=None,
        artifact_identity=None,
        as_of=None,
        checkpoint_ids=(),
        milestone_id=None,
        delivery_record=None,
        report_id=None,
        previous=None,
        reason=None,
        audience="Project owner",
        objective=None,
        actor_id="report-cli",
    ):
        project_ref = self._project(project, as_of)
        snapshot = capture(
            self.store,
            project_ref,
            kind=kind,
            artifact_identity=artifact_identity,
            candidate_root=candidate,
            checkpoint_ids=checkpoint_ids,
            milestone_id=milestone_id,
            as_of=as_of,
        )
        delivery = observe_delivery(
            delivery_record if snapshot["mode"] == "CURRENT" else None,
            project_ref,
            snapshot["artifact_identity"],
            candidate_root=candidate,
            executions=snapshot.get("executions", []),
        )
        if snapshot["mode"] == "AS_OF" and delivery_record is not None:
            delivery["gaps"].append(
                "A currently supplied external delivery record cannot establish historical delivery state."
            )
        snapshot["delivery"] = delivery
        request = {
            "kind": kind,
            "artifact_identity": snapshot["artifact_identity"],
            "checkpoint_ids": sorted(checkpoint_ids),
            "milestone_id": milestone_id,
            "audience": safe_prose(audience),
            "objective": safe_prose(
                objective or "Describe the exact scoped project facts and available proof."
            ),
        }
        payload = compose(snapshot, request)
        if previous is not None:
            previous = _reference(previous)
            if previous.project_id != project_ref.project_id or report_id not in (
                None,
                previous.contract_id,
            ):
                raise IntegrityError(
                    "The prior report belongs to another project or logical report."
                )
            report_id = previous.contract_id
        report_id = (
            report_id
            or "report-"
            + content_digest([project_ref.project_id, kind, sorted(checkpoint_ids), milestone_id])[
                :32
            ]
        )
        if not isinstance(report_id, str) or not ID_PATTERN.fullmatch(report_id):
            raise IntegrityError("Use a valid stable report identity.")
        revisions = self.history(report_id)
        prior = revisions[-1] if revisions else None
        prior_ref = ContractRef.from_document(prior) if prior else None
        if previous is not None and previous != prior_ref:
            raise ConflictError("The prior report revision is no longer the logical head.")
        if prior_ref is not None and prior_ref.project_id != project_ref.project_id:
            raise IntegrityError("The report identity already belongs to another project.")
        if prior is not None:
            existing = self.repository.find(prior_ref)
            if existing is not None and (
                existing["manifest"]["source_watermark"] == snapshot["watermark"]
                and existing["manifest"].get("delivery_provenance", {}).get("files", [])
                == delivery["provenance"].get("files", [])
                and _same_content(prior["payload"], payload, existing["manifest"]["reason"])
                and reason is None
            ):
                return self.draft(existing["draft_id"])
            payload["decisions_and_change_history"]["notes"].append(
                "Report revision reason. "
                + safe_prose(
                    reason
                    or "This report revision captures a changed source snapshot or candidate."
                )
            )
        metadata = {
            "contract_id": report_id,
            "revision_id": "report-revision-" + uuid4().hex,
            "contract_type": "EVIDENCE_REPORT",
            "project_id": project_ref.project_id,
            "version": 1 if prior is None else prior["metadata"]["version"] + 1,
            "schema_version": "1.0",
            "status": "PUBLISHED",
            "created_at": _now(),
            "supersedes": prior_ref.to_json() if prior_ref else None,
            "standard_ref": snapshot["project"]["metadata"]["standard_ref"],
            "provenance": {"engine": "REPORT", "actor_id": actor_id, "source": ""},
            "approval": None,
        }
        manifest = {
            "version": 1,
            "report_ref": {
                key: metadata[key]
                for key in ("contract_id", "revision_id", "contract_type", "project_id")
            },
            "content_sha256": content_digest(payload),
            "source_watermark": snapshot["watermark"],
            "source_manifest": snapshot["manifest"],
            "delivery_provenance": delivery["provenance"],
            "request": request,
            "reason": safe_prose(reason)
            if reason
            else (
                "This report revision captures a changed source snapshot or candidate."
                if prior is not None
                else "Source-backed report capture."
            ),
        }
        metadata["provenance"]["source"] = "report-manifest-sha256:" + content_digest(manifest)
        document = {"metadata": metadata, "payload": payload}
        _public(document)
        validate_schema(document)
        render_markdown(document)
        package = self.repository.freeze(document, manifest)
        return self.draft(package["draft_id"])

    def drafts(self):
        return self.repository.list_drafts()

    def draft(self, draft_id):
        package = self.repository.get(draft_id)
        return {
            "draft_id": draft_id,
            "report_ref": ContractRef.from_document(package["document"]).to_json(),
            "document": package["document"],
        }

    def publish(self, draft_id, *, actor_id=None):
        package = self.repository.get(draft_id)
        document, manifest = package["document"], package["manifest"]
        reference = ContractRef.from_document(document)
        expected_actor = document["metadata"]["provenance"]["actor_id"]
        if actor_id is not None and actor_id != expected_actor:
            raise AuthorityError("The publisher differs from the frozen report actor.")
        context = PublishContext("REPORT", expected_actor)
        _public(document)
        with self.store._connection() as connection:
            try:
                for _ in range(3):
                    existing = self.store._lookup(connection, reference)
                    guard = None
                    if existing is None:
                        version = connection.execute("PRAGMA data_version").fetchone()[0]
                        connection.execute("BEGIN")
                        guard = require_unchanged(
                            self.store,
                            connection,
                            manifest["source_manifest"],
                            extra_files=manifest["delivery_provenance"].get("files", []),
                        )
                        connection.execute("COMMIT")
                    connection.execute("BEGIN IMMEDIATE")
                    if (
                        existing is None
                        and connection.execute("PRAGMA data_version").fetchone()[0] != version
                    ):
                        connection.execute("ROLLBACK")
                        continue
                    if guard is not None:
                        require_file_guard(guard)
                    result = self.store._publish(connection, document, context=context)
                    if guard is not None:
                        require_file_guard(guard)
                    connection.execute("COMMIT")
                    break
                else:
                    raise ConflictError(
                        "Sources are changing during publication. Retry the frozen report."
                    )
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return self.repository.complete(draft_id, result)

    def recover(self, draft_id):
        return self.publish(draft_id)

    def get(self, reference):
        reference = _reference(reference)
        document = self.store.get(reference)
        if document is None:
            raise IntegrityError("The exact report revision was not found.")
        return document

    def history(self, report_id):
        documents = self.store.list_revisions(report_id)
        if any(item["metadata"]["contract_type"] != "EVIDENCE_REPORT" for item in documents):
            raise IntegrityError("The logical identity belongs to another contract type.")
        return documents

    def latest(self, report_id):
        documents = self.history(report_id)
        if not documents:
            raise IntegrityError("The report was not found.")
        return documents[-1]

    def list(self, project_id):
        identifiers = dict.fromkeys(
            event["contract_id"]
            for event in self.store.list_events()
            if event["project_id"] == project_id and event["contract_type"] == "EVIDENCE_REPORT"
        )
        return [self._summary(self.latest(identifier)) for identifier in identifiers]

    @staticmethod
    def _summary(document):
        payload = document["payload"]
        return {
            "report_ref": ContractRef.from_document(document).to_json(),
            "kind": payload["report_scope"]["kind"],
            "as_of": payload["report_scope"]["as_of"],
            "candidate": payload["report_scope"]["target_id"],
            "technical_validation": payload["version_and_delivery_lineage"]["technical_validation"],
        }

    def manifest(self, reference):
        self.get(reference)
        package = self.repository.find(_reference(reference))
        return package["manifest"] if package else None

    def compare(self, left, right):
        left, right = _reference(left), _reference(right)
        if left.project_id != right.project_id:
            raise IntegrityError("Compare reports from the same project.")
        first, second = self.get(left), self.get(right)
        _public(first)
        _public(second)
        return {
            "left": self._summary(first),
            "right": self._summary(second),
            "changes": [
                {"section": key, "left": value, "right": second["payload"][key]}
                for key, value in first["payload"].items()
                if value != second["payload"][key]
            ],
            "limitations": [
                "Each snapshot retains its candidate, cutoff and per-VRC metric denominator."
            ],
        }

    def verify(self, reference):
        document = self.get(reference)
        checks = {}
        for raw in document["payload"]["execution_and_validation_digest"]["validation_result_refs"]:
            result = self.store.get(ContractRef.from_json(raw))
            if result is None:
                raise IntegrityError("A report's exact Validation Result is unavailable.")
            for evidence in result["payload"]["evidence_refs"]:
                try:
                    self.store.verify_artifact(evidence["path"], evidence["sha256"])
                    checks[evidence["evidence_id"]] = {
                        "evidence_id": evidence["evidence_id"],
                        "state": "VERIFIED",
                    }
                except IntegrityError:
                    checks[evidence["evidence_id"]] = {
                        "evidence_id": evidence["evidence_id"],
                        "state": "UNAVAILABLE_OR_CORRUPT",
                        "reason": "The source file is unavailable or its bytes no longer match.",
                    }
        available = self.manifest(reference) is not None
        return {
            "report_ref": _reference(reference).to_json(),
            "observed_at": _now(),
            "document_sha256": content_digest(document),
            "manifest_available": available,
            "evidence": list(checks.values()),
            "complete": available and all(item["state"] == "VERIFIED" for item in checks.values()),
        }
