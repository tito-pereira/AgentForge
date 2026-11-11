# SPDX-License-Identifier: MPL-2.0
"""Independent audit execution and immutable result derivation."""

import os
import platform
import sqlite3
import stat
import threading
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from corinthos.contracts import AuthorityError, ConflictError, ContractRef, IntegrityError
from corinthos.contracts.artifacts import is_link, private_directory
from corinthos.contracts.model import ID_PATTERN, canonical_json
from corinthos.workflow.reconciliation import RevisionReconciler
from corinthos.workflow.verification import safe_workspace_path, workspace_snapshot, write_artifact

from .procedures import COMPOUND_EVIDENCE, _text, digest, observe_command, validate_binding
from .repository import ValidationRepository

_OUTCOMES = {"CONFORMANT", "NONCONFORMANT", "NOT_VERIFIED"}
_WORKSPACE_LIMIT = 256 * 1024 * 1024


def _now():
    return datetime.now(UTC).isoformat()


def _ref(document):
    return None if document is None else ContractRef.from_document(document)


def _record_results(run, events, plan, status, verify_evidence):
    context = run["context"]
    rows = {
        event["data"]["check_id"]: event["data"]
        for event in events
        if event["kind"] == "CHECK_OBSERVED"
    }
    checks, evidence, findings = [], [], []
    covered, unverified, blockers = [], [], []
    for check in plan["payload"]["verification_matrix"]:
        identifier = check["check_id"]
        row = rows.get(identifier, {})
        outcome = row.get("status", "NOT_VERIFIED")
        refs = row.get("evidence", [])
        rationale = row.get("rationale", "No complete observation was retained for this check.")
        try:
            for item in refs:
                verify_evidence(item["path"], item["sha256"])
        except IntegrityError:
            refs = []
            outcome = "NOT_VERIFIED"
            rationale = "Retained evidence no longer matches the private artifact bytes."
        evidence.extend(refs)
        evidence_ids = [item["evidence_id"] for item in refs]
        mandatory = check["gate_classification"] == "MANDATORY"
        if outcome in {"CONFORMANT", "NONCONFORMANT"}:
            covered.append(identifier)
        if outcome == "NOT_VERIFIED":
            unverified.append(identifier)
        blocking = mandatory and outcome != "CONFORMANT"
        if blocking:
            blockers.append(identifier)
        if outcome in {"NONCONFORMANT", "NOT_VERIFIED"}:
            findings.append(
                {
                    "finding_id": "finding-" + digest(identifier)[:32],
                    "check_id": identifier,
                    "symptom": rationale,
                    "severity": "BLOCKING" if blocking else "ADVISORY",
                    "evidence_ids": evidence_ids,
                    "affected_component_ids": plan["payload"]["validation_scope"]["target_ids"],
                    "blocking": blocking,
                }
            )
        checks.append(
            {
                "check_id": identifier,
                "source_ref": check["source_ref"],
                "verification_method": check["verification_method"],
                "status": outcome,
                "evidence_ids": evidence_ids,
                "rationale": rationale,
                **({"not_applicable_reason": rationale} if outcome is None else {}),
            }
        )
    required = {
        item["check_id"]
        for item in plan["payload"]["verification_matrix"]
        if item["gate_classification"] == "MANDATORY"
    }
    sufficient = required.issubset(covered)
    satisfied = status == "COMPLETED" and sufficient and not blockers
    run_id = run["run_id"]
    return {
        "metadata": {
            "contract_id": "result-" + run_id,
            "revision_id": "result-" + run_id + "-r1",
            "contract_type": "VALIDATION_RESULT",
            "project_id": plan["metadata"]["project_id"],
            "version": 1,
            "schema_version": "1.0",
            "status": "PUBLISHED",
            "created_at": run["finished_at"],
            "supersedes": None,
            "standard_ref": plan["metadata"]["standard_ref"],
            "provenance": {
                "engine": "VALIDATION",
                "actor_id": run["evaluator"],
                "source": "Independent scoped audit with retained operational observations",
            },
            "approval": None,
        },
        "payload": {
            "validation_plan_ref": ContractRef.from_document(plan).to_json(),
            "target_and_execution": {
                "validation_run_id": run_id,
                "trigger": context["trigger"],
                "started_at": run["started_at"],
                "finished_at": run["finished_at"],
                "artifact_identity": context["artifact_identity"],
                "environment": context["environment"],
                "tool_versions": context["tool_versions"],
                "configuration": ["Exact reviewed procedure bindings and isolated candidate copy"],
                "evaluator_ref": run["evaluator"],
                "status": status,
            },
            "check_results": checks,
            "coverage_summary": {
                "covered_check_ids": covered,
                "unverified_check_ids": unverified,
                "sufficient": sufficient,
            },
            "findings": findings,
            "gate_assessment": {
                "gate": plan["payload"]["gate_policy"]["gate"],
                "scope": plan["payload"]["validation_scope"]["level"],
                "state": "SATISFIED" if satisfied else "BLOCKED",
                "blocking_check_ids": blockers,
                "rationale": (
                    "Completed execution and all mandatory scoped checks conform."
                    if satisfied
                    else "Execution or mandatory scoped evidence is incomplete or adverse."
                ),
            },
            "evidence_refs": evidence,
            "revalidation_guidance": (
                []
                if satisfied
                else [
                    "Inspect the affected checks, repair within approved obligations, and resubmit."
                ]
            ),
        },
    }


