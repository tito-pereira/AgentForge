# SPDX-License-Identifier: MPL-2.0
"""Durable execution claims, fenced leases and retained observations."""

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from time import time
from uuid import uuid4

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    ContractStore,
    IntegrityError,
    StoreError,
)
from corinthos.contracts.model import ID_PATTERN, canonical_json
from corinthos.contracts.schema import validate_schema

from .reconciliation import RevisionReconciler
from .verification import (
    AuditExpectation,
    CheckpointSpec,
    ValidationGateConsumer,
    _dependency_closure,
    _digest_file,
    safe_workspace_path,
    workspace_snapshot,
)

_MAX_JSON = 1_048_576
_MAX_INTEGER = 9_223_372_036_854_775_807
_CHECKPOINT_STATES = {
    "PENDING",
    "READY",
    "RUNNING",
    "VERIFYING",
    "COMPLETED",
    "BLOCKED",
    "INTERRUPTED",
    "RECOVERING",
}
_ATTEMPT_STATES = {"RUNNING", "VERIFYING", "COMPLETED", "BLOCKED", "INTERRUPTED"}


def _identifier(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise StoreError("Execution operations require valid stable identifiers.")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 20_000:
        raise StoreError("Execution inspection requires bounded nonblank text.")
    return value


def _json(value):
    if type(value) is not dict:
        raise StoreError("Execution context and observations must be JSON objects.")
    serialized = canonical_json(value)
    if len(serialized.encode("utf-8")) > _MAX_JSON:
        raise StoreError(
            "Execution records exceed the 1 MiB limit. Retain large output as artifacts."
        )
    return serialized


def _read(value):
    try:
        result = json.loads(value)
        _json(result)
        return result
    except (ValueError, TypeError, RecursionError):
        raise StoreError("Stored execution state is invalid. Preserve it for recovery.") from None


def _expectations(details):
    return tuple(AuditExpectation.from_json(item) for item in details.get("audit_expectations", ()))


def _inputs_changed(root, inputs):
    try:
        return any(
            _digest_file(safe_workspace_path(root, path)) != expected
            for path, expected in inputs.items()
        )
    except (ValueError, OSError):
        return True


class PrerequisiteAuditBlocked(ConflictError):
    """A historical completion no longer satisfies current downstream eligibility."""

    def __init__(self, checkpoint_id, observations):
        super().__init__(f"Required audit evidence blocks checkpoint prerequisite {checkpoint_id}.")
        self.details = {
            "reason": "PREREQUISITE_VALIDATION_BLOCKED",
            "prerequisite_checkpoint_id": checkpoint_id,
            "gates": observations,
        }


class CurrentAuditBlocked(ConflictError):
    """The owned checkpoint's exact candidate lacks admissible formal proof."""

    def __init__(self, observations):
        super().__init__("Required Validation evidence blocks this checkpoint.")
        self.details = {
            "reason": "REQUIRED_VALIDATION_GATE_NOT_SATISFIED",
            "gates": observations,
        }


class ExecutionRepository:
    """Serialize workspace effects without treating lease expiry as safe retry."""

    def __init__(self, store, *, clock=None):
        if not isinstance(store, ContractStore):
            raise StoreError("Execution persistence requires the existing ContractStore.")
        self.store = store
        self.gates = ValidationGateConsumer(store)
        self._clock = time if clock is None else clock

    def _now(self):
        value = self._clock()
        if type(value) not in (int, float) or not isfinite(value):
            raise StoreError("A valid local execution clock is required.")
        return float(value)

    def _ttl(self, ttl):
        if type(ttl) not in (int, float) or not isfinite(ttl) or not 0 < ttl <= 3600:
            raise StoreError("Use a positive finite lease lifetime of at most one hour.")
        return self._now() + ttl

    @staticmethod
    def _workspace(value, root):
        try:
            original = Path(value).absolute()
            resolved = original.resolve(strict=True)
            if original != resolved or not resolved.is_dir() or not resolved.is_relative_to(root):
                raise ValueError
            key = str(resolved).casefold() if os.name == "nt" else str(resolved)
            return str(resolved), key
        except (ValueError, TypeError, OSError, RuntimeError):
            raise StoreError(
                "Use an existing authorized workspace without path redirection."
            ) from None

    def _fresh(self, connection, reference):
        reference = (
            reference if isinstance(reference, ContractRef) else ContractRef.from_json(reference)
        )
        if reference.contract_type != "WORKFLOW":
            raise IntegrityError("Execution requires an exact published Workflow Contract.")
        workflow = self.store._lookup(connection, reference)
        if workflow is None:
            raise IntegrityError("The exact Workflow Contract is unavailable.")
        validate_schema(workflow)
        payload = workflow["payload"]
        references = [reference, ContractRef.from_json(payload["project_contract_ref"])]
        references.extend(
            ContractRef.from_json(item["module_contract_ref"]) for item in payload["modules"]
        )
        references.extend(
            ContractRef.from_json(item["decision_contract_ref"])
            for item in payload["technology_decisions"]
        )
        for source in references:
            document = self.store._lookup(connection, source)
            active = self.store._active(connection, source.contract_id)
            if (
                source.project_id != reference.project_id
                or document is None
                or active is None
                or ContractRef.from_document(active) != source
            ):
                raise ConflictError(
                    "An approved execution source changed. Reconcile before continuing."
                )
        return workflow

    def require_eligible(self, execution_id, checkpoint_id):
        """Recheck approved sources and required prerequisites before dispatch effects."""
        with self.store._connection() as connection:
            execution = self._row(connection, execution_id)
            self._head(connection, execution)
            checkpoint = self._checkpoint(connection, execution_id, checkpoint_id)
            self._eligible(connection, execution, checkpoint)

    def _bindings(self, workflow, bindings):
        serialized = _json(bindings)
        result = json.loads(serialized)
        checkpoints = {item["checkpoint_id"] for item in workflow["payload"]["checkpoints"]}
        if type(result.get("checkpoints")) is not dict or set(result["checkpoints"]) != checkpoints:
            raise StoreError("Execution bindings must cover exactly the Workflow checkpoints.")
        if any(type(value) is not dict for value in result["checkpoints"].values()):
            raise StoreError("Each checkpoint requires a structured execution binding.")
        workspace, key = self._workspace(
            result.get("workspace"), self.store.database_path.parent.parent
        )
        result["workspace"] = workspace
        serialized = _json(result)
        return key, serialized, sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _row(connection, execution_id):
        _identifier(execution_id)
        row = connection.execute(
            "SELECT * FROM wf_executions WHERE execution_id = ?", (execution_id,)
        ).fetchone()
        if row is None:
            raise StoreError("The execution does not exist.")
        if (
            row["state"] not in {"ACTIVE", "COMPLETED", "BLOCKED", "INTERRUPTED", "SUPERSEDED"}
            or type(row["version"]) is not int
            or not 1 <= row["version"] <= _MAX_INTEGER
        ):
            raise StoreError("Stored execution state is invalid. Preserve it for recovery.")
        return row

    @staticmethod
    def _checkpoint(connection, execution_id, checkpoint_id):
        _identifier(checkpoint_id)
        row = connection.execute(
            "SELECT * FROM wf_checkpoints WHERE execution_id = ? AND checkpoint_id = ?",
            (execution_id, checkpoint_id),
        ).fetchone()
        if row is None or row["state"] not in _CHECKPOINT_STATES:
            raise StoreError("The checkpoint execution state is unavailable or invalid.")
        return row

    @staticmethod
    def _attempt(connection, attempt_id):
        _identifier(attempt_id)
        row = connection.execute(
            "SELECT * FROM wf_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None or row["state"] not in _ATTEMPT_STATES:
            raise StoreError("The execution attempt is unavailable or invalid.")
        return row

    @staticmethod
    def _head(connection, execution):
        lease = connection.execute(
            "SELECT * FROM wf_workspace_leases WHERE workspace = ?", (execution["workspace"],)
        ).fetchone()
        if (
            lease is None
            or lease["execution_id"] != execution["execution_id"]
            or execution["state"] == "SUPERSEDED"
        ):
            raise ConflictError(
                "This execution was superseded. Inspect the active workspace execution."
            )
        return lease

    @staticmethod
    def _version(row, expected):
        if type(expected) is not int or expected < 1 or row["version"] != expected:
            raise ConflictError("Execution state changed. Reload it before continuing.")

    @staticmethod
    def _bump(connection, row, state):
        if row["version"] >= _MAX_INTEGER:
            raise StoreError("The execution version cannot advance further.")
        cursor = connection.execute(
            "UPDATE wf_executions SET version = version + 1, state = ? WHERE execution_id = ? AND version = ?",
            (state, row["execution_id"], row["version"]),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Execution state changed. Reload it before continuing.")
        return row["version"] + 1

    def _event(
        self, connection, execution_id, actor_id, kind, data, *, checkpoint_id=None, attempt_id=None
    ):
        _identifier(actor_id)
        event_id = "event-" + uuid4().hex
        connection.execute(
            "INSERT INTO wf_execution_events (event_id,execution_id,checkpoint_id,attempt_id,actor_id,kind,data,occurred_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                event_id,
                execution_id,
                checkpoint_id,
                attempt_id,
                actor_id,
                kind,
                _json(data),
                datetime.fromtimestamp(self._now(), UTC).isoformat(),
            ),
        )
        return event_id

    def _create(self, connection, workflow, workspace, bindings, digest, actor_id):
        execution_id = "execution-" + uuid4().hex
        reference = ContractRef.from_document(workflow)
        connection.execute(
            "INSERT INTO wf_executions VALUES (?,?,?,?,?,?,?,?,?)",
            (
                execution_id,
                reference.project_id,
                canonical_json(reference.to_json()),
                workspace,
                bindings,
                digest,
                1,
                "ACTIVE",
                datetime.fromtimestamp(self._now(), UTC).isoformat(),
            ),
        )
        connection.executemany(
            "INSERT INTO wf_checkpoints VALUES (?,?,?,NULL,NULL)",
            (
                (execution_id, row["checkpoint_id"], "PENDING")
                for row in workflow["payload"]["checkpoints"]
            ),
        )
        self._event(
            connection,
            execution_id,
            actor_id,
            "EXECUTION_REGISTERED",
            {"workflow_ref": reference.to_json(), "bindings_sha256": digest},
        )
        return execution_id

    def register(self, workflow_ref, bindings, *, actor_id):
        """Register immutable execution configuration or return its current exact match."""
        _identifier(actor_id)
        with self.store._transaction() as connection:
            workflow = self._fresh(connection, workflow_ref)
            workspace, serialized, digest = self._bindings(workflow, bindings)
            lease = connection.execute(
                "SELECT * FROM wf_workspace_leases WHERE workspace = ?", (workspace,)
            ).fetchone()
            if lease is not None:
                existing = self._row(connection, lease["execution_id"])
                if (
                    _read(existing["workflow_ref"]) == ContractRef.from_document(workflow).to_json()
                    and existing["bindings"] == serialized
                ):
                    return self._view(connection, existing)
                raise ConflictError(
                    "The workspace has another execution. Explicit reconciliation is required."
                )
            execution_id = self._create(
                connection, workflow, workspace, serialized, digest, actor_id
            )
            connection.execute(
                "INSERT INTO wf_workspace_leases (workspace,execution_id) VALUES (?,?)",
                (workspace, execution_id),
            )
            return self._view(connection, self._row(connection, execution_id))

    def _view(self, connection, row):
        reference = ContractRef.from_json(_read(row["workflow_ref"]))
        workflow = self.store._lookup(connection, reference)
        bindings = _read(row["bindings"])
        if (
            workflow is None
            or sha256(row["bindings"].encode()).hexdigest() != row["bindings_sha256"]
        ):
            raise StoreError("Stored execution sources or bindings are inconsistent.")
        checkpoints = {}
        plans = {item["checkpoint_id"]: item for item in workflow["payload"]["checkpoints"]}
        for state in connection.execute(
            "SELECT * FROM wf_checkpoints WHERE execution_id = ? ORDER BY checkpoint_id",
            (row["execution_id"],),
        ):
            if state["checkpoint_id"] not in plans or state["state"] not in _CHECKPOINT_STATES:
                raise StoreError("Stored checkpoint execution state is inconsistent.")
            checkpoints[state["checkpoint_id"]] = {
                "checkpoint_id": state["checkpoint_id"],
                "state": state["state"],
                "depends_on": plans[state["checkpoint_id"]]["depends_on"],
                "attempt_id": state["attempt_id"],
                "inherited_from": None
                if state["inherited_from"] is None
                else _read(state["inherited_from"]),
            }
        if checkpoints.keys() != plans.keys():
            raise StoreError("Stored execution omits Workflow checkpoints.")
        lease = connection.execute(
            "SELECT * FROM wf_workspace_leases WHERE workspace = ?", (row["workspace"],)
        ).fetchone()
        return {
            **dict(row),
            "workflow_ref": reference.to_json(),
            "bindings": bindings,
            "checkpoints": checkpoints,
            "active_execution_id": None if lease is None else lease["execution_id"],
            "lease": None
            if lease is None or lease["execution_id"] != row["execution_id"]
            else dict(lease),
        }

    def get(self, execution_id):
        with self.store._connection() as connection:
            return self._view(connection, self._row(connection, execution_id))

    def list(self):
        with self.store._connection() as connection:
            return [
                self._view(connection, row)
                for row in connection.execute("SELECT * FROM wf_executions ORDER BY rowid")
            ]

    def get_attempt(self, attempt_id):
        with self.store._connection() as connection:
            return self._attempt_view(connection, self._attempt(connection, attempt_id))

    @staticmethod
    def _retained_candidate(connection, attempt_id):
        row = connection.execute(
            "SELECT data FROM wf_execution_events WHERE attempt_id = ? "
            "AND kind = 'ATTEMPT_OBSERVATION' "
            "AND json_type(data, '$.source_evidence') = 'object' "
            "ORDER BY sequence DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()
        return _read(row["data"]) if row is not None else {}

    def _source_manifest(self, attempt_id, details):
        evidence = details.get("source_evidence")
        if (
            type(evidence) is not dict
            or evidence.get("path") != f"runtime/{attempt_id}/source-verified.json"
            or not isinstance(evidence.get("sha256"), str)
        ):
            raise ConflictError("The attempt has no safely retained verification candidate.")
        self.store.verify_artifact(evidence["path"], evidence["sha256"])
        path = self.store.database_path.parent / "artifacts" / evidence["path"]
        data = path.read_bytes()
        if sha256(data).hexdigest() != evidence["sha256"]:
            raise IntegrityError("The retained candidate manifest has changed.")
        try:
            manifest = json.loads(data)
        except (ValueError, TypeError, RecursionError):
            raise IntegrityError("The retained candidate manifest is invalid.") from None
        if (
            type(manifest) is not dict
            or manifest.get("artifact_identity") != details.get("artifact_identity")
            or type(manifest.get("files")) is not dict
        ):
            raise IntegrityError("The retained candidate manifest differs from its exact attempt.")
        return manifest

    def audit_request(self, attempt_id):
        """Return the exact still-available candidate for a separate audit process."""
        with self.store._connection() as connection:
            attempt = self._attempt(connection, attempt_id)
            execution = self._row(connection, attempt["execution_id"])
            lease = self._head(connection, execution)
            checkpoint_id = attempt["checkpoint_id"]
            checkpoint = self._checkpoint(connection, execution["execution_id"], checkpoint_id)
            reference = ContractRef.from_json(_read(execution["workflow_ref"]))
            self._fresh(connection, reference)
            if checkpoint["attempt_id"] != attempt_id or not (
                attempt["state"] == "VERIFYING"
                and lease["attempt_id"] == attempt_id
                and lease["fence"] == attempt["fence"]
                and lease["expires_at"] > self._now()
                or attempt["state"] == "BLOCKED"
                and lease["attempt_id"] is None
            ):
                raise ConflictError("Use the current retained verifying or blocked candidate.")
            details = _read(attempt["details"])
            if attempt["state"] == "VERIFYING":
                details.update(self._retained_candidate(connection, attempt_id))
            identity = details.get("artifact_identity")
            if details.get("cleanup_confirmed") is not True or not isinstance(identity, dict):
                raise ConflictError("The attempt has no safely retained verification candidate.")
            bindings = _read(execution["bindings"])
            workspace, _ = self._workspace(
                bindings["workspace"], self.store.database_path.parent.parent
            )
            workspace = Path(workspace)
            spec = CheckpointSpec.from_json(bindings["checkpoints"][checkpoint_id])
        manifest = self._source_manifest(attempt_id, details)
        if workspace_snapshot(workspace) != manifest:
            raise ConflictError("The workspace no longer matches the exact retained candidate.")
        gates, expectations, _ = self.gates.requirements(
            reference, checkpoint_id, spec, retained=_expectations(details)
        )
        return {
            "attempt_id": attempt_id,
            "workflow_ref": reference.to_json(),
            "checkpoint_id": checkpoint_id,
            "workspace": str(workspace),
            "artifact_identity": identity,
            "source_evidence": details["source_evidence"],
            "expectations": [item.to_json() for item in expectations],
            "required_gates": [
                {
                    "validation_plan_ref": gate.validation_plan_ref.to_json(),
                    "result_ref": gate.result_ref.to_json() if gate.result_ref else None,
                    "gate": gate.gate,
                    "scope": list(gate.scope),
                    "target_ref": gate.target_ref.to_json(),
                }
                for gate in gates
            ],
        }

    @staticmethod
    def _attempt_view(connection, row):
        result = {**dict(row), "context": _read(row["context"]), "details": _read(row["details"])}
        lease = connection.execute(
            "SELECT * FROM wf_workspace_leases WHERE attempt_id = ?", (row["attempt_id"],)
        ).fetchone()
        result["expires_at"] = None if lease is None else lease["expires_at"]
        return result

    def history(self, execution_id):
        with self.store._connection() as connection:
            self._row(connection, execution_id)
            return [
                {**dict(row), "data": _read(row["data"])}
                for row in connection.execute(
                    "SELECT * FROM wf_execution_events WHERE execution_id = ? ORDER BY sequence",
                    (execution_id,),
                )
            ]

    def _formal_inputs(self, attempt_id, details, observations):
        """A command can read the whole candidate. Only explicit review paths bound input scope."""
        from corinthos.validation.repository import ValidationRepository

        try:
            files = self._source_manifest(attempt_id, details)["files"]
            paths = {
                item["path"]
                for deliverable in details["deliverables"].values()
                for item in deliverable
            }
            if not paths:
                return None
            repository = ValidationRepository(self.store)
            for observation in observations:
                reference = ContractRef.from_json(observation["validation_plan_ref"])
                for binding in repository.bindings(reference).values():
                    if binding["command"] is not None or not binding["review_paths"]:
                        return None
                    paths.update(binding["review_paths"])
            return {path: files[path] for path in paths}
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            return None

    def _eligible(self, connection, execution, checkpoint):
        workflow = self._fresh(connection, _read(execution["workflow_ref"]))
        plans = {item["checkpoint_id"]: item for item in workflow["payload"]["checkpoints"]}
        identifier = checkpoint["checkpoint_id"]
        if identifier not in plans:
            raise StoreError("The checkpoint does not belong to its recorded Workflow.")
        reference = ContractRef.from_document(workflow)
        bindings = _read(execution["bindings"])
        root = Path(bindings["workspace"])
        current_identity = None
        for dependency in sorted(_dependency_closure(plans, (identifier,)) - {identifier}):
            state = self._checkpoint(connection, execution["execution_id"], dependency)
            if state["state"] != "COMPLETED":
                raise ConflictError("A required checkpoint prerequisite is not completed.")
            spec = bindings["checkpoints"][dependency]
            spec = (
                CheckpointSpec.from_json(spec)
                if spec.get("required_gates") or spec.get("audit_expectations")
                else None
            )
            attempt = (
                self._attempt(connection, state["attempt_id"]) if state["attempt_id"] else None
            )
            details = _read(attempt["details"]) if attempt is not None else {}
            retained = tuple(
                AuditExpectation(item.level, reference, item.scope)
                if item.target_ref.contract_type == "WORKFLOW"
                else item
                for item in _expectations(details)
            )
            gates, _ = self.gates.observe(
                reference, dependency, spec, details.get("artifact_identity"), retained=retained
            )
            if gates:
                inputs = self._formal_inputs(state["attempt_id"], details, gates)
                if inputs is None or _inputs_changed(root, inputs):
                    if current_identity is None:
                        current_identity = workspace_snapshot(root)["artifact_identity"]
                    if current_identity != details.get("artifact_identity"):
                        gates, _ = self.gates.observe(
                            reference, dependency, spec, current_identity, retained=retained
                        )
                        for gate in gates:
                            if gate["state"] != "SATISFIED":
                                gate["reason"] = (
                                    "Prerequisite audit inputs or whole-candidate identity changed. "
                                    + gate["reason"]
                                )
                                gate["artifact_identity"] = current_identity
            if any(gate["state"] != "SATISFIED" for gate in gates):
                raise PrerequisiteAuditBlocked(dependency, gates)
        return workflow

    def _completion_audits(self, connection, execution, attempt, workflow, details):
        bindings = _read(execution["bindings"])
        value = bindings["checkpoints"][attempt["checkpoint_id"]]
        spec = (
            CheckpointSpec.from_json(value)
            if value.get("required_gates") or value.get("audit_expectations")
            else None
        )
        reference = ContractRef.from_document(workflow)
        recorded = self._retained_candidate(connection, attempt["attempt_id"])
        retained = (*_expectations(recorded), *_expectations(details))
        gates, expectations, _ = self.gates.requirements(
            reference, attempt["checkpoint_id"], spec, retained=retained
        )
        if not gates and not expectations:
            return {}
        workspace, _ = self._workspace(
            bindings["workspace"], self.store.database_path.parent.parent
        )
        identity = workspace_snapshot(workspace)["artifact_identity"]
        observed = recorded.get("artifact_identity", details.get("artifact_identity"))
        if observed is not None and observed != identity:
            raise ConflictError("The retained candidate changed before formal completion.")
        observations, expectations = self.gates.observe(
            reference, attempt["checkpoint_id"], spec, identity, retained=expectations
        )
        if any(item["state"] != "SATISFIED" for item in observations):
            raise CurrentAuditBlocked(observations)
        return {
            "gates": observations,
            "reason": "FORMAL_CHECKPOINT_GATES_SATISFIED",
            "artifact_identity": identity,
            "audit_expectations": [item.to_json() for item in expectations],
        }

    def prepare(self, execution_id, checkpoint_id, expected_version, *, actor_id):
        with self.store._transaction() as connection:
            execution = self._row(connection, execution_id)
            self._version(execution, expected_version)
            self._head(connection, execution)
            checkpoint = self._checkpoint(connection, execution_id, checkpoint_id)
            self._eligible(connection, execution, checkpoint)
            if checkpoint["state"] == "READY":
                return self._view(connection, execution)
            if checkpoint["state"] != "PENDING" and not (
                checkpoint["state"] == "BLOCKED" and checkpoint["attempt_id"] is None
            ):
                raise ConflictError("Inspect previous effects before retrying this checkpoint.")
            connection.execute(
                "UPDATE wf_checkpoints SET state = 'READY' WHERE execution_id = ? AND checkpoint_id = ?",
                (execution_id, checkpoint_id),
            )
            self._bump(connection, execution, "ACTIVE")
            self._event(
                connection,
                execution_id,
                actor_id,
                "CHECKPOINT_READY",
                {},
                checkpoint_id=checkpoint_id,
            )
            return self._view(connection, self._row(connection, execution_id))

    def block(self, execution_id, checkpoint_id, expected_version, *, actor_id, details):
        _json(details)
        with self.store._transaction() as connection:
            execution = self._row(connection, execution_id)
            self._version(execution, expected_version)
            lease = self._head(connection, execution)
            checkpoint = self._checkpoint(connection, execution_id, checkpoint_id)
            if lease["attempt_id"] is not None or checkpoint["state"] not in {
                "PENDING",
                "READY",
                "BLOCKED",
            }:
                raise ConflictError(
                    "An active or completed attempt needs its fenced transition or inspection."
                )
            connection.execute(
                "UPDATE wf_checkpoints SET state = 'BLOCKED' WHERE execution_id = ? AND checkpoint_id = ?",
                (execution_id, checkpoint_id),
            )
            self._bump(connection, execution, "BLOCKED")
            self._event(
                connection,
                execution_id,
                actor_id,
                "CHECKPOINT_BLOCKED",
                details,
                checkpoint_id=checkpoint_id,
            )
            return self._view(connection, self._row(connection, execution_id))

    def _context(self, execution, workflow, context):
        result = _read(_json(context))
        source = result.get("source_snapshot")
        if type(source) is not dict or not any(
            isinstance(source.get(key), str) and source[key].strip()
            for key in ("commit_id", "snapshot_id")
        ):
            raise StoreError(
                "Record an observed source commit or snapshot before execution effects."
            )
        expected = {
            "workflow_ref": _read(execution["workflow_ref"]),
            "project_ref": workflow["payload"]["project_contract_ref"],
            "module_refs": [row["module_contract_ref"] for row in workflow["payload"]["modules"]],
            "technology_refs": list(
                {
                    canonical_json(row["decision_contract_ref"]): row["decision_contract_ref"]
                    for row in workflow["payload"]["technology_decisions"]
                }.values()
            ),
            "authorized_workspace": _read(execution["bindings"])["workspace"],
        }
        if any(key in result and result[key] != value for key, value in expected.items()):
            raise IntegrityError("Attempt context cannot replace the exact registered sources.")
        return {**result, **expected}

    def _claim(
        self,
        connection,
        execution,
        checkpoint,
        lease,
        workflow,
        *,
        owner_id,
        provider,
        context,
        ttl,
        state,
    ):
        _identifier(owner_id)
        _identifier(provider)
        expires = self._ttl(ttl)
        if lease["attempt_id"] is not None:
            raise ConflictError(
                "The workspace is claimed. Expiry requires explicit inspection, not automatic retry."
            )
        if lease["fence"] >= _MAX_INTEGER:
            raise StoreError("The workspace fencing counter cannot advance further.")
        attempt_id = "attempt-" + uuid4().hex
        fence = lease["fence"] + 1
        context = self._context(execution, workflow, context)
        version = self._bump(connection, execution, "ACTIVE")
        now = datetime.fromtimestamp(self._now(), UTC).isoformat()
        connection.execute(
            "INSERT INTO wf_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                attempt_id,
                execution["execution_id"],
                checkpoint["checkpoint_id"],
                owner_id,
                fence,
                provider,
                state,
                _json(context),
                "{}",
                checkpoint["attempt_id"],
                version,
                now,
                now,
            ),
        )
        connection.execute(
            "UPDATE wf_checkpoints SET state = ?, attempt_id = ?, inherited_from = NULL WHERE execution_id = ? AND checkpoint_id = ?",
            (state, attempt_id, execution["execution_id"], checkpoint["checkpoint_id"]),
        )
        connection.execute(
            "UPDATE wf_workspace_leases SET attempt_id = ?, owner_id = ?, fence = ?, expires_at = ? WHERE workspace = ?",
            (attempt_id, owner_id, fence, expires, execution["workspace"]),
        )
        self._event(
            connection,
            execution["execution_id"],
            owner_id,
            "ATTEMPT_CLAIMED",
            {
                "provider": provider,
                "fence": fence,
                "expires_at": expires,
                "state": state,
                "context": context,
            },
            checkpoint_id=checkpoint["checkpoint_id"],
            attempt_id=attempt_id,
        )
        return self._attempt_view(connection, self._attempt(connection, attempt_id))

    def claim(
        self, execution_id, checkpoint_id, expected_version, *, owner_id, provider, context, ttl=120
    ):
        with self.store._transaction() as connection:
            execution = self._row(connection, execution_id)
            self._version(execution, expected_version)
            lease = self._head(connection, execution)
            checkpoint = self._checkpoint(connection, execution_id, checkpoint_id)
            workflow = self._eligible(connection, execution, checkpoint)
            self._workspace(
                _read(execution["bindings"])["workspace"], self.store.database_path.parent.parent
            )
            if checkpoint["state"] != "READY":
                raise ConflictError("A checkpoint must be READY before claiming external effects.")
            return self._claim(
                connection,
                execution,
                checkpoint,
                lease,
                workflow,
                owner_id=owner_id,
                provider=provider,
                context=context,
                ttl=ttl,
                state="RUNNING",
            )

    def _owned(self, connection, attempt, fence, owner_id, *, live):
        if type(fence) is not int or attempt["fence"] != fence or attempt["owner_id"] != owner_id:
            raise ConflictError("The attempt belongs to another owner or fencing generation.")
        execution = self._row(connection, attempt["execution_id"])
        lease = self._head(connection, execution)
        if (lease["attempt_id"], lease["owner_id"], lease["fence"]) != (
            attempt["attempt_id"],
            owner_id,
            fence,
        ):
            raise ConflictError(
                "The workspace claim changed. Retain late observations without completing work."
            )
        if live and lease["expires_at"] <= self._now():
            raise ConflictError("The workspace lease expired. Inspect effects before resuming.")
        if live:
            self._fresh(connection, _read(execution["workflow_ref"]))
        return execution, lease

    def renew(self, attempt_id, fence, *, owner_id, ttl=120):
        with self.store._transaction() as connection:
            attempt = self._attempt(connection, attempt_id)
            execution, lease = self._owned(connection, attempt, fence, owner_id, live=True)
            if attempt["state"] not in {"RUNNING", "VERIFYING"}:
                raise ConflictError("Only an active attempt can renew its workspace claim.")
            expires = max(lease["expires_at"], self._ttl(ttl))
            connection.execute(
                "UPDATE wf_workspace_leases SET expires_at = ? WHERE workspace = ?",
                (expires, execution["workspace"]),
            )
            self._event(
                connection,
                execution["execution_id"],
                owner_id,
                "LEASE_RENEWED",
                {"fence": fence, "expires_at": expires},
                checkpoint_id=attempt["checkpoint_id"],
                attempt_id=attempt_id,
            )
            return self._attempt_view(connection, attempt)

    def transition(
        self, attempt_id, fence, target_state, *, owner_id, details, completion_guard=None
    ):
        """Apply a trusted completion guard while holding the database writer reservation."""
        _json(details)
        if not details or target_state not in {"VERIFYING", "COMPLETED", "BLOCKED", "INTERRUPTED"}:
            raise StoreError("Record an explicit observed execution outcome.")
        if completion_guard is not None and (
            target_state != "COMPLETED" or not callable(completion_guard)
        ):
            raise StoreError("A completion guard applies only to the completion transition.")
        with self.store._transaction() as connection:
            attempt = self._attempt(connection, attempt_id)
            if (
                attempt["owner_id"] != owner_id
                or type(fence) is not int
                or attempt["fence"] != fence
            ):
                raise ConflictError("The attempt owner or fencing generation does not match.")
            merged = {**_read(attempt["details"]), **details}
            if attempt["state"] == target_state and _read(attempt["details"]) == merged:
                return self._attempt_view(connection, attempt)
            negative = target_state in {"BLOCKED", "INTERRUPTED"}
            execution, lease = self._owned(connection, attempt, fence, owner_id, live=not negative)
            allowed = {
                "RUNNING": {"VERIFYING", "BLOCKED", "INTERRUPTED"},
                "VERIFYING": {"COMPLETED", "BLOCKED", "INTERRUPTED"},
            }
            if target_state not in allowed.get(attempt["state"], set()):
                raise ConflictError("This attempt transition is not permitted.")
            if completion_guard is not None:
                checked = completion_guard()
                _json(checked)
                details = {**details, **checked}
                merged = {**merged, **checked}
                self._owned(connection, attempt, fence, owner_id, live=True)
            if target_state == "COMPLETED":
                checkpoint = self._checkpoint(
                    connection, execution["execution_id"], attempt["checkpoint_id"]
                )
                workflow = self._eligible(connection, execution, checkpoint)
                verified = self._completion_audits(connection, execution, attempt, workflow, merged)
                details = {**details, **verified}
                merged = {**merged, **verified}
            connection.execute(
                "UPDATE wf_checkpoints SET state = ? WHERE execution_id = ? AND checkpoint_id = ?",
                (target_state, execution["execution_id"], attempt["checkpoint_id"]),
            )
            all_complete = (
                connection.execute(
                    "SELECT 1 FROM wf_checkpoints WHERE execution_id = ? AND state != 'COMPLETED' LIMIT 1",
                    (execution["execution_id"],),
                ).fetchone()
                is None
            )
            state = target_state if negative else ("COMPLETED" if all_complete else "ACTIVE")
            version = self._bump(connection, execution, state)
            connection.execute(
                "UPDATE wf_attempts SET state = ?, details = ?, execution_version = ?, updated_at = ? WHERE attempt_id = ?",
                (
                    target_state,
                    _json(merged),
                    version,
                    datetime.fromtimestamp(self._now(), UTC).isoformat(),
                    attempt_id,
                ),
            )
            if target_state == "COMPLETED" or (
                negative and details.get("cleanup_confirmed") is True
            ):
                connection.execute(
                    "UPDATE wf_workspace_leases SET attempt_id = NULL, owner_id = NULL, expires_at = 0 WHERE workspace = ?",
                    (execution["workspace"],),
                )
            self._event(
                connection,
                execution["execution_id"],
                owner_id,
                "ATTEMPT_" + target_state,
                details,
                checkpoint_id=attempt["checkpoint_id"],
                attempt_id=attempt_id,
            )
            return self._attempt_view(connection, self._attempt(connection, attempt_id))

    def observe(self, attempt_id, fence, *, owner_id, details):
        """Retain late effects without granting a stale process any state authority."""
        with self.store._transaction() as connection:
            attempt = self._attempt(connection, attempt_id)
            if (
                attempt["owner_id"] != owner_id
                or type(fence) is not int
                or attempt["fence"] != fence
            ):
                raise ConflictError("The observation does not identify its original attempt owner.")
            return self._event(
                connection,
                attempt["execution_id"],
                owner_id,
                "ATTEMPT_OBSERVATION",
                details,
                checkpoint_id=attempt["checkpoint_id"],
                attempt_id=attempt_id,
            )

    def recover(
        self,
        execution_id,
        checkpoint_id,
        expected_version,
        *,
        actor_id,
        inspection,
        decision,
        owner_id=None,
        ttl=120,
        context=None,
    ):
        """Require explicit inspection before retry or a verification-only attempt."""
        _json(inspection)
        if (
            inspection.get("process_stopped") is not True
            or inspection.get("effects_inspected") is not True
        ):
            raise ConflictError("Confirm that the process stopped and its effects were inspected.")
        _text(inspection.get("summary"))
        if decision not in {"RETRY", "VERIFY", "BLOCK"}:
            raise StoreError("Choose RETRY, VERIFY or BLOCK after inspection.")
        with self.store._transaction() as connection:
            execution = self._row(connection, execution_id)
            self._version(execution, expected_version)
            lease = self._head(connection, execution)
            checkpoint = self._checkpoint(connection, execution_id, checkpoint_id)
            if checkpoint["attempt_id"] is None or checkpoint["state"] == "COMPLETED":
                raise ConflictError("Recovery requires a previous unfinished checkpoint attempt.")
            attempt = self._attempt(connection, checkpoint["attempt_id"])
            if lease["attempt_id"] not in (None, attempt["attempt_id"]):
                raise ConflictError("Another attempt currently owns this workspace.")
            if lease["fence"] >= _MAX_INTEGER:
                raise StoreError("The workspace fencing counter cannot advance further.")
            workflow = (
                None if decision == "BLOCK" else self._eligible(connection, execution, checkpoint)
            )
            connection.execute(
                "UPDATE wf_checkpoints SET state = 'RECOVERING' WHERE execution_id = ? AND checkpoint_id = ?",
                (execution_id, checkpoint_id),
            )
            self._event(
                connection,
                execution_id,
                actor_id,
                "RECOVERY_STARTED",
                {"from_state": checkpoint["state"], "to_state": "RECOVERING"},
                checkpoint_id=checkpoint_id,
                attempt_id=attempt["attempt_id"],
            )
            connection.execute(
                "UPDATE wf_workspace_leases SET attempt_id = NULL, owner_id = NULL, expires_at = 0, fence = fence + 1 WHERE workspace = ?",
                (execution["workspace"],),
            )
            if attempt["state"] in {"RUNNING", "VERIFYING"}:
                details = {**_read(attempt["details"]), "recovery_inspection": inspection}
                connection.execute(
                    "UPDATE wf_attempts SET state = 'INTERRUPTED', details = ?, updated_at = ? WHERE attempt_id = ?",
                    (
                        _json(details),
                        datetime.fromtimestamp(self._now(), UTC).isoformat(),
                        attempt["attempt_id"],
                    ),
                )
            state = {"VERIFY": "VERIFYING", "RETRY": "READY", "BLOCK": "BLOCKED"}[decision]
            if decision == "VERIFY":
                fresh_lease = self._head(connection, execution)
                self._claim(
                    connection,
                    execution,
                    checkpoint,
                    fresh_lease,
                    workflow,
                    owner_id=owner_id or actor_id,
                    provider="verification",
                    context=context or {},
                    ttl=ttl,
                    state="VERIFYING",
                )
            else:
                connection.execute(
                    "UPDATE wf_checkpoints SET state = ? WHERE execution_id = ? AND checkpoint_id = ?",
                    (state, execution_id, checkpoint_id),
                )
                self._bump(connection, execution, "ACTIVE" if decision == "RETRY" else "BLOCKED")
            self._event(
                connection,
                execution_id,
                actor_id,
                "RECOVERY_INSPECTED",
                {
                    "inspection": inspection,
                    "decision": decision,
                    "old_fence": attempt["fence"],
                    "from_state": "RECOVERING",
                    "to_state": state,
                },
                checkpoint_id=checkpoint_id,
                attempt_id=attempt["attempt_id"],
            )
            return self._view(connection, self._row(connection, execution_id))

    @staticmethod
    def _compatible(connection, store, old, new, identifier, old_bindings, new_bindings):
        old_rows = {item["checkpoint_id"]: item for item in old["payload"]["checkpoints"]}
        new_rows = {item["checkpoint_id"]: item for item in new["payload"]["checkpoints"]}
        pending, checked, modules = [identifier], set(), set()
        while pending:
            key = pending.pop()
            if key in checked:
                continue
            checked.add(key)
            if (
                key not in old_rows
                or old_rows[key] != new_rows.get(key)
                or old_bindings["checkpoints"].get(key) != new_bindings["checkpoints"].get(key)
            ):
                return False
            modules.update(old_rows[key]["module_ids"])
            pending.extend(old_rows[key]["depends_on"])
        for field in ("modules", "technology_decisions"):
            if [row for row in old["payload"][field] if row["module_id"] in modules] != [
                row for row in new["payload"][field] if row["module_id"] in modules
            ]:
                return False
        before = store._lookup(
            connection, ContractRef.from_json(old["payload"]["project_contract_ref"])
        )["payload"]
        after = store._lookup(
            connection, ContractRef.from_json(new["payload"]["project_contract_ref"])
        )["payload"]
        if any(
            before[field] != after[field]
            for field in (
                "vision",
                "scope",
                "constraints",
                "success_criteria",
                "structural_proposals",
                "negotiated_decisions",
            )
        ):
            return False
        required = {
            requirement_id
            for checkpoint_id in checked
            for requirement_id in old_rows[checkpoint_id]["requirement_ids"]
        }
        return [row for row in before["requirements"] if row["requirement_id"] in required] == [
            row for row in after["requirements"] if row["requirement_id"] in required
        ]

    def reconcile(
        self,
        execution_id,
        expected_version,
        new_workflow_ref,
        bindings,
        *,
        actor_id,
        preserve_checkpoint_ids,
        reason,
    ):
        """Activate a successor execution while retaining original evidence identities."""
        _text(reason)
        if not isinstance(preserve_checkpoint_ids, (list, tuple)):
            raise StoreError("Choose distinct checkpoint identifiers for explicit preservation.")
        for checkpoint_id in preserve_checkpoint_ids:
            _identifier(checkpoint_id)
        if len(set(preserve_checkpoint_ids)) != len(preserve_checkpoint_ids):
            raise StoreError("Choose distinct checkpoint identifiers for explicit preservation.")
        with self.store._transaction() as connection:
            execution = self._row(connection, execution_id)
            self._version(execution, expected_version)
            lease = self._head(connection, execution)
            if lease["attempt_id"] is not None:
                raise ConflictError(
                    "Inspect and recover the claimed workspace before reconciliation."
                )
            old = self.store._lookup(
                connection, ContractRef.from_json(_read(execution["workflow_ref"]))
            )
            new = self._fresh(connection, new_workflow_ref)
            if new["metadata"]["contract_id"] != old["metadata"]["contract_id"]:
                raise ConflictError("Reconciliation requires the same logical Workflow lineage.")
            workspace, serialized, digest = self._bindings(new, bindings)
            if (
                workspace != execution["workspace"]
                or new["metadata"]["project_id"] != execution["project_id"]
            ):
                raise ConflictError(
                    "Reconciliation cannot transfer an execution to another project or workspace."
                )
            preserved = set(preserve_checkpoint_ids)
            plans = {row["checkpoint_id"]: row for row in new["payload"]["checkpoints"]}
            if any(
                checkpoint_id in plans and not set(plans[checkpoint_id]["depends_on"]) <= preserved
                for checkpoint_id in preserved
            ):
                raise ConflictError("Preserve the completed prerequisite chain together.")
            for identifier in preserve_checkpoint_ids:
                checkpoint = self._checkpoint(connection, execution_id, identifier)
                if checkpoint["state"] != "COMPLETED" or not self._compatible(
                    connection,
                    self.store,
                    old,
                    new,
                    identifier,
                    _read(execution["bindings"]),
                    _read(serialized),
                ):
                    raise ConflictError(
                        "A carried checkpoint must have demonstrably unchanged sources, obligations and configuration."
                    )
            if preserved:
                impact = RevisionReconciler(self.store).compare(
                    ContractRef.from_document(old), ContractRef.from_document(new)
                )
                if not preserved <= set(impact["preserved_checkpoint_ids"]):
                    raise ConflictError(
                        "A carried checkpoint is affected by approved revision or milestone changes."
                    )
            if lease["fence"] >= _MAX_INTEGER:
                raise StoreError("The workspace fencing counter cannot advance further.")
            successor = self._create(connection, new, workspace, serialized, digest, actor_id)
            for identifier in preserve_checkpoint_ids:
                checkpoint = self._checkpoint(connection, execution_id, identifier)
                inherited = {
                    "execution_id": execution_id,
                    "workflow_ref": _read(execution["workflow_ref"]),
                    "checkpoint_id": identifier,
                    "attempt_id": checkpoint["attempt_id"],
                    "reason": reason,
                }
                connection.execute(
                    "UPDATE wf_checkpoints SET state = 'COMPLETED', attempt_id = ?, inherited_from = ? WHERE execution_id = ? AND checkpoint_id = ?",
                    (checkpoint["attempt_id"], _json(inherited), successor, identifier),
                )
            self._bump(connection, execution, "SUPERSEDED")
            connection.execute(
                "UPDATE wf_workspace_leases SET execution_id = ?, fence = fence + 1 WHERE workspace = ?",
                (successor, workspace),
            )
            self._event(
                connection,
                execution_id,
                actor_id,
                "EXECUTION_SUPERSEDED",
                {"successor_execution_id": successor, "reason": reason},
            )
            self._event(
                connection,
                successor,
                actor_id,
                "EXECUTION_RECONCILED",
                {
                    "previous_execution_id": execution_id,
                    "preserved_checkpoint_ids": list(preserve_checkpoint_ids),
                    "reason": reason,
                },
            )
            return self._view(connection, self._row(connection, successor))
