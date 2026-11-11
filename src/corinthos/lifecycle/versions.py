# SPDX-License-Identifier: MPL-2.0
"""Delivered artifact lineage and bounded evolution through existing Engine owners."""

from pathlib import Path

from corinthos.contracts import ConflictError, ContractRef, IntegrityError
from corinthos.report.fileguard import prepare as prepare_files
from corinthos.report.fileguard import require_file_guard
from corinthos.validation.procedures import digest, file_hash
from corinthos.workflow.reconciliation import RevisionReconciler
from corinthos.workflow.verification import (
    RequiredGate,
    ValidationGateConsumer,
    safe_workspace_path,
    workspace_snapshot,
)

from .builds import BuildService
from .repository import LifecycleRepository, identifier

_CLASSES = {"OPERATIONAL", "INTERNAL_REPLAN", "BINDING_PLAN", "PROJECT_CHANGE"}


class VersionService:
    def __init__(self, store_or_root):
        self.repository = LifecycleRepository(store_or_root)
        self.store = self.repository.store
        self.builds = BuildService(self.store)

    def get(self, version_id):
        return self.repository.get("VERSION", version_id)

    def list(self, project_id):
        return self.repository.list("VERSION", project_id)

    def require_delivered(self, version_id, connection=None):
        record = self.repository.get("VERSION", version_id, connection=connection)
        if record["state"] != "DELIVERED":
            raise IntegrityError("The exact version has no completed delivery record.")
        origin = record["origin"]
        if origin.get("source_kind") == "EXISTING_DELIVERY":
            source = self._existing_delivery(
                origin["report_ref"],
                record["snapshot"]["candidate_root"],
                origin["delivery_record"],
            )
            if source["origin"] != origin:
                raise IntegrityError(
                    "The retained original delivery or authenticated report changed."
                )
            return record
        build = self.repository.get("BUILD", origin["build_id"], connection=connection)
        if (
            build["project_id"] != record["project_id"]
            or build["origin"]["artifact_identity"] != origin["artifact_identity"]
            or build["state"] != "SEALED"
        ):
            raise IntegrityError("Delivered version and retained build lineage differ.")
        self.builds.identity_for_candidate(record["snapshot"]["candidate_root"], origin["build_id"])
        for package in origin["packages"]:
            path = safe_workspace_path(Path(record["snapshot"]["candidate_root"]), package["path"])
            if file_hash(path) != package["sha256"]:
                raise IntegrityError("A retained delivered package changed.")
        reference = ContractRef.from_json(origin["project_ref"])
        document = (
            self.store._lookup(connection, reference)
            if connection is not None
            else self.store.get(reference)
        )
        if document is None:
            raise IntegrityError("The delivered Project revision is unavailable.")
        return record

    def _existing_delivery(self, report_ref, candidate_root, delivery_record):
        from corinthos.report.delivery import _ordinary_path, observe_delivery
        from corinthos.report.service import ReportService

        reference = (
            report_ref if isinstance(report_ref, ContractRef) else ContractRef.from_json(report_ref)
        )
        reports = ReportService(self.store)
        document = reports.get(reference)
        manifest = reports.manifest(reference)
        package = reports.repository.find(reference) if manifest is not None else None
        payload = document["payload"]
        if (
            manifest is None
            or payload["report_scope"]["kind"] != "PRODUCT"
            or payload["version_and_delivery_lineage"]["delivery"] != "DELIVERED"
        ):
            raise IntegrityError(
                "Adoption requires an authenticated delivered Product report and its retained manifest."
            )
        source = manifest["source_manifest"]
        project = ContractRef.from_json(source["project_ref"])
        candidate = _ordinary_path(candidate_root)
        inventory = workspace_snapshot(candidate, max_bytes=256 * 1024 * 1024, max_files=8192)
        if source.get("candidate") is None or source["candidate"]["inventory"] != inventory:
            raise IntegrityError(
                "The retained baseline differs from the original whole-candidate inventory."
            )
        observed = observe_delivery(
            delivery_record,
            project,
            inventory["artifact_identity"],
            candidate_root=candidate,
            executions=source["executions"],
            observe_availability=False,
        )
        if (
            observed["delivery"] != "DELIVERED"
            or observed["product_version"]
            != payload["version_and_delivery_lineage"]["product_version"]
        ):
            raise IntegrityError(
                "The original package/version does not establish this delivered baseline."
            )
        execution = next(
            row
            for row in source["executions"]
            if row["execution_id"] == observed["provenance"]["execution_id"]
        )
        provenance = {
            key: value for key, value in observed["provenance"].items() if key != "observed_at"
        }
        source_refs = [project.to_json(), execution["workflow_ref"]]
        source_refs.extend(
            raw
            for raw in payload["source_refs"]
            if raw["contract_type"] not in {"PROJECT", "WORKFLOW"}
        )
        origin = {
            "source_kind": "EXISTING_DELIVERY",
            "report_ref": reference.to_json(),
            "report_manifest_sha256": digest(manifest),
            "project_ref": project.to_json(),
            "artifact_identity": inventory["artifact_identity"],
            "product_version": observed["product_version"],
            "previous_version_id": None,
            "source_refs": source_refs,
            "validation_result_refs": payload["execution_and_validation_digest"][
                "validation_result_refs"
            ],
            "delivery_record": str(_ordinary_path(delivery_record)),
            "delivery_provenance": provenance,
        }
        return {
            "origin": origin,
            "inventory": inventory,
            "candidate_root": str(candidate),
            "document": document,
            "frozen_report": {
                "path": str(reports.repository._directory(package["draft_id"]) / "frozen.json"),
                "sha256": digest(package),
                "limit": 8 * 1024 * 1024,
            },
        }

    def adopt_delivery(
        self, report_ref, candidate_root, delivery_record, *, actor_id="workflow-cli"
    ):
        """Retain a verified existing baseline without relabelling its original Validation identity."""
        source = self._existing_delivery(report_ref, candidate_root, delivery_record)
        origin = source["origin"]
        guard = prepare_files(
            self.store,
            {
                "evidence": [],
                "candidate": {"root": source["candidate_root"], "inventory": source["inventory"]},
            },
            lambda: self._existing_delivery(report_ref, candidate_root, delivery_record),
            extra_files=origin["delivery_provenance"]["files"],
        )
        report_guard = prepare_files(
            self.store,
            {"evidence": [], "candidate": None},
            lambda: self._existing_delivery(report_ref, candidate_root, delivery_record),
            extra_files=(source["frozen_report"],),
        )
        with self.repository.transaction() as conn:
            require_file_guard(guard)
            require_file_guard(report_guard)
            reference = ContractRef.from_json(origin["report_ref"])
            if self.store._lookup(conn, reference) != source["document"]:
                raise IntegrityError("The original delivered report is unavailable.")
            existing = next(
                (
                    row
                    for row in self.repository.list(
                        "VERSION", reference.project_id, connection=conn
                    )
                    if row["logical_key"] == origin["product_version"]
                ),
                None,
            )
            if existing is not None:
                if existing["origin"] != origin:
                    raise ConflictError("This product version already denotes another delivery.")
                require_file_guard(guard)
                require_file_guard(report_guard)
                return existing
            record = self.repository.create(
                "VERSION",
                reference.project_id,
                origin,
                state="DELIVERED",
                logical_key=origin["product_version"],
                snapshot={
                    "candidate_root": source["candidate_root"],
                    "availability": "UNOBSERVED",
                    "acceptance": "NOT_REVIEWED",
                },
                connection=conn,
                actor_id=actor_id,
                event="VERSION_DELIVERY_ADOPTED",
            )
            require_file_guard(guard)
            require_file_guard(report_guard)
            return record

    def _product_gate(self, reference, project, identity, connection):
        plan = self.store._lookup(connection, reference)
        if plan is None:
            raise IntegrityError("The exact Product Validation plan is unavailable.")
        scope = plan["payload"]["validation_scope"]
        if (
            reference.contract_type != "VALIDATION"
            or reference.project_id != project.project_id
            or scope["level"] != "PRODUCT"
            or scope["target_contract_ref"] != project.to_json()
            or set(scope["target_ids"]) != {project.project_id}
        ):
            raise IntegrityError("Delivery requires an exact whole-product Validation plan.")
        latest = connection.execute(
            "SELECT state FROM val_runs WHERE plan_revision_id=? AND artifact_sha256=? "
            "ORDER BY rowid DESC LIMIT 1",
            (reference.revision_id, digest(identity)),
        ).fetchone()
        if latest is None or latest["state"] != "PUBLISHED":
            raise ConflictError("The newest exact Product Validation run is missing or unfinished.")
        gate = RequiredGate(reference, None, "PRODUCT_VALIDATION", (project.project_id,), project)
        result = ValidationGateConsumer(self.store).consume(gate, identity)
        if result["state"] != "SATISFIED":
            raise ConflictError("Independent Product Validation does not permit delivery.")
        return result

    def deliver(
        self,
        build_id,
        product_plan_ref,
        product_version,
        *,
        package_paths,
        previous_version_id=None,
        documentation_paths=(),
        actor_id="workflow-cli",
    ):
        """Record delivery of a sealed, independently verified retained package, never install it."""
        if (
            not isinstance(product_version, str)
            or not 1 <= len(product_version) <= 128
            or any(ord(char) < 32 or ord(char) == 127 for char in product_version)
        ):
            raise IntegrityError("Use a bounded printable product version.")
        reference = (
            product_plan_ref
            if isinstance(product_plan_ref, ContractRef)
            else ContractRef.from_json(product_plan_ref)
        )
        build = self.builds.get(build_id)
        origin = build["origin"]
        manifest = self.builds._manifest(build)
        guard = prepare_files(
            self.store,
            {
                "evidence": [],
                "candidate": {
                    "root": origin["candidate_root"],
                    "inventory": {
                        "artifact_identity": origin["artifact_identity"],
                        "files": manifest["candidate"]["files"],
                    },
                },
            },
            lambda: self.builds.identity_for_candidate(origin["candidate_root"], build_id),
            extra_files=(
                {
                    "path": origin["manifest_path"],
                    "sha256": origin["manifest_sha256"],
                    "limit": 4 * 1024 * 1024,
                },
            ),
        )
        project = next(
            ContractRef.from_json(raw)
            for raw in origin["source_refs"]
            if raw["contract_type"] == "PROJECT"
        )
        if not isinstance(package_paths, (list, tuple)) or not 1 <= len(package_paths) <= 64:
            raise IntegrityError("Delivery requires explicit retained package paths.")
        if not isinstance(documentation_paths, (list, tuple)) or len(documentation_paths) > 128:
            raise IntegrityError("Use a bounded documentation path list.")
        files = manifest["candidate"]["files"]
        packages, documentation = [], []
        for paths, output in ((package_paths, packages), (documentation_paths, documentation)):
            for path in paths:
                safe_workspace_path(Path(origin["candidate_root"]), path)
                if path not in files or path in {item["path"] for item in output}:
                    raise IntegrityError(
                        "Delivery paths must be distinct retained candidate files."
                    )
                output.append({"path": path, **files[path]})
        request = {
            "build_id": build_id,
            "project_ref": project.to_json(),
            "artifact_identity": origin["artifact_identity"],
            "product_version": product_version,
            "previous_version_id": previous_version_id,
            "packages": packages,
            "documentation": documentation,
            "source_refs": origin["source_refs"],
            "validation_plan_ref": reference.to_json(),
        }
        with self.repository.transaction() as conn:
            require_file_guard(guard)
            existing = next(
                (
                    item
                    for item in self.repository.list("VERSION", project.project_id, connection=conn)
                    if item["logical_key"] == product_version
                ),
                None,
            )
            if existing is not None:
                if {
                    key: value
                    for key, value in existing["origin"].items()
                    if key != "validation_gate"
                } != request:
                    raise ConflictError(
                        "This delivered product version already denotes other bytes or lineage."
                    )
                record = self.require_delivered(existing["record_id"], connection=conn)
                require_file_guard(guard)
                return record
            self.builds.executions._fresh(conn, ContractRef.from_json(origin["workflow_ref"]))
            active = self.store.resolve_active(project.contract_id)
            if active is None or ContractRef.from_document(active) != project:
                raise ConflictError("Reconcile the Project revision before delivery.")
            if self.builds._execution(origin, conn)["state"] != "COMPLETED":
                raise ConflictError("Complete the governing Workflow before product delivery.")
            self.builds.identity_for_candidate(origin["candidate_root"], build_id)
            gate = self._product_gate(reference, project, origin["artifact_identity"], conn)
            previous = (
                self.require_delivered(previous_version_id, connection=conn)
                if previous_version_id is not None
                else None
            )
            if previous is not None and previous["project_id"] != project.project_id:
                raise IntegrityError("Incremental versions must preserve project identity.")
            request["validation_gate"] = gate
            require_file_guard(guard)
            record = self.repository.create(
                "VERSION",
                project.project_id,
                request,
                state="DELIVERED",
                logical_key=product_version,
                snapshot={
                    "candidate_root": origin["candidate_root"],
                    "manifest_path": origin["manifest_path"],
                    "manifest_sha256": origin["manifest_sha256"],
                    "availability": "UNOBSERVED",
                    "acceptance": "NOT_REVIEWED",
                },
                connection=conn,
                actor_id=actor_id,
                event="VERSION_DELIVERED",
            )
            require_file_guard(guard)
            return record

    def negotiate(self, evolution_id, *, actor_id="project-manager-evolution"):
        """Atomically open the actual PM revision journey once, without approving it."""
        from corinthos.project_manager.service import ProjectManager, _validate_snapshot

        manager = ProjectManager(self.repository.root)
        operation_id = "evolution-pm-" + digest({"evolution_id": evolution_id})[:40]
        with self.repository.transaction() as connection:
            evolution = self.repository.get("EVOLUTION", evolution_id, connection=connection)
            if evolution["origin"]["change_class"] != "PROJECT_CHANGE":
                raise IntegrityError(
                    "Only a changed product decision enters Project revision negotiation."
                )
            self.require_delivered(evolution["origin"]["version_id"], connection=connection)
            operation = self.repository.find("OPERATION", operation_id, connection=connection)
            origin = {
                "operation": "EVOLUTION_PM_NEGOTIATION",
                "evolution_id": evolution_id,
                "evolution_origin_sha256": evolution["origin_sha256"],
            }
            if operation is not None:
                if operation["state"] != "COMPLETED" or operation["origin"] != origin:
                    raise ConflictError("The PM negotiation operation requires inspected recovery.")
                return _validate_snapshot(
                    manager.repository.get(operation["snapshot"]["session_id"])
                )
            operation = self.repository.create(
                "OPERATION",
                evolution["project_id"],
                origin,
                state="RESERVED",
                record_id=operation_id,
                connection=connection,
                actor_id=actor_id,
            )
            session = manager.revise(
                ContractRef.from_json(evolution["origin"]["project_ref"]),
                "Evolution " + evolution_id + ": " + evolution["origin"]["reason"],
                actor_id=actor_id,
                connection=connection,
            )
            self.repository.update(
                "OPERATION",
                operation_id,
                operation["version"],
                state="COMPLETED",
                snapshot={"session_id": session["session_id"]},
                connection=connection,
                actor_id=actor_id,
            )
            self.repository.update(
                "EVOLUTION",
                evolution_id,
                evolution["version"],
                state="NEGOTIATING",
                snapshot={**evolution["snapshot"], "pm_session_id": session["session_id"]},
                connection=connection,
                actor_id=actor_id,
            )
            return session

    def evolve(self, version_id, change_class, reason, *, actor_id="workflow-cli", request_id=None):
        version = self.require_delivered(version_id)
        if not isinstance(change_class, str) or change_class not in _CLASSES:
            raise IntegrityError("Choose one of the four revision authority classes.")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 4096 or "\0" in reason:
            raise IntegrityError("Describe the bounded proposed evolution.")
        request_id = identifier(request_id) if request_id is not None else None
        workflow = next(
            raw for raw in version["origin"]["source_refs"] if raw["contract_type"] == "WORKFLOW"
        )
        reconciler = RevisionReconciler(self.store)
        impact = reconciler.inspect(workflow)
        origin = {
            "version_id": version_id,
            "change_class": change_class,
            "reason": reason,
            "project_ref": version["origin"]["project_ref"],
            "workflow_ref": workflow,
            "artifact_identity": version["origin"]["artifact_identity"],
            "impact": impact,
        }
        with self.repository.transaction() as conn:
            if reconciler.inspect(workflow) != impact:
                raise ConflictError(
                    "The evolution impact changed; inspect the current governing sources."
                )
            context = {}
            for kind in ("FEEDBACK", "REVIEW"):
                context[kind.lower()] = [
                    {
                        "record_id": row["record_id"],
                        "origin_sha256": row["origin_sha256"],
                        "version": row["version"],
                        "snapshot_sha256": row["snapshot_sha256"],
                        "state": row["state"],
                    }
                    for row in self.repository.list(kind, version["project_id"], connection=conn)
                    if (
                        kind == "FEEDBACK"
                        and row["origin"].get("admission", {}).get("artifact_identity")
                        == version["origin"]["artifact_identity"]
                        or kind == "REVIEW"
                        and row["origin"].get("version_id") == version_id
                    )
                ]
            origin["context_refs"] = context
            if request_id is not None:
                old = self.repository.find("EVOLUTION", request_id, connection=conn)
                if old is not None:
                    if old["origin"] != origin:
                        raise ConflictError(
                            "The evolution request ID already has a different origin."
                        )
                    return old
            return self.repository.create(
                "EVOLUTION",
                version["project_id"],
                origin,
                state="PROPOSED",
                record_id=request_id,
                actor_id=actor_id,
                connection=conn,
                snapshot={
                    "authority": {
                        "OPERATIONAL": "Workflow repair and relevant Validation; unchanged Project obligations.",
                        "INTERNAL_REPLAN": "Workflow bounded delegation or fresh HUMAN plan decision.",
                        "BINDING_PLAN": "Pertinent genuine HUMAN technology, interface or milestone decision.",
                        "PROJECT_CHANGE": "Project Manager negotiation and actual owner approval.",
                    }[change_class]
                },
            )