def _review_observation(reviewer, request):
    if reviewer is None:
        return {"state": "REVIEW_UNAVAILABLE"}
    response = reviewer(request)
    if not isinstance(response, dict) or set(response) != {
        "evaluator",
        "artifact_identity",
        "inspected",
        "status",
        "rationale",
    }:
        return {"state": "REVIEW_MISMATCHED"}
    status = response["status"]
    if (
        response["evaluator"] != request["evaluator"]
        or response["artifact_identity"] != request["artifact_identity"]
        or response["inspected"] != request["paths"]
        or not isinstance(status, str)
        or status not in _OUTCOMES | {"NOT_APPLICABLE"}
        or (status == "NOT_APPLICABLE" and not request["optional"])
    ):
        return {"state": "REVIEW_MISMATCHED"}
    try:
        _text(response["rationale"])
    except IntegrityError:
        return {"state": "REVIEW_MISMATCHED"}
    return {**response, "state": status}


class ValidationRunner:
    """Execute published reviewed bindings against a retained candidate snapshot."""

    def __init__(self, store):
        self.store = store
        self.repository = ValidationRepository(store)

    def _plan(self, plan_ref):
        plan = self.store.get(plan_ref)
        if plan is None or plan_ref.contract_type != "VALIDATION":
            raise IntegrityError("Use an exact published Validation Contract.")
        return plan

    def inspect_plan(self, plan_ref):
        """Display the published plan with its exact reviewed operational bindings."""
        return {
            "plan": self._plan(plan_ref),
            "bindings": self.repository.bindings(plan_ref),
            "method_reviews": self.repository.reviews(plan_ref),
        }

    def inspect_impact(self, plan_ref):
        """Report affected scopes while keeping every earlier observation historical."""
        plan = self._plan(plan_ref)
        refs = self._refs(plan)
        changes = [
            ref.to_json() for ref in refs if _ref(self.store.resolve_active(ref.contract_id)) != ref
        ]
        changed_ids = {ref["contract_id"] for ref in changes}
        affected = [
            row["check_id"]
            for row in plan["payload"]["verification_matrix"]
            if row["source_ref"].get("contract_ref", {}).get("contract_id") in changed_ids
        ]
        reconciler = RevisionReconciler(self.store)
        workflow = [reconciler.inspect(ref) for ref in refs if ref.contract_type == "WORKFLOW"]
        try:
            with self.store._connection() as connection:
                self.repository.require_current(connection, plan_ref)
            current = True
        except IntegrityError:
            current = False
        return {
            "current": current,
            "changed_sources": changes,
            "directly_affected_checks": affected,
            "workflow_impact": workflow,
            "action": (
                "Use the unchanged plan with a fresh run for changed candidate bytes."
                if current
                else "Reconcile the affected scope and publish revised formal bindings."
            ),
            "historical_evidence": "Earlier observations retain their exact source and artifact.",
        }

    def require_requested_scope(self, plan_ref, request):
        """Accept only a plan matching the exact scope requested by Workflow."""
        plan = self._plan(plan_ref)["payload"]["validation_scope"]
        scope = {
            "level": plan["level"],
            "target_ref": plan["target_contract_ref"],
            "scope": sorted(plan["target_ids"]),
        }
        if scope not in request["expectations"] and not any(
            row["validation_plan_ref"] == plan_ref.to_json() for row in request["required_gates"]
        ):
            raise IntegrityError(
                "This Validation plan does not match the retained Workflow request."
            )

    @staticmethod
    def _refs(plan):
        return (
            ContractRef.from_document(plan),
            *(ContractRef.from_json(item) for item in plan["payload"]["source_contract_refs"]),
        )

    def _current(self, plan):
        try:
            with self.store._connection() as connection:
                self.repository.require_current(connection, ContractRef.from_document(plan))
        except IntegrityError:
            return False
        return True

    def _guard(self, plan, candidate, snapshot, connection, run):
        self.repository.require_current(connection, ContractRef.from_document(plan))
        if workspace_snapshot(candidate) != snapshot:
            raise IntegrityError(
                "The exact candidate or an approved source changed during validation."
            )

    @staticmethod
    def _copy(candidate, destination, snapshot):
        if sum(item["size"] for item in snapshot["files"].values()) > _WORKSPACE_LIMIT:
            raise IntegrityError("The candidate exceeds the bounded audit copy size.")
        destination.mkdir(mode=0o700)
        for relative, expected in snapshot["files"].items():
            source = safe_workspace_path(candidate, relative)
            info = source.lstat()
            if is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise IntegrityError("An audited candidate input is not an unlinked regular file.")
            with source.open("rb") as stream:
                if not os.path.samestat(info, os.fstat(stream.fileno())):
                    raise IntegrityError("A candidate input changed while being opened.")
                content = stream.read(expected["size"] + 1)
            if (
                len(content) != expected["size"]
                or sha256(content).hexdigest() != expected["sha256"]
            ):
                raise IntegrityError("A candidate input changed before the isolated copy.")
            output = destination / relative
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with output.open("xb") as stream:
                stream.write(content)
        if workspace_snapshot(destination)["files"] != snapshot["files"]:
            raise IntegrityError(
                "The isolated candidate does not match the retained source manifest."
            )

    def _check(self, run, row, binding, candidate, scratch, snapshot, reviewer, cancel, shared):
        identifier = row["check_id"]
        observation = {}
        command = binding["command"]
        if command is not None:
            command_id = digest(command)
            if command_id in shared:
                original_check, actual = shared[command_id]
                observation["command"] = {**actual, "shared_observation_from": original_check}
            else:
                actual = observe_command(command, candidate, scratch, cancel)
                observation["command"] = actual
                if actual["state"] in {"CONFORMANT", "NONCONFORMANT"}:
                    shared[command_id] = (identifier, actual)
            if not observation["command"]["cleanup_confirmed"]:
                return {
                    "check_id": identifier,
                    "status": "NOT_VERIFIED",
                    "rationale": "Owned process cleanup is unconfirmed. Inspect effects before recovery.",
                    "evidence": [],
                    "cleanup_confirmed": False,
                    "observations": observation,
                }
        paths = binding["review_paths"]
        if paths:
            missing = set(paths) - snapshot["files"].keys()
            request = {
                "check_id": identifier,
                "criterion": row["criterion"],
                "source_ref": row["source_ref"],
                "method": row["verification_method"],
                "scope": run["context"]["scope"],
                "evaluator": run["evaluator"],
                "run_id": run["run_id"],
                "artifact_identity": snapshot["artifact_identity"],
                "candidate_root": str(candidate),
                "paths": {path: snapshot["files"][path] for path in paths if path not in missing},
                "optional": row["gate_classification"] == "OPTIONAL" and command is None,
                "command": observation.get("command"),
            }
            observation["review"] = (
                {"state": "REVIEW_FILES_MISSING"}
                if missing
                else _review_observation(reviewer, request)
            )
        if workspace_snapshot(candidate)["files"] != snapshot["files"]:
            raise IntegrityError("A procedure changed the isolated candidate during evaluation.")
        states = {item["state"] for item in observation.values()}
        if states == {"NOT_APPLICABLE"}:
            status = None
            rationale = observation["review"]["rationale"]
        elif states and states <= {"CONFORMANT", "NONCONFORMANT"}:
            status = "NONCONFORMANT" if "NONCONFORMANT" in states else "CONFORMANT"
            rationale = " ".join(
                item["rationale"]
                if kind == "review"
                else f"The independently specified command observed {item['state']}."
                for kind, item in observation.items()
            )
        else:
            status = "NOT_VERIFIED"
            rationale = "Procedure evidence is incomplete or inadmissible: " + ", ".join(
                sorted(states)
            )
        exact = {
            "check_id": identifier,
            "source_ref": row["source_ref"],
            "artifact_identity": snapshot["artifact_identity"],
            "execution_context": {
                "validation_run_id": run["run_id"],
                "validation_plan_ref": run["plan_ref"],
            },
            "verification_method": row["verification_method"],
            "evaluator_ref": run["evaluator"],
        }
        evidence = []
        kinds = []
        review_observed = observation.get("review", {}).get("state") in (
            _OUTCOMES | {"NOT_APPLICABLE"}
        )
        command_observed = observation.get("command", {}).get("state") in {
            "CONFORMANT",
            "NONCONFORMANT",
        }
        for kind in row["required_evidence"]:
            if kind == "Independent review record" and not review_observed:
                continue
            if kind == COMPOUND_EVIDENCE and not (
                command_observed and review_observed and snapshot["artifact_identity"].get("commit")
            ):
                continue
            kinds.append(kind)
        if len(kinds) != len(row["required_evidence"]):
            status = "NOT_VERIFIED"
            rationale = "The required evidence kind could not be observed on the exact candidate."
        for kind in kinds:
            eid = "evidence-" + digest([run["run_id"], identifier, kind])[:36]
            ref = {**exact, "evidence_kind": kind, "evidence_id": eid}
            envelope = {
                **ref,
                "observed_at": _now(),
                "binding_sha256": digest(binding),
                "observations": observation,
                "status": status,
                "rationale": rationale,
            }
            stored = write_artifact(
                self.store, run["run_id"], eid + ".json", canonical_json(envelope).encode("utf-8")
            )
            evidence.append({**ref, "path": stored["path"], "sha256": stored["sha256"]})
        return {
            "check_id": identifier,
            "status": status,
            "rationale": rationale,
            "evidence": evidence,
            "cleanup_confirmed": observation.get("command", {}).get("cleanup_confirmed", True),
        }

    def run(
        self,
        plan_ref,
        candidate_root,
        *,
        evaluator,
        expected_identity=None,
        reviewer=None,
        previous_run_id=None,
        cancel=None,
    ):
        """Audit an exact candidate and return the published result reference."""
        plan = self._plan(plan_ref)
        if not isinstance(evaluator, str) or not ID_PATTERN.fullmatch(evaluator):
            raise AuthorityError("Identify the independent evaluator with a stable identifier.")
        for ref in self._refs(plan)[1:]:
            if (
                ref.contract_type != "PROJECT"
                and self.store.get(ref)["metadata"]["provenance"]["actor_id"] == evaluator
            ):
                raise AuthorityError(
                    "The evaluator must be separate from implementation publication."
                )
        if not self._current(plan):
            raise IntegrityError("Reconcile the exact Validation plan and sources before auditing.")
        bindings = self.repository.bindings(plan_ref)
        rows = plan["payload"]["verification_matrix"]
        if {row["check_id"] for row in rows} != bindings.keys():
            raise IntegrityError("Published plan and typed procedure bindings differ.")
        candidate = Path(candidate_root).absolute()
        if candidate.resolve(strict=True) != candidate or not candidate.is_dir():
            raise IntegrityError("Use an existing ordinary candidate directory.")
        snapshot = workspace_snapshot(candidate)
        if expected_identity is not None and expected_identity != snapshot["artifact_identity"]:
            raise IntegrityError("The candidate differs from the retained Workflow artifact.")
        cancel = cancel if cancel is not None else threading.Event()
        root = self.store.database_path.parent.parent
        context = {
            "candidate_root": str(candidate),
            "artifact_identity": snapshot["artifact_identity"],
            "trigger": "Inspected revalidation"
            if previous_run_id
            else "Independent requested audit",
            "environment": platform.platform(),
            "tool_versions": [
                f"Python {platform.python_version()}",
                f"SQLite {sqlite3.sqlite_version}",
            ],
            "scope": plan["payload"]["validation_scope"],
        }
        run = self.repository.start(
            plan_ref, context, evaluator=evaluator, previous_run_id=previous_run_id, ttl=120
        )
        owner, run_id = run["owner"], run["run_id"]
        stage = private_directory(root, "snapshots", create=True) / run_id
        status = "COMPLETED"
        requires_inspection = False
        stop = threading.Event()

        def renew():
            while not stop.wait(20):
                try:
                    self.repository.renew(run_id, owner, ttl=120)
                except (ValueError, OSError):
                    cancel.set()
                    return

        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        try:
            stage.mkdir(mode=0o700)
            copy, scratch = stage / "candidate", stage / "scratch"
            scratch.mkdir(mode=0o700)
            self._copy(candidate, copy, snapshot)
            self.repository.observe(
                run_id,
                owner,
                "CANDIDATE_VERIFIED",
                {
                    "snapshot_sha256": digest(snapshot),
                    "copy": str(copy),
                },
            )
            shared = {}
            for row in rows:
                if cancel.is_set():
                    status = "INTERRUPTED"
                    break
                if not self._current(plan) or workspace_snapshot(candidate) != snapshot:
                    raise IntegrityError("An exact source or candidate changed during the audit.")
                identifier = row["check_id"]
                binding = validate_binding(bindings[identifier])
                self.repository.observe(run_id, owner, "CHECK_STARTED", {"check_id": identifier})
                observation = self._check(
                    run, row, binding, copy, scratch, snapshot, reviewer, cancel, shared
                )
                self.repository.observe(run_id, owner, "CHECK_OBSERVED", observation)
                if not observation["cleanup_confirmed"]:
                    requires_inspection = True
                    break
                if workspace_snapshot(candidate) != snapshot or not self._current(plan):
                    raise IntegrityError("An exact source or candidate changed during the check.")
        except KeyboardInterrupt:
            status = "INTERRUPTED"
        except (OSError, ValueError):
            status = "ERROR"
            self.repository.observe(
                run_id,
                owner,
                "AUDIT_STOPPED",
                {"reason": "The candidate, procedure or evidence boundary could not be verified."},
            )
        finally:
            stop.set()
            heartbeat.join()
        if requires_inspection:
            raise ConflictError(
                f"Inspect process cleanup before recovering Validation run {run_id}."
            )
        if cancel.is_set() and status == "COMPLETED":
            status = "INTERRUPTED"

        def guard(connection, current):
            self._guard(plan, candidate, snapshot, connection, current)

        def build(current, events):
            return _record_results(current, events, plan, status, self.store.verify_artifact)

        try:
            return self.repository.finalize(
                run_id, owner, build, guard=guard if status == "COMPLETED" else None
            )
        except IntegrityError:
            if status != "COMPLETED":
                raise
            status = "ERROR"
            self.repository.observe(
                run_id,
                owner,
                "AUDIT_STOPPED",
                {"reason": "Source or candidate freshness changed before finalization."},
            )
            return self.repository.finalize(run_id, owner, build)

    def recover(self, run_id, inspection):
        """Finalize a stopped run as interrupted with its retained observations."""
        run = self.repository.get(run_id)
        plan = self._plan(ContractRef.from_json(run["plan_ref"]))
        self.repository.recover(
            run_id,
            inspection,
            lambda current, events: _record_results(
                current, events, plan, "INTERRUPTED", self.store.verify_artifact
            ),
        )
        return self.repository.publish(run_id)

    def publish_frozen(self, run_id):
        """Reconcile exact frozen publication after checking current eligibility."""
        run = self.repository.get(run_id)
        if run["state"] == "PUBLISHED":
            return self.repository.publish(run_id)
        result = run["frozen_result"]
        if result["payload"]["target_and_execution"]["status"] != "COMPLETED":
            return self.repository.publish(run_id)
        candidate = Path(run["context"]["candidate_root"])
        snapshot = workspace_snapshot(candidate)
        if snapshot["artifact_identity"] != run["context"]["artifact_identity"]:
            raise IntegrityError("The frozen result belongs to a different candidate.")
        plan = self._plan(ContractRef.from_json(run["plan_ref"]))
        return self.repository.publish(
            run_id,
            guard=lambda connection, current: self._guard(
                plan, candidate, snapshot, connection, current
            ),
        )
