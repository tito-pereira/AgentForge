# SPDX-License-Identifier: MPL-2.0
"""Sequential, fenced checkpoint execution with real preliminary engineering evidence."""

import json
import math
import os
import threading
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from corinthos.adapters import ContextInput
from corinthos.contracts import ConflictError, ContractRef, ContractStore, IntegrityError
from corinthos.contracts.model import ID_PATTERN, canonical_json

from .execution_repository import CurrentAuditBlocked, ExecutionRepository, PrerequisiteAuditBlocked
from .reconciliation import RevisionReconciler
from .verification import (
    AuditExpectation,
    CheckpointSpec,
    CommandCheck,
    RequiredGate,
    TechnicalReview,
    ValidationGateConsumer,
    command_check,
    relative_path,
    safe_workspace_path,
    workspace_snapshot,
    write_artifact,
)


def _reference(value):
    return value if isinstance(value, ContractRef) else ContractRef.from_json(value)


def _permitted(path, allowed):
    return any(path == item or path.startswith(item + "/") for item in allowed)


class _Heartbeat:
    def __init__(self, runner, attempt, workflow_ref, external_cancel):
        self.runner, self.attempt, self.workflow_ref = runner, attempt, workflow_ref
        self.external_cancel = external_cancel
        self.cancel = threading.Event()
        self.stop = threading.Event()
        self.reason = None
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self):
        elapsed = 0.0
        while not self.stop.wait(0.1):
            if self.external_cancel is not None and self.external_cancel.is_set():
                self.cancel.set()
            elapsed += 0.1
            if elapsed < 10:
                continue
            elapsed = 0
            try:
                self.runner.repository.renew(
                    self.attempt["attempt_id"],
                    self.attempt["fence"],
                    owner_id=self.runner.owner_id,
                    ttl=60,
                )
                if not self.runner.reconciler.inspect(self.workflow_ref)["current"]:
                    self.reason = "ACTIVE_PLAN_CHANGED"
                    self.cancel.set()
            except (ValueError, OSError):
                self.reason = "LEASE_OR_PLAN_CHECK_FAILED"
                self.cancel.set()

    def __enter__(self):
        if self.external_cancel is not None and self.external_cancel.is_set():
            self.cancel.set()
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=2)


