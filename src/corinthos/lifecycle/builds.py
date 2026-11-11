# SPDX-License-Identifier: MPL-2.0
"""Workflow-owned sealed candidates and independent milestone admission."""

import json
import math
import platform
import sqlite3
import threading
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import distributions
from pathlib import Path
from uuid import uuid4

from corinthos.contracts import ConflictError, ContractRef, IntegrityError
from corinthos.contracts.artifacts import private_directory
from corinthos.contracts.model import ID_PATTERN, canonical_json
from corinthos.validation.procedures import _environment, _text, digest, file_hash
from corinthos.workflow.execution_repository import ExecutionRepository
from corinthos.workflow.verification import (
    AuditExpectation,
    CheckpointSpec,
    CommandCheck,
    RequiredGate,
    TechnicalReview,
    ValidationGateConsumer,
    _dependency_closure,
    command_check,
    relative_path,
    safe_workspace_path,
    workspace_snapshot,
    write_artifact,
)

from .repository import LifecycleRepository

_LIMIT = 256 * 1024 * 1024
_STATES = {"PREPARING", "SEALED", "INTERRUPTED", "FAILED", "RETIRING", "RETIRED"}


def _identifier(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise IntegrityError("Build operations require stable identifiers.")
    return value


def _ordinary_root(value):
    path = Path(value).absolute()
    if path.resolve(strict=True) != path or not path.is_dir():
        raise IntegrityError("Use an existing ordinary candidate directory.")
    return path


def _commands(checks):
    if not isinstance(checks, (list, tuple)) or len(checks) > 64:
        raise IntegrityError("Provide a bounded list of typed build checks.")
    rows, identifiers = [], set()
    for check in checks:
        if not isinstance(check, CommandCheck):
            raise IntegrityError("Build checks need distinct typed command identifiers.")
        _identifier(check.check_id)
        if check.check_id in identifiers:
            raise IntegrityError("Build checks need distinct typed command identifiers.")
        identifiers.add(check.check_id)
        if (
            not isinstance(check.argv, (tuple, list))
            or not 0 < len(check.argv) <= 64
            or any(
                not isinstance(arg, str) or not arg or len(arg) > 8192 or "\0" in arg
                for arg in check.argv
            )
            or not isinstance(check.plan_item, str)
            or not check.plan_item.strip()
            or len(check.plan_item) > 4096
            or type(check.timeout) not in (int, float)
            or not math.isfinite(check.timeout)
            or not 0 < check.timeout <= 600
        ):
            raise IntegrityError("Build commands require explicit bounded argv and time limits.")
        executable = Path(check.argv[0])
        for arg in check.argv:
            _text(arg, size=8192)
        if (
            not executable.is_absolute()
            or executable.suffix.casefold() in {".bat", ".cmd", ".ps1", ".sh"}
            or executable.stem.casefold()
            in {"cmd", "powershell", "pwsh", "sh", "bash", "zsh", "fish"}
        ):
            raise IntegrityError("Use a pinned absolute native executable without a shell.")
        relative_path(check.cwd, directory=True)
        inputs = {arg: file_hash(Path(arg)) for arg in check.argv if Path(arg).is_absolute()}
        rows.append({**asdict(check), "argv": list(check.argv), "inputs": inputs})
    return rows


def _review_matches(review, origin, identity):
    return (
        isinstance(review, TechnicalReview)
        and review.accepted is True
        and isinstance(review.actor_id, str)
        and ID_PATTERN.fullmatch(review.actor_id) is not None
        and review.actor_id not in {"codex", "claude"}
        and review.artifact_identity == identity
        and isinstance(review.criterion_ids, (list, tuple))
        and all(isinstance(item, str) for item in review.criterion_ids)
        and set(review.criterion_ids) == {item["criterion_id"] for item in origin["criteria"]}
        and isinstance(review.findings, (list, tuple))
        and bool(review.findings)
        and all(
            isinstance(item, str) and item.strip() and len(item) <= 4096 for item in review.findings
        )
    )


def _tool_observation(scratch):
    dependencies = []
    for distribution in distributions():
        if len(dependencies) >= 4096:
            raise IntegrityError("The controller dependency inventory exceeds the bounded limit.")
        dependencies.append(
            {
                "name": _text(distribution.metadata["Name"], size=256),
                "version": _text(distribution.version, size=256),
            }
        )
    return {
        "controller_python": platform.python_version(),
        "controller_sqlite": sqlite3.sqlite_version,
        "controller_distributions": sorted(
            dependencies, key=lambda row: (row["name"], row["version"])
        ),
        "launcher_configuration_sha256": digest(_environment(scratch)),
        "environment_policy": "Only launcher variables; isolated application/temp data; UTF-8 and no bytecode writes",
    }


class BuildService:
    """Materialize immutable bytes; ask Validation to audit rather than self-certify."""

    def __init__(self, project_root):
        self.repository = LifecycleRepository(project_root)
        self.store, self.root = self.repository.store, self.repository.root
        self.executions = ExecutionRepository(self.store)
        self.gates = ValidationGateConsumer(self.store)

    def _scope(self, workflow_ref, milestone_id, connection):
        reference = (
            workflow_ref
            if isinstance(workflow_ref, ContractRef)
            else ContractRef.from_json(workflow_ref)
        )
        workflow = self.executions._fresh(connection, reference)
        payload = workflow["payload"]
        milestones = {row["milestone_id"]: row for row in payload["playtest_milestones"]}
        if milestone_id not in milestones:
            raise IntegrityError("Select a milestone in the exact approved Workflow.")
        selected = _dependency_closure(milestones, (milestone_id,))
        checkpoints = {row["checkpoint_id"]: row for row in payload["checkpoints"]}
        required = {cp for mid in selected for cp in milestones[mid]["required_checkpoint_ids"]}
        closure = _dependency_closure(checkpoints, required)
        refs = [reference.to_json(), payload["project_contract_ref"]]
        refs.extend(row["module_contract_ref"] for row in payload["modules"])
        refs.extend(row["decision_contract_ref"] for row in payload["technology_decisions"])
        return {
            "workflow_ref": reference.to_json(),
            "source_refs": list({canonical_json(ref): ref for ref in refs}.values()),
            "milestone_id": milestone_id,
            "milestone_ids": sorted(selected),
            "checkpoint_ids": sorted(closure),
            "criteria": [
                item for mid in sorted(selected) for item in milestones[mid]["readiness_criteria"]
            ],
            "scenarios": list(
                dict.fromkeys(
                    item for mid in sorted(selected) for item in milestones[mid]["test_scenarios"]
                )
            ),
        }

    def _execution(self, origin, connection):
        scope = self._scope(origin["workflow_ref"], origin["milestone_id"], connection)
        if any(origin.get(key) != value for key, value in scope.items()):
            raise IntegrityError("The build scope differs from its exact approved Workflow.")
        row = self.executions._row(connection, origin["execution_id"])
        execution = self.executions._view(connection, row)
        if execution["workflow_ref"] != origin["workflow_ref"]:
            raise ConflictError("Build and execution have different exact Workflow revisions.")
        if execution["active_execution_id"] != execution["execution_id"]:
            raise ConflictError("Reconcile the superseded build execution first.")
        for cp in origin["checkpoint_ids"]:
            binding = execution["bindings"]["checkpoints"][cp]
            spec = CheckpointSpec.from_json(binding)
            if any(
                item.gate == "PLAYTEST_READINESS"
                for item in (*spec.required_gates, *spec.audit_expectations)
            ):
                raise ConflictError(
                    "Circular playtest gate: reconcile checkpoint and build audit stages."
                )
            if execution["checkpoints"][cp]["state"] != "COMPLETED":
                raise ConflictError(
                    "Every cumulative milestone checkpoint must be completed first."
                )
            attempt_id = execution["checkpoints"][cp]["attempt_id"]
            attempt = self.executions._attempt_view(
                connection, self.executions._attempt(connection, attempt_id)
            )
            details = attempt["details"]
            if (
                details.get("cleanup_confirmed") is not True
                or details.get("technical_review", {}).get("accepted") is not True
            ):
                raise ConflictError(
                    "Required checkpoint completion lacks its technical observations."
                )
            self.executions._source_manifest(attempt_id, details)
            gates, _ = self.gates.observe(
                ContractRef.from_json(origin["workflow_ref"]),
                cp,
                spec,
                details.get("artifact_identity"),
                retained=tuple(
                    AuditExpectation.from_json(item)
                    for item in details.get("audit_expectations", ())
                ),
            )
            if any(gate["state"] != "SATISFIED" for gate in gates):
                raise ConflictError(
                    "Current required checkpoint Validation proof blocks the build."
                )
            for gate in gates:
                reference = gate.get("validation_plan_ref")
                if reference is not None:
                    latest = connection.execute(
                        "SELECT state FROM val_runs WHERE plan_revision_id=? AND artifact_sha256=? ORDER BY rowid DESC LIMIT 1",
                        (reference["revision_id"], digest(details["artifact_identity"])),
                    ).fetchone()
                    if latest is not None and latest["state"] != "PUBLISHED":
                        raise ConflictError("A newer unfinished checkpoint audit blocks the build.")
        return execution

    def _paths(self, build_id, *, create=False):
        _identifier(build_id)
        base = private_directory(self.root, "snapshots", create=create)
        folder = base / build_id
        if create:
            folder.mkdir(mode=0o700, exist_ok=False)
        _ordinary_root(folder)
        return folder, folder / "candidate", folder / "manifest.json"

    def get(self, build_id):
        record = self.repository.get("BUILD", build_id)
        if record["state"] not in _STATES:
            raise IntegrityError("The build has an unknown lifecycle state.")
        origin = record["origin"]
        if origin.get("build_id") != build_id or origin.get("project_id") != record["project_id"]:
            raise IntegrityError("The build origin is inconsistent.")
        return record

    @staticmethod
    def _copy(source, destination, snapshot, *, full_inventory=False):
        from corinthos.validation.runtime import ValidationRunner

        ValidationRunner._copy(source, destination, snapshot, full_inventory=full_inventory)

    def _run(self, checks, candidate, scratch, run_id):
        observations = []
        for row in checks:
            if any(file_hash(Path(path)) != sha for path, sha in row["inputs"].items()):
                raise IntegrityError("A pinned build command input changed.")
            check = CommandCheck(**{key: value for key, value in row.items() if key != "inputs"})
            observation = command_check(
                self.store,
                candidate,
                run_id,
                check,
                threading.Event(),
                environment=_environment(scratch),
            )
            observations.append(observation)
            if any(file_hash(Path(path)) != sha for path, sha in row["inputs"].items()):
                raise IntegrityError("A build command input changed during execution.")
            if observation["state"] != "PASSED" or not observation["cleanup_confirmed"]:
                break
        return observations

    @staticmethod
    def _passed(checks, observations):
        return len(checks) == len(observations) and all(
            item["state"] == "PASSED"
            and item["cleanup_confirmed"]
            and item["check_id"] == check["check_id"]
            and item["plan_item"] == check["plan_item"]
            for check, item in zip(checks, observations, strict=True)
        )

    def prepare(
        self,
        workflow_ref,
        milestone_id,
        execution_id,
        source_root,
        *,
        commands=(),
        package_paths=(),
        operation_id=None,
    ):
        source = _ordinary_root(source_root)
        if not source.is_relative_to(self.root) or source.is_relative_to(self.root / ".corinthos"):
            raise IntegrityError("Build only an authorized nonprivate project workspace.")
        recipe = _commands(commands)
        if (
            not isinstance(package_paths, (list, tuple))
            or not all(isinstance(path, str) for path in package_paths)
            or len(set(package_paths)) != len(package_paths)
        ):
            raise IntegrityError("Declare distinct candidate-relative package paths.")
        for path in package_paths:
            relative_path(path)
        source_snapshot = workspace_snapshot(source, max_bytes=_LIMIT)
        with self.repository.transaction() as connection:
            scope = self._scope(workflow_ref, milestone_id, connection)
            execution = self._execution({**scope, "execution_id": execution_id}, connection)
            if Path(execution["workspace"]) != source:
                raise ConflictError("Materialize the exact completed execution workspace.")
        project_id = scope["workflow_ref"]["project_id"]
        operation_id = _identifier(operation_id or "build-operation-" + uuid4().hex)
        request = {
            **scope,
            "execution_id": execution_id,
            "source_root": str(source),
            "source_snapshot": source_snapshot,
            "commands": recipe,
            "package_paths": list(package_paths),
        }
        with self.repository.transaction() as connection:
            previous = self.repository.find("OPERATION", operation_id, connection=connection)
            if previous is not None:
                if previous["origin"].get("request") != request:
                    raise ConflictError("An operation ID cannot name a different build request.")
                if previous["state"] == "COMPLETED":
                    return self.get(previous["origin"]["build_id"])
                raise ConflictError(
                    "Inspect and recover the unfinished build operation before retrying."
                )
            if any(
                row["origin"].get("operation") == "BUILD"
                and row["origin"].get("request", {}).get("source_root") == str(source)
                and row["state"] not in {"COMPLETED", "CANCELLED"}
                for row in self.repository.list("OPERATION", project_id, connection=connection)
            ):
                raise ConflictError(
                    "Inspect the previous build preparation effects before starting another operation."
                )
            build_id = "build-" + uuid4().hex
            operation = self.repository.create(
                "OPERATION",
                project_id,
                {"operation": "BUILD", "build_id": build_id, "request": request},
                state="PREPARING",
                record_id=operation_id,
                logical_key=operation_id,
                connection=connection,
                event="BUILD_PREPARATION_STARTED",
            )
        try:
            folder, candidate, manifest_path = self._paths(build_id, create=True)
            scratch = folder / "scratch"
            scratch.mkdir(mode=0o700)
            self._copy(source, candidate, source_snapshot)
            observations = self._run(recipe, candidate, scratch, operation_id)
            if not self._passed(recipe, observations):
                raise ConflictError("Build command failed or process cleanup needs inspection.")
            sealed = workspace_snapshot(candidate, max_bytes=_LIMIT, include_ignored=True)
            for path in sealed["files"]:
                relative_path(path)
            for path in package_paths:
                package = safe_workspace_path(candidate, path)
                if (
                    path not in sealed["files"]
                    or file_hash(package) != sealed["files"][path]["sha256"]
                ):
                    raise IntegrityError(
                        "A declared package is missing or excluded from the sealed inventory."
                    )
            if workspace_snapshot(source, max_bytes=_LIMIT) != source_snapshot:
                raise ConflictError("The development source changed during build preparation.")
            manifest = {
                "build_id": build_id,
                "project_id": project_id,
                "request": request,
                "candidate": sealed,
                "observations": observations,
                "tools": _tool_observation(scratch),
                "candidate_root": str(candidate),
            }
            with manifest_path.open("xb") as stream:
                stream.write(canonical_json(manifest).encode("utf-8"))
            manifest_sha = file_hash(manifest_path)
            with self.repository.transaction() as connection:
                self._scope(scope["workflow_ref"], milestone_id, connection)
                self._execution(request, connection)
                operation = self.repository.update(
                    "OPERATION",
                    operation_id,
                    operation["version"],
                    state="FROZEN",
                    snapshot={"manifest_sha256": manifest_sha, "manifest_path": str(manifest_path)},
                    connection=connection,
                    event="BUILD_SEAL_OBSERVED",
                )
            return self._finish(operation)
        except (OSError, ValueError, KeyboardInterrupt):
            current = self.repository.get("OPERATION", operation_id)
            if current["state"] == "PREPARING":
                self.repository.update(
                    "OPERATION",
                    operation_id,
                    current["version"],
                    state="INTERRUPTED",
                    snapshot={"inspection_required": True},
                    event="BUILD_PREPARATION_INTERRUPTED",
                )
            raise

    def _finish(self, operation):
        build_id = operation["origin"]["build_id"]
        request = operation["origin"]["request"]
        _, candidate, manifest_path = self._paths(build_id)
        if file_hash(manifest_path) != operation["snapshot"]["manifest_sha256"]:
            raise IntegrityError("The observed build seal changed before completion.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest["request"] != request
            or workspace_snapshot(candidate, max_bytes=_LIMIT, include_ignored=True)
            != manifest["candidate"]
        ):
            raise IntegrityError("The staged build differs from its anchored seal.")
        identity = {
            **manifest["candidate"]["artifact_identity"],
            "build_id": build_id,
            "artifact_id": "manifest-" + operation["snapshot"]["manifest_sha256"],
        }
        origin = {
            **request,
            "build_id": build_id,
            "project_id": operation["project_id"],
            "operation_id": operation["record_id"],
            "candidate_root": str(candidate),
            "manifest_path": str(manifest_path),
            "manifest_sha256": operation["snapshot"]["manifest_sha256"],
            "artifact_identity": identity,
        }
        with self.repository.transaction() as connection:
            self._scope(request["workflow_ref"], request["milestone_id"], connection)
            self._execution(request, connection)
            current = self.repository.get(
                "OPERATION", operation["record_id"], connection=connection
            )
            if current["version"] != operation["version"]:
                raise ConflictError("The build operation changed during sealing.")
            if (
                file_hash(manifest_path) != operation["snapshot"]["manifest_sha256"]
                or workspace_snapshot(candidate, max_bytes=_LIMIT, include_ignored=True)
                != manifest["candidate"]
            ):
                raise IntegrityError("The candidate changed during the final seal transition.")
            build = self.repository.create(
                "BUILD",
                operation["project_id"],
                origin,
                record_id=build_id,
                state="SEALED",
                snapshot={"readiness": None},
                connection=connection,
                event="BUILD_SEALED",
            )
            self.repository.update(
                "OPERATION",
                operation["record_id"],
                current["version"],
                state="COMPLETED",
                snapshot=current["snapshot"],
                connection=connection,
                event="BUILD_PREPARATION_COMPLETED",
            )
            return build

    def recover(self, operation_id, inspection):
        """Reconcile an anchored seal after genuine stopped-process/effect inspection."""
        operation = self.repository.get("OPERATION", operation_id)
        if operation["origin"].get("operation") not in {"BUILD", "BUILD_READINESS"}:
            raise IntegrityError("Recover an actual build preparation operation.")
        if operation["state"] == "COMPLETED":
            return self.get(operation["origin"]["build_id"])
        if (
            not isinstance(inspection, dict)
            or inspection.get("process_stopped") is not True
            or inspection.get("effects_inspected") is not True
            or not isinstance(inspection.get("reason"), str)
            or not inspection["reason"].strip()
        ):
            raise IntegrityError("Record actual stopped-process and effect inspection first.")
        if operation["origin"]["operation"] == "BUILD_READINESS":
            with self.repository.transaction() as connection:
                record = self.repository.get(
                    "BUILD", operation["origin"]["build_id"], connection=connection
                )
                if record["snapshot"].get("readiness", {}).get("operation_id") != operation_id:
                    raise ConflictError("A newer readiness observation superseded this operation.")
                record = self.repository.update(
                    "BUILD",
                    record["record_id"],
                    record["version"],
                    snapshot={
                        **record["snapshot"],
                        "readiness": {
                            "state": "BLOCKED",
                            "operation_id": operation_id,
                            "inspection": inspection,
                        },
                    },
                    connection=connection,
                    event="BUILD_READINESS_RECOVERED",
                )
                self.repository.update(
                    "OPERATION",
                    operation_id,
                    operation["version"],
                    state="CANCELLED",
                    snapshot={"inspection": inspection},
                    connection=connection,
                    event="BUILD_READINESS_INTERRUPTED",
                )
                return record
        if operation["state"] != "FROZEN":
            return self.repository.update(
                "OPERATION",
                operation_id,
                operation["version"],
                state="CANCELLED",
                snapshot={
                    **operation["snapshot"],
                    "inspection": inspection,
                    "disposition": "ABANDONED",
                },
                event="BUILD_EFFECTS_INSPECTED",
            )
        self.repository.event(
            operation["project_id"], "BUILD_RECOVERY_INSPECTED", inspection, record_id=operation_id
        )
        return self._finish(operation)

    def _manifest(self, record):
        origin = record["origin"]
        _, candidate, manifest_path = self._paths(record["record_id"])
        if (
            str(candidate) != origin["candidate_root"]
            or str(manifest_path) != origin["manifest_path"]
        ):
            raise IntegrityError("The build payload is outside its owned path.")
        if file_hash(manifest_path) != origin["manifest_sha256"]:
            raise IntegrityError("The sealed build manifest changed.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        observed = workspace_snapshot(
            _ordinary_root(candidate), max_bytes=_LIMIT, include_ignored=True
        )
        if (
            observed != manifest["candidate"]
            or manifest["build_id"] != record["record_id"]
            or manifest["project_id"] != record["project_id"]
        ):
            raise IntegrityError("The sealed build candidate bytes changed.")
        expected = {
            **observed["artifact_identity"],
            "build_id": record["record_id"],
            "artifact_id": "manifest-" + origin["manifest_sha256"],
        }
        if expected != origin["artifact_identity"]:
            raise IntegrityError("The full sealed build identity differs.")
        return manifest

    def identity_for_candidate(self, candidate_root, build_id):
        record = self.get(build_id)
        if record["state"] != "SEALED" or _ordinary_root(candidate_root) != Path(
            record["origin"]["candidate_root"]
        ):
            raise IntegrityError("Audit only the exact owned sealed build candidate.")
        self._manifest(record)
        return record["origin"]["artifact_identity"]

    def readiness(self, build_id, *, checks, reviewer=None):
        record = self.get(build_id)
        origin = record["origin"]
        identity = self.identity_for_candidate(origin["candidate_root"], build_id)
        recipe = _commands(checks)
        if not recipe or {row["plan_item"] for row in recipe} != set(origin["scenarios"]):
            raise IntegrityError(
                "Bind every exact cumulative milestone scenario to an actual check."
            )
        run_id = "build-readiness-" + uuid4().hex
        with self.repository.transaction() as connection:
            self._scope(origin["workflow_ref"], origin["milestone_id"], connection)
            self._execution(origin, connection)
            if (record["snapshot"].get("readiness") or {}).get("state") == "RUNNING":
                raise ConflictError("Inspect the unfinished readiness operation before retrying.")
            operation = self.repository.create(
                "OPERATION",
                record["project_id"],
                {
                    "operation": "BUILD_READINESS",
                    "build_id": build_id,
                    "artifact_identity": identity,
                    "checks": recipe,
                },
                state="RUNNING",
                record_id=run_id,
                connection=connection,
                event="BUILD_READINESS_STARTED",
            )
            record = self.repository.update(
                "BUILD",
                build_id,
                record["version"],
                snapshot={
                    **record["snapshot"],
                    "readiness": {
                        "state": "RUNNING",
                        "operation_id": run_id,
                        "artifact_identity": identity,
                    },
                },
                connection=connection,
                event="BUILD_READINESS_PENDING",
            )
        folder = private_directory(self.root, "snapshots", create=True) / run_id
        folder.mkdir(mode=0o700)
        candidate, scratch = folder / "candidate", folder / "scratch"
        scratch.mkdir(mode=0o700)
        self._copy(
            Path(origin["candidate_root"]),
            candidate,
            self._manifest(record)["candidate"],
            full_inventory=True,
        )
        observations = self._run(recipe, candidate, scratch, run_id)
        review = (
            None
            if reviewer is None
            else reviewer(
                {
                    "build_id": build_id,
                    "artifact_identity": identity,
                    "criteria": origin["criteria"],
                    "candidate_root": str(candidate),
                    "checks": observations,
                }
            )
        )
        accepted = self._passed(recipe, observations) and _review_matches(review, origin, identity)
        evidence = write_artifact(
            self.store,
            run_id,
            "readiness.json",
            canonical_json(
                {
                    "checks": observations,
                    "review": {
                        **asdict(review),
                        "criterion_ids": list(review.criterion_ids),
                        "findings": list(review.findings),
                    }
                    if isinstance(review, TechnicalReview)
                    else None,
                    "artifact_identity": identity,
                }
            ).encode("utf-8"),
        )
        self.identity_for_candidate(origin["candidate_root"], build_id)
        if (
            workspace_snapshot(candidate, include_ignored=True)["files"]
            != self._manifest(record)["candidate"]["files"]
        ):
            raise IntegrityError("A readiness procedure changed candidate bytes.")
        with self.repository.transaction() as connection:
            self._scope(origin["workflow_ref"], origin["milestone_id"], connection)
            self._execution(origin, connection)
            if not all(item["cleanup_confirmed"] for item in observations):
                raise ConflictError("Inspect process cleanup before recovering readiness.")
            record = self.repository.update(
                "BUILD",
                build_id,
                record["version"],
                snapshot={
                    **record["snapshot"],
                    "readiness": {
                        "state": "SATISFIED" if accepted else "BLOCKED",
                        "artifact_identity": identity,
                        "operation_id": run_id,
                        "evidence": evidence,
                        "checks": recipe,
                    },
                },
                connection=connection,
                event="BUILD_READINESS_OBSERVED",
            )
            self.repository.update(
                "OPERATION",
                run_id,
                operation["version"],
                state="COMPLETED",
                snapshot={"evidence": evidence, "state": "SATISFIED" if accepted else "BLOCKED"},
                connection=connection,
                event="BUILD_READINESS_COMPLETED",
            )
            return record

    def validate(
        self, build_id, plan_ref, *, evaluator, reviewer=None, previous_run_id=None, cancel=None
    ):
        from corinthos.validation.runtime import ValidationRunner

        record = self.get(build_id)
        self._ready(record)
        plan = self.store.get(plan_ref)
        self._plan_matches(record, plan)
        return ValidationRunner(self.store).run(
            plan_ref,
            record["origin"]["candidate_root"],
            evaluator=evaluator,
            build_id=build_id,
            reviewer=reviewer,
            previous_run_id=previous_run_id,
            cancel=cancel,
        )

    def _ready(self, record, connection=None):
        readiness = record["snapshot"].get("readiness")
        if (
            record["state"] != "SEALED"
            or not isinstance(readiness, dict)
            or readiness.get("state") != "SATISFIED"
            or readiness.get("artifact_identity") != record["origin"]["artifact_identity"]
        ):
            raise ConflictError("The sealed build has no satisfied Workflow readiness observation.")
        proof = readiness["evidence"]
        self.store.verify_artifact(proof["path"], proof["sha256"])
        operations = [
            row
            for row in self.repository.list(
                "OPERATION", record["project_id"], connection=connection
            )
            if row["origin"].get("operation") == "BUILD_READINESS"
            and row["origin"].get("build_id") == record["record_id"]
        ]
        if (
            not operations
            or operations[-1]["record_id"] != readiness.get("operation_id")
            or operations[-1]["state"] != "COMPLETED"
            or operations[-1]["snapshot"].get("state") != "SATISFIED"
            or operations[-1]["snapshot"].get("evidence") != proof
            or operations[-1]["origin"].get("checks") != readiness.get("checks")
        ):
            raise IntegrityError(
                "The latest readiness operation does not support this observation."
            )
        raw = (private_directory(self.root, "artifacts") / proof["path"]).read_bytes()
        if sha256(raw).hexdigest() != proof["sha256"]:
            raise IntegrityError("Readiness evidence changed during inspection.")
        observed = json.loads(raw)
        review = observed.get("review")
        if (
            observed.get("artifact_identity") != record["origin"]["artifact_identity"]
            or not self._passed(readiness["checks"], observed.get("checks", []))
            or not isinstance(review, dict)
            or set(review)
            != {"actor_id", "accepted", "criterion_ids", "artifact_identity", "findings"}
            or not _review_matches(
                TechnicalReview(**review), record["origin"], readiness["artifact_identity"]
            )
        ):
            raise IntegrityError("The retained readiness evidence is incomplete or mismatched.")
        for observation in observed["checks"]:
            artifact = observation["evidence"]
            self.store.verify_artifact(artifact["path"], artifact["sha256"])

    @staticmethod
    def _plan_matches(record, plan):
        if plan is None or plan.get("metadata", {}).get("contract_type") != "VALIDATION":
            raise IntegrityError("Publish the exact independent milestone Validation plan first.")
        scope = plan["payload"]["validation_scope"]
        if (
            scope["level"] != "PLAYTEST_MILESTONE"
            or scope["target_contract_ref"] != record["origin"]["workflow_ref"]
            or not set(scope["target_ids"]) <= set(record["origin"]["milestone_ids"])
            or plan["payload"]["gate_policy"]["gate"] != "PLAYTEST_READINESS"
        ):
            raise IntegrityError("The Validation plan has another exact milestone target or gate.")

    def require_eligible(self, build_id, connection):
        """Recheck bytes, sources and latest formal proof inside the promotion writer."""
        databases = connection.execute("PRAGMA database_list").fetchall()
        if not connection.in_transaction or not any(
            Path(row[2]) == self.store.database_path for row in databases
        ):
            raise IntegrityError("Build admission requires the matching project transaction.")
        record = self.repository.get("BUILD", build_id, connection=connection)
        origin = record["origin"]
        self._ready(record, connection)
        self._scope(origin["workflow_ref"], origin["milestone_id"], connection)
        self._execution(origin, connection)
        self._manifest(record)
        plans = []
        for plan in self.gates._active_plans(record["project_id"]):
            try:
                self._plan_matches(record, plan)
            except IntegrityError:
                continue
            plans.append(plan)
        if not any(
            origin["milestone_id"] in plan["payload"]["validation_scope"]["target_ids"]
            for plan in plans
        ):
            raise ConflictError("No active exact milestone Validation plan is available.")
        identity = origin["artifact_identity"]
        for plan in plans:
            reference = ContractRef.from_document(plan)
            latest = connection.execute(
                "SELECT state FROM val_runs WHERE plan_revision_id = ? AND artifact_sha256 = ? ORDER BY rowid DESC LIMIT 1",
                (reference.revision_id, digest(identity)),
            ).fetchone()
            if latest is None or latest["state"] != "PUBLISHED":
                raise ConflictError(
                    "The latest exact build Validation run is missing or unfinished."
                )
            gate = RequiredGate(
                reference,
                None,
                "PLAYTEST_READINESS",
                tuple(plan["payload"]["validation_scope"]["target_ids"]),
                ContractRef.from_json(origin["workflow_ref"]),
            )
            if self.gates.consume(gate, identity)["state"] != "SATISFIED":
                raise ConflictError(
                    "The latest exact build Validation proof does not satisfy admission."
                )
        return {
            "build_id": build_id,
            "project_id": record["project_id"],
            **{
                key: origin[key]
                for key in (
                    "artifact_identity",
                    "workflow_ref",
                    "milestone_id",
                    "milestone_ids",
                    "checkpoint_ids",
                    "candidate_root",
                    "manifest_path",
                    "manifest_sha256",
                )
            },
            "record_version": record["version"],
        }