class WorkflowRunner:
    """Execute one explicitly requested ready checkpoint; uncertain work needs recovery."""

    def __init__(self, project_root, adapters, *, reviewer, repository=None, auditor=None):
        original = Path(project_root).absolute()
        self.root = original.resolve(strict=True)
        if original != self.root or not self.root.is_dir():
            raise IntegrityError("Execution requires an authorized ordinary project directory.")
        self.store = ContractStore(self.root)
        self.repository = repository if repository is not None else ExecutionRepository(self.store)
        if self.repository.store.database_path != self.store.database_path:
            raise IntegrityError("Execution state must share the project's ContractStore.")
        if adapters.store is None or adapters.store.database_path != self.store.database_path:
            raise IntegrityError("Task adapters must use the same approved project ContractStore.")
        if not callable(reviewer):
            raise IntegrityError(
                "Execution requires an explicit trusted technical review callback."
            )
        if auditor is not None and not callable(auditor):
            raise IntegrityError("An audit request handler must be a trusted callable.")
        self.adapters, self.reviewer = adapters, reviewer
        self.auditor = auditor
        self.reconciler = RevisionReconciler(self.store)
        self.gates = ValidationGateConsumer(self.store)
        self.owner_id = "runner-" + uuid4().hex

    def _workflow(self, reference):
        reference = _reference(reference)
        document = self.store.get(reference)
        if reference.contract_type != "WORKFLOW" or document is None:
            raise IntegrityError("Execution requires an exact published Workflow Contract.")
        if not self.reconciler.inspect(reference)["current"]:
            raise ConflictError("The approved execution plan changed. Reconcile before dispatch.")
        return document

    def prepare_bindings(self, workflow_ref, specs):
        reference = _reference(workflow_ref)
        workflow = self._workflow(reference)
        checkpoints = {item["checkpoint_id"]: item for item in workflow["payload"]["checkpoints"]}
        if not isinstance(specs, (list, tuple)) or not all(
            isinstance(item, CheckpointSpec) for item in specs
        ):
            raise IntegrityError("Provide explicit checkpoint verification specifications.")
        if any(
            not isinstance(item.checkpoint_id, str) or not ID_PATTERN.fullmatch(item.checkpoint_id)
            for item in specs
        ):
            raise IntegrityError("Execution specifications require valid checkpoint identifiers.")
        if (
            len({item.checkpoint_id for item in specs}) != len(specs)
            or {item.checkpoint_id for item in specs} != checkpoints.keys()
        ):
            raise IntegrityError("Configure every approved checkpoint exactly once.")
        bindings = {"workspace": str(self.root), "checkpoints": {}}
        targets = {
            reference,
            ContractRef.from_json(workflow["payload"]["project_contract_ref"]),
            *(
                ContractRef.from_json(item["module_contract_ref"])
                for item in workflow["payload"]["modules"]
            ),
        }
        for spec in specs:
            checkpoint = checkpoints[spec.checkpoint_id]
            if (
                not isinstance(spec.commands, (list, tuple))
                or not all(isinstance(item, CommandCheck) for item in spec.commands)
                or type(spec.deliverables) is not dict
                or not isinstance(spec.allowed_paths, (list, tuple))
                or not isinstance(spec.review_items, (list, tuple))
                or not all(isinstance(item, str) for item in spec.review_items)
                or not isinstance(spec.required_gates, (list, tuple))
                or not all(isinstance(item, RequiredGate) for item in spec.required_gates)
                or not isinstance(spec.audit_expectations, (list, tuple))
                or not all(isinstance(item, AuditExpectation) for item in spec.audit_expectations)
            ):
                raise IntegrityError(
                    "Execution specifications require structured commands, paths, review items and gates."
                )
            if not spec.commands or not spec.allowed_paths:
                raise IntegrityError(
                    "A checkpoint needs actual automated checks and explicit write boundaries."
                )
            if set(spec.deliverables) != set(checkpoint["deliverables"]):
                raise IntegrityError(
                    "Bind every declared deliverable to actual files without adding scope."
                )
            allowed = [relative_path(item) for item in spec.allowed_paths]
            for paths in spec.deliverables.values():
                if not isinstance(paths, (list, tuple)) or not paths:
                    raise IntegrityError("Every deliverable needs at least one explicit file path.")
                for path in paths:
                    relative_path(path)
                    if not _permitted(path, allowed):
                        raise IntegrityError(
                            "A deliverable is outside the declared write boundary."
                        )
            identifiers, covered = set(), set(spec.review_items)
            for check in spec.commands:
                if (
                    not isinstance(check.check_id, str)
                    or not ID_PATTERN.fullmatch(check.check_id)
                    or check.check_id in identifiers
                ):
                    raise IntegrityError("Automated checks need distinct valid identifiers.")
                identifiers.add(check.check_id)
                if (
                    not isinstance(check.argv, (list, tuple))
                    or not check.argv
                    or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in check.argv)
                ):
                    raise IntegrityError(
                        "Verification commands require explicit nonempty argument lists."
                    )
                if os.name == "nt" and Path(check.argv[0]).suffix.lower() in {
                    ".cmd",
                    ".bat",
                    ".ps1",
                }:
                    raise IntegrityError("Use native executables for verification commands.")
                relative_path(check.cwd, directory=True)
                if (
                    type(check.timeout) not in (int, float)
                    or not math.isfinite(check.timeout)
                    or not 0 < check.timeout <= 3600
                ):
                    raise IntegrityError(
                        "Verification checks need finite time limits of at most one hour."
                    )
                covered.add(check.plan_item)
            if covered != set(checkpoint["verification_plan"]):
                raise IntegrityError(
                    "Bind every exact verification-plan item to checks or explicit technical review."
                )
            for gate in spec.required_gates:
                if (
                    not isinstance(gate.validation_plan_ref, ContractRef)
                    or not isinstance(gate.target_ref, ContractRef)
                    or (
                        gate.result_ref is not None and not isinstance(gate.result_ref, ContractRef)
                    )
                    or not isinstance(gate.scope, (list, tuple))
                    or not all(
                        isinstance(item, str) and ID_PATTERN.fullmatch(item) for item in gate.scope
                    )
                ):
                    raise IntegrityError(
                        "Required gates need typed exact references and bounded scope identifiers."
                    )
                if (
                    gate.validation_plan_ref.contract_type != "VALIDATION"
                    or gate.target_ref not in targets
                    or not gate.scope
                ):
                    raise IntegrityError(
                        "Required gates must identify exact applicable approved targets."
                    )
                if gate.result_ref is not None and (
                    gate.result_ref.contract_type != "VALIDATION_RESULT"
                    or gate.result_ref.project_id != reference.project_id
                ):
                    raise IntegrityError(
                        "A gate result must belong to this project and Validation Result type."
                    )
                if gate.validation_plan_ref.project_id != reference.project_id or gate.gate not in {
                    "CHECKPOINT",
                    "PLAYTEST_READINESS",
                    "PRODUCT_VALIDATION",
                }:
                    raise IntegrityError(
                        "A required Validation gate has an invalid project or gate type."
                    )
                plan = self.store.get(gate.validation_plan_ref)
                if plan is None:
                    level = {
                        "CHECKPOINT": "MODULE"
                        if gate.target_ref.contract_type == "MODULE"
                        else "CHECKPOINT",
                        "PLAYTEST_READINESS": "PLAYTEST_MILESTONE",
                        "PRODUCT_VALIDATION": "PRODUCT",
                    }[gate.gate]
                    expectation = AuditExpectation(level, gate.target_ref, gate.scope)
                else:
                    expectation = AuditExpectation.from_plan(plan)
                if (
                    expectation.gate != gate.gate
                    or expectation.target_ref != gate.target_ref
                    or set(expectation.scope) != set(gate.scope)
                    or not self.gates.scope_allowed(workflow, spec.checkpoint_id, expectation)
                ):
                    raise IntegrityError(
                        "A required gate must cover an exact approved scope at this checkpoint."
                    )
            if len(set(spec.audit_expectations)) != len(spec.audit_expectations) or any(
                not self.gates.scope_allowed(workflow, spec.checkpoint_id, expectation)
                for expectation in spec.audit_expectations
            ):
                raise IntegrityError("Formal audits need distinct scopes due at this checkpoint.")
            bindings["checkpoints"][spec.checkpoint_id] = spec.to_json()
        canonical_json(bindings)
        return bindings

    def configure(self, workflow_ref, specs, *, actor_id, work_item_id=None):
        reference = _reference(workflow_ref)
        bindings = self.prepare_bindings(reference, specs)
        return self.repository.register(
            reference, bindings, actor_id=actor_id, work_item_id=work_item_id
        )

    def audit_request(self, attempt_id):
        """Inspect a retained candidate for a separate independent evaluator."""
        return self.repository.audit_request(attempt_id)

    def _context(self, workflow, checkpoint, spec, execution, source):
        payload = workflow["payload"]
        modules = {item["module_id"]: item for item in payload["modules"]}
        selected, pending = set(), list(checkpoint["module_ids"])
        while pending:
            identifier = pending.pop()
            if identifier not in selected:
                selected.add(identifier)
                pending.extend(modules[identifier]["depends_on"])
        references = tuple(
            ContractRef.from_json(modules[key]["module_contract_ref"])
            for key in modules
            if key in selected
        )
        decisions = tuple(
            dict.fromkeys(
                ContractRef.from_json(item["decision_contract_ref"])
                for item in payload["technology_decisions"]
                if item["module_id"] in selected
            )
        )
        interfaces = tuple(
            canonical_json(
                {
                    "module_id": document["payload"]["module_id"],
                    "provided": document["payload"]["provided_interfaces"],
                    "consumed": document["payload"]["consumed_interfaces"],
                }
            )
            for document in (self.store.get(ref) for ref in references)
        )
        task_id = (
            "task-"
            + sha256(
                (execution["execution_id"] + ":" + checkpoint["checkpoint_id"]).encode()
            ).hexdigest()[:32]
        )
        objective = (
            checkpoint["objective"] + "\nImplement only this checkpoint's approved obligations. "
        )
        objective += (
            "Authorized source write paths: " + canonical_json(list(spec.allowed_paths)) + ". "
        )
        objective += "Preserve existing unrelated work and private Corinthos/Git state. Run meaningful tests and update applicable documentation."
        durable = {
            "source_snapshot": {
                "snapshot_id": source["artifact_identity"]["snapshot_id"],
                "commit_id": source["artifact_identity"].get("commit"),
                "files": source["files"],
            },
            "task_id": task_id,
            "objective": objective,
            "deliverables": checkpoint["deliverables"],
            "verification_plan": checkpoint["verification_plan"],
            "allowed_paths": list(spec.allowed_paths),
        }
        binding = execution["bindings"].get("work_item")
        work_context = ()
        if binding is not None:
            durable["work_item"] = binding
            work_context = ("Exact operational Work Item binding: " + canonical_json(binding),)
        context = ContextInput(
            self.root,
            ContractRef.from_json(payload["project_contract_ref"]),
            objective,
            tuple(checkpoint["deliverables"]),
            tuple(checkpoint["verification_plan"]),
            references,
            decisions,
            ContractRef.from_document(workflow),
            interfaces,
            (
                "Execution uses the exact durable attempt and current approved plan.",
                "Exact local implementation and verification bindings: "
                + canonical_json(spec.to_json()),
                "Observed pre-effect source identity: "
                + canonical_json(source["artifact_identity"]),
                *work_context,
            ),
            task_id,
        )
        return durable, context

    def _negative(self, attempt, state, details):
        try:
            self.repository.observe(
                attempt["attempt_id"], attempt["fence"], owner_id=self.owner_id, details=details
            )
            return self.repository.transition(
                attempt["attempt_id"],
                attempt["fence"],
                state,
                owner_id=self.owner_id,
                details=details,
            )
        except ConflictError:
            return self.repository.get_attempt(attempt["attempt_id"])

    def run_next(self, execution_id, *, provider="codex", timeout=300, cancel=None):
        if (
            not isinstance(provider, str)
            or provider not in {"codex", "claude"}
            or type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 86_400
        ):
            raise IntegrityError(
                "Choose a supported adapter and a finite positive execution timeout."
            )
        execution = self.repository.get(execution_id)
        reference = ContractRef.from_json(execution["workflow_ref"])
        workflow = self._workflow(reference)
        ready = next(
            (
                identifier
                for identifier, row in execution["checkpoints"].items()
                if (
                    row["state"] == "READY"
                    or (row["state"] in {"PENDING", "BLOCKED"} and row["attempt_id"] is None)
                )
                and all(
                    execution["checkpoints"][dependency]["state"] == "COMPLETED"
                    for dependency in row["depends_on"]
                )
            ),
            None,
        )
        if ready is None:
            return None
        spec = CheckpointSpec.from_json(execution["bindings"]["checkpoints"][ready])
        checkpoint = next(
            item for item in workflow["payload"]["checkpoints"] if item["checkpoint_id"] == ready
        )
        source = workspace_snapshot(self.root)
        durable, context = self._context(workflow, checkpoint, spec, execution, source)
        try:
            if execution["checkpoints"][ready]["state"] != "READY":
                execution = self.repository.prepare(
                    execution_id, ready, execution["version"], actor_id=self.owner_id
                )
            attempt = self.repository.claim(
                execution_id,
                ready,
                execution["version"],
                owner_id=self.owner_id,
                provider=provider,
                context=durable,
                ttl=60,
            )
        except PrerequisiteAuditBlocked as blocker:
            self.repository.block(
                execution_id,
                ready,
                execution["version"],
                actor_id=self.owner_id,
                details=blocker.details,
            )
            return None
        context = replace(context, attempt_id=attempt["attempt_id"])
        details = {"cleanup_confirmed": True}
        with _Heartbeat(self, attempt, reference, cancel) as heartbeat:
            try:
                if (
                    workspace_snapshot(self.root) != source
                    or not self.reconciler.inspect(reference)["current"]
                ):
                    return self._negative(
                        attempt,
                        "BLOCKED",
                        {**details, "reason": "SOURCE_OR_PLAN_CHANGED_BEFORE_DISPATCH"},
                    )
                before = write_artifact(
                    self.store,
                    attempt["attempt_id"],
                    "source-before.json",
                    canonical_json(source).encode(),
                )
                self.repository.observe(
                    attempt["attempt_id"],
                    attempt["fence"],
                    owner_id=self.owner_id,
                    details={"source_before": before, "dispatch_intent": "RECORDED_BEFORE_PROCESS"},
                )
                self.repository.require_eligible(execution_id, ready)
                details["cleanup_confirmed"] = False
                result = self.adapters.invoke(
                    provider, context, timeout=timeout, cancel=heartbeat.cancel
                )
                metadata = asdict(result)
                output = metadata.pop("output")
                events = metadata.pop("events")
                details.update(
                    agent=metadata,
                    cleanup_confirmed=result.cleanup_confirmed,
                    agent_output=write_artifact(
                        self.store,
                        attempt["attempt_id"],
                        "agent-output.txt",
                        output.encode("utf-8"),
                    ),
                    agent_events=write_artifact(
                        self.store,
                        attempt["attempt_id"],
                        "agent-events.json",
                        json.dumps(events).encode(),
                    ),
                )
                self.repository.observe(
                    attempt["attempt_id"], attempt["fence"], owner_id=self.owner_id, details=details
                )
                if result.status != "COMPLETED" or not result.cleanup_confirmed:
                    details.update(
                        reason=result.error_kind or "AGENT_DID_NOT_COMPLETE",
                        source_after=self._source_artifact(attempt),
                    )
                    state = (
                        "INTERRUPTED"
                        if result.status in {"TIMEOUT", "CANCELLED", "PROTOCOL_ERROR"}
                        or not result.cleanup_confirmed
                        else "BLOCKED"
                    )
                    return self._negative(attempt, state, details)
                attempt = self.repository.transition(
                    attempt["attempt_id"],
                    attempt["fence"],
                    "VERIFYING",
                    owner_id=self.owner_id,
                    details=details,
                )
                return self._verify(attempt, workflow, checkpoint, spec, source, heartbeat, details)
            except PrerequisiteAuditBlocked as blocker:
                return self._negative(attempt, "BLOCKED", {**details, **blocker.details})
            except (ValueError, OSError, KeyboardInterrupt):
                return self._negative(
                    attempt,
                    "INTERRUPTED",
                    {**details, "reason": "EXECUTION_OR_EVIDENCE_INTERRUPTED"},
                )

    def _source_artifact(self, attempt):
        snapshot = workspace_snapshot(self.root)
        return write_artifact(
            self.store,
            attempt["attempt_id"],
            "source-interrupted.json",
            canonical_json(snapshot).encode(),
        )

    def _verify(self, attempt, workflow, checkpoint, spec, before, heartbeat, details):
        reference = ContractRef.from_document(workflow)
        after = workspace_snapshot(self.root)
        changed = sorted(
            path
            for path in before["files"].keys() | after["files"].keys()
            if before["files"].get(path) != after["files"].get(path)
        )
        details.update(artifact_identity=after["artifact_identity"], changed_paths=changed)
        if any(not _permitted(path, spec.allowed_paths) for path in changed):
            return self._negative(attempt, "BLOCKED", {**details, "reason": "WRITE_SCOPE_EXCEEDED"})
        if heartbeat.cancel.is_set() or not self.reconciler.inspect(reference)["current"]:
            return self._negative(
                attempt,
                "INTERRUPTED",
                {**details, "reason": heartbeat.reason or "CANCELLED_OR_STALE_PLAN"},
            )
        deliverables = {}
        try:
            for declared, paths in spec.deliverables.items():
                items = []
                for relative in paths:
                    path = safe_workspace_path(self.root, relative)
                    if not path.is_file() or relative not in after["files"]:
                        raise IntegrityError(
                            "A declared deliverable is missing or outside source inventory."
                        )
                    items.append({"path": relative, **after["files"][relative]})
                deliverables[declared] = items
        except (ValueError, OSError):
            return self._negative(
                attempt, "BLOCKED", {**details, "reason": "DECLARED_DELIVERABLE_MISSING_OR_UNSAFE"}
            )
        checks = []
        for check in spec.commands:
            result = command_check(
                self.store, self.root, attempt["attempt_id"], check, heartbeat.cancel
            )
            checks.append(result)
            details.update(
                checks=checks,
                deliverables=deliverables,
                cleanup_confirmed=details["cleanup_confirmed"] and result["cleanup_confirmed"],
            )
            self.repository.observe(
                attempt["attempt_id"],
                attempt["fence"],
                owner_id=self.owner_id,
                details={"check": result},
            )
            if result["state"] != "PASSED" or not result["cleanup_confirmed"]:
                return self._negative(
                    attempt,
                    "INTERRUPTED"
                    if not result["cleanup_confirmed"] or heartbeat.cancel.is_set()
                    else "BLOCKED",
                    {**details, "reason": "AUTOMATED_VERIFICATION_FAILED"},
                )
        final = workspace_snapshot(self.root)
        if final != after:
            return self._negative(
                attempt, "BLOCKED", {**details, "reason": "SOURCE_CHANGED_DURING_VERIFICATION"}
            )
        evidence = write_artifact(
            self.store,
            attempt["attempt_id"],
            "source-verified.json",
            canonical_json(final).encode(),
        )
        prior = attempt["previous_attempt_id"]
        retained = ()
        if prior is not None:
            previous = self.repository.get_attempt(prior)
            retained = tuple(
                AuditExpectation.from_json(item)
                for item in previous["details"].get("audit_expectations", ())
            )
        gates, retained, _ = self.gates.requirements(
            reference, checkpoint["checkpoint_id"], spec, retained=retained
        )
        details["source_evidence"] = evidence
        if retained:
            details["audit_expectations"] = [item.to_json() for item in retained]
        self.repository.observe(
            attempt["attempt_id"],
            attempt["fence"],
            owner_id=self.owner_id,
            details={
                "source_evidence": evidence,
                "artifact_identity": final["artifact_identity"],
                "audit_expectations": details.get("audit_expectations", []),
                "cleanup_confirmed": details["cleanup_confirmed"],
            },
        )
        request = {
            "attempt_id": attempt["attempt_id"],
            "checkpoint": checkpoint,
            "workflow_ref": reference.to_json(),
            "workspace": str(self.root),
            "artifact_identity": final["artifact_identity"],
            "changed_paths": changed,
            "deliverables": deliverables,
            "checks": checks,
            "evidence": [evidence],
        }
        review = self.reviewer(request)
        required_criteria = {item["criterion_id"] for item in checkpoint["completion_criteria"]}
        if (
            not isinstance(review, TechnicalReview)
            or type(review.accepted) is not bool
            or not isinstance(review.actor_id, str)
            or not ID_PATTERN.fullmatch(review.actor_id)
            or review.actor_id in {"codex", "claude", attempt["provider"]}
            or not isinstance(review.criterion_ids, (list, tuple))
            or not all(isinstance(item, str) for item in review.criterion_ids)
            or set(review.criterion_ids) != required_criteria
            or review.artifact_identity != final["artifact_identity"]
            or not isinstance(review.findings, (list, tuple))
            or not all(isinstance(item, str) and item.strip() for item in review.findings)
        ):
            return self._negative(
                attempt, "BLOCKED", {**details, "reason": "TECHNICAL_REVIEW_MISSING_OR_MISMATCHED"}
            )
        details["technical_review"] = {
            "actor_id": review.actor_id,
            "accepted": review.accepted,
            "criterion_ids": list(review.criterion_ids),
            "artifact_identity": review.artifact_identity,
            "findings": list(review.findings),
            "origin": "EXPLICIT_PRELIMINARY_ENGINEERING_REVIEW",
        }
        if review.accepted and self.auditor is not None and (gates or retained):
            self.auditor(self.audit_request(attempt["attempt_id"]))

        def observe_gates():
            nonlocal retained
            observations, retained = self.gates.observe(
                reference,
                checkpoint["checkpoint_id"],
                spec,
                final["artifact_identity"],
                retained=retained,
            )
            if retained:
                details["audit_expectations"] = [item.to_json() for item in retained]
            return observations

        observations = observe_gates()
        details["gates"] = observations
        if not review.accepted:
            return self._negative(
                attempt, "BLOCKED", {**details, "reason": "TECHNICAL_REVIEW_REJECTED"}
            )
        if any(gate["state"] != "SATISFIED" for gate in observations):
            return self._negative(
                attempt, "BLOCKED", {**details, "reason": "REQUIRED_VALIDATION_GATE_NOT_SATISFIED"}
            )
        if (
            heartbeat.cancel.is_set()
            or workspace_snapshot(self.root) != final
            or not self.reconciler.inspect(reference)["current"]
        ):
            return self._negative(
                attempt,
                "INTERRUPTED",
                {**details, "reason": "SOURCE_OR_PLAN_CHANGED_BEFORE_COMPLETION"},
            )
        details["reason"] = "PRELIMINARY_CHECKPOINT_OBLIGATIONS_SATISFIED"
        failure = {}

        def completion_guard():
            current_gates = observe_gates()
            details["gates"] = current_gates
            if any(gate["state"] != "SATISFIED" for gate in current_gates):
                failure.update(state="BLOCKED", reason="REQUIRED_VALIDATION_GATE_NOT_SATISFIED")
                raise ConflictError("Required Validation evidence changed before completion.")
            if (
                heartbeat.cancel.is_set()
                or workspace_snapshot(self.root) != final
                or not self.reconciler.inspect(reference)["current"]
            ):
                failure.update(
                    state="INTERRUPTED", reason="SOURCE_OR_PLAN_CHANGED_BEFORE_COMPLETION"
                )
                raise ConflictError("The source or approved plan changed before completion.")
            verified = {"gates": current_gates}
            if current_gates:
                verified.update(
                    reason="FORMAL_CHECKPOINT_GATES_SATISFIED",
                    audit_expectations=[item.to_json() for item in retained],
                )
            return verified

        try:
            return self.repository.transition(
                attempt["attempt_id"],
                attempt["fence"],
                "COMPLETED",
                owner_id=self.owner_id,
                details=details,
                completion_guard=completion_guard,
            )
        except (CurrentAuditBlocked, PrerequisiteAuditBlocked) as blocker:
            return self._negative(attempt, "BLOCKED", {**details, **blocker.details})
        except ConflictError:
            if not failure:
                raise
            return self._negative(
                attempt, failure["state"], {**details, "reason": failure["reason"]}
            )

    def verify_existing(self, attempt_id, *, cancel=None):
        attempt = self.repository.get_attempt(attempt_id)
        if attempt["state"] != "VERIFYING" or attempt["owner_id"] != self.owner_id:
            raise ConflictError(
                "Checks-only recovery requires the current explicitly fenced verification attempt."
            )
        execution = self.repository.get(attempt["execution_id"])
        reference = ContractRef.from_json(execution["workflow_ref"])
        workflow = self._workflow(reference)
        checkpoint = next(
            item
            for item in workflow["payload"]["checkpoints"]
            if item["checkpoint_id"] == attempt["checkpoint_id"]
        )
        spec = CheckpointSpec.from_json(
            execution["bindings"]["checkpoints"][attempt["checkpoint_id"]]
        )
        before = workspace_snapshot(self.root)
        with _Heartbeat(self, attempt, reference, cancel) as heartbeat:
            try:
                return self._verify(
                    attempt,
                    workflow,
                    checkpoint,
                    spec,
                    before,
                    heartbeat,
                    {"cleanup_confirmed": True, "verification_only": True},
                )
            except (ValueError, OSError, KeyboardInterrupt):
                return self._negative(
                    attempt,
                    "INTERRUPTED",
                    {
                        "cleanup_confirmed": False,
                        "verification_only": True,
                        "reason": "VERIFICATION_RECOVERY_INTERRUPTED",
                    },
                )
