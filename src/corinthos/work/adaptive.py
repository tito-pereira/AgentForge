# SPDX-License-Identifier: MPL-2.0
"""Derive Work Item flow and reports without creating another execution owner."""

import json
from dataclasses import asdict

from corinthos.context import ContextService
from corinthos.context.redaction import redact
from corinthos.contracts import ConflictError, ContractRef, ContractStore, IntegrityError
from corinthos.work.model import ScopeLevel, WorkError, WorkStatus
from corinthos.workflow.work_binding import (
    applicable_workflow,
    unbound_work_execution,
    work_execution,
)

from .adaptive_validation import workflow_validation
from .repository import WorkRepository
from .scope import ScopePolicyService
from .service import _WORK_ID, WorkService, _id

_REDUCED = {ScopeLevel.TASK, ScopeLevel.CHANGE}
_TERMINAL = {WorkStatus.COMPLETED, WorkStatus.CANCELLED}
_ACTIVE = {"STARTING", "RUNNING", "CANCELLING"}
_REFERENCE_LIMIT = 12


def _gate(id, state):
    return {"id": id, "state": state}


def _last_session(connection, item):
    row = connection.execute(
        """SELECT session_id, provider, state, run_generation, context_projection_id,
                  cleanup_unconfirmed FROM agent_sessions WHERE project_id = ? AND work_item_id = ?
           ORDER BY created_at DESC, session_id DESC LIMIT 1""",
        (item.project_id, item.work_item_id),
    ).fetchone()
    return dict(row) | {"cleanup_unconfirmed": bool(row["cleanup_unconfirmed"])} if row else None


def _canonical_refs(connection, item, *, select_workflows):
    projects = ContractStore.active_references(connection, item.project_id, "PROJECT", limit=2)
    if len(projects) > 1:
        raise IntegrityError("More than one active Project covers the Work Item.")
    project = projects[0] if projects else None
    if not select_workflows:
        return project, []
    applicable = []
    references = ContractStore.active_references(
        connection, item.project_id, "WORKFLOW", limit=_REFERENCE_LIMIT + 1
    )
    if len(references) <= _REFERENCE_LIMIT:
        for reference in references:
            document = ContractStore._lookup(connection, reference)
            if document is not None and applicable_workflow(connection, document, item):
                applicable.append((reference, document))
    return project, applicable


class AdaptiveWorkflowService:
    """Enforce proportional gates at explicit entry points and inspect exact evidence."""

    def __init__(self, root, supervisor=None):
        self.root = root
        self.supervisor = supervisor
        self.context = ContextService(root)

    def _context_facts(self, connection, item, session):
        repository = self.context.repository
        latest = repository.list_projections(connection, item.work_item_id, limit=1)
        projection = self.context._verify(connection, latest[0]) if latest else None
        handoffs = repository.list_handoffs(connection, work_item_id=item.work_item_id, limit=1)
        handoff = handoffs[0] if handoffs else None
        if handoff is not None:
            from corinthos.context.handoff import verify_handoff

            verify_handoff(handoff)

        continuity = None
        if session and session["context_projection_id"]:
            bound = projection
            if bound is None or bound.projection_id != session["context_projection_id"]:
                bound = self.context._verify(
                    connection, self.context._get(connection, session["context_projection_id"])
                )
            required = bound.canonical_payload.get("required_handoff_id")
            if required is not None:
                origin = repository.get_handoff(connection, required)
                continuity = {
                    "source_session_id": origin.source_session_id,
                    "source_generation": origin.run_generation,
                    "source_provider": origin.provider,
                    "handoff_id": required,
                    "target_session_id": session["session_id"],
                    "target_provider": session["provider"],
                    "projection_id": bound.projection_id,
                }
        return (
            None
            if projection is None
            else {
                "projection_id": projection.projection_id,
                "projection_digest": projection.projection_digest,
            },
            None
            if handoff is None
            else {"handoff_id": handoff.handoff_id, "digest": handoff.digest},
            continuity,
        )

    def _view(self, connection, item, *, evidence=True):
        assessment = ScopePolicyService.assess_item(connection, item)
        selected = item.scope_level
        reduced = selected in _REDUCED
        critical = selected == ScopeLevel.CRITICAL
        terminal = item.status in _TERMINAL
        higher_scope = selected != assessment["effective_flow"]
        session = _last_session(connection, item)
        project, workflows = _canonical_refs(connection, item, select_workflows=not reduced)
        execution = None if reduced else work_execution(connection, item)
        current = execution if execution and execution["binding_current"] else None
        applicable = {ref: doc for ref, doc in workflows}
        if current is not None:
            workflow = ContractRef.from_json(current["workflow_ref"])
        else:
            workflow = workflows[0][0] if len(workflows) == 1 else None
        human = bool(
            workflow in applicable
            and (applicable[workflow]["metadata"]["approval"] or {}).get("kind") == "HUMAN"
        )
        validation, result_refs = (
            workflow_validation(self.root, connection, item, current)
            if evidence
            else ("NOT_VERIFIED", [])
        )
        projection, handoff, continuity = (
            self._context_facts(connection, item, session) if evidence else (None, None, None)
        )
        active_project_session = connection.execute(
            "SELECT work_item_id FROM agent_sessions WHERE state IN ('STARTING','RUNNING','CANCELLING')"
        ).fetchone()
        active_workflow = (
            connection.execute(
                """SELECT 1 FROM wf_workspace_leases l JOIN wf_executions e USING (execution_id)
               WHERE e.project_id = ? AND l.attempt_id IS NOT NULL LIMIT 1""",
                (item.project_id,),
            ).fetchone()
            is not None
        )
        active_session = (
            active_project_session is not None
            and active_project_session["work_item_id"] == item.work_item_id
        )
        blockers, actions = [], []
        gates = [_gate("SCOPE", "BLOCKED" if higher_scope else "SATISFIED")]
        if selected == ScopeLevel.CHANGE:
            unknown_modules = any(module.module_ref is None for module in item.affected_modules)
            gates.append(_gate("AFFECTED_MODULES", "BLOCKED" if unknown_modules else "SATISFIED"))
            if unknown_modules:
                blockers.append("UNRESOLVED_AFFECTED_MODULES")
            open_dependency = any(
                WorkRepository(connection).row(dependency)["status"] != "COMPLETED"
                for dependency in item.dependencies
            )
            gates.append(_gate("DEPENDENCIES", "BLOCKED" if open_dependency else "SATISFIED"))
            if open_dependency:
                blockers.append("OPEN_DEPENDENCIES")
        if not reduced:
            gates.extend(
                (
                    _gate("PROJECT_CONTRACT", "SATISFIED" if project else "REQUIRED"),
                    _gate("WORKFLOW_CONTRACT", "SATISFIED" if workflow else "REQUIRED"),
                    _gate(
                        "WORKFLOW_EXECUTION",
                        "SATISFIED" if current and current["state"] == "COMPLETED" else "REQUIRED",
                    ),
                )
            )
        else:
            gates.extend(
                (
                    _gate("CONTEXT_PROJECTION", "SATISFIED" if projection else "REQUIRED"),
                    _gate(
                        "SESSION_OBSERVATIONS",
                        "SATISFIED" if session and session["state"] not in _ACTIVE else "REQUIRED",
                    ),
                )
            )
        if critical:
            gates.append(_gate("HUMAN_APPROVAL", "SATISFIED" if human else "REQUIRED"))
        gates.append(_gate("VALIDATION", validation))
        if higher_scope:
            blockers.append("MINIMUM_SCOPE_NOT_MET")
        if item.status == WorkStatus.BLOCKED:
            blockers.append("WORK_ITEM_BLOCKED")
        if reduced and not active_session and active_project_session is not None:
            blockers.append("PROJECT_SESSION_ACTIVE")
        if reduced and active_workflow:
            blockers.append("WORKFLOW_ATTEMPT_ACTIVE")
        if not reduced and active_project_session is not None:
            blockers.append("PROJECT_SESSION_ACTIVE")
        if validation == "BLOCKED":
            blockers.append("VALIDATION_BLOCKED")

        can_start = reduced and not terminal and not blockers and not active_session
        can_complete = (
            item.status == WorkStatus.ACTIVE
            and not blockers
            and not active_session
            and validation == "VERIFIED"
            and current is not None
            and current["state"] == "COMPLETED"
            and (not critical or human)
        )
        if terminal:
            stage = "TERMINAL"
        elif higher_scope:
            stage = "BLOCKED_SCOPE"
            actions.append("Set the Work Item to at least its minimum required scope.")
        elif reduced and active_session:
            stage = "EXECUTING"
        elif reduced and blockers:
            stage = "BLOCKED"
        elif not reduced and (workflow is None or project is None or (critical and not human)):
            stage = "PLANNING_REQUIRED"
            actions.append(
                "Use corinthos project and corinthos workflow plan for explicit planning and approval."
            )
        elif not reduced and current is None:
            stage = "WORKFLOW_READY"
            if execution is None:
                existing = unbound_work_execution(connection, item, self.root)
                if existing is None:
                    actions.append(
                        f"Use corinthos workflow configure {workflow.contract_id} --revision {workflow.revision_id} --work-item {item.work_item_id}."
                    )
                elif (
                    existing["workflow_ref"]["contract_id"] == workflow.contract_id
                    and not existing["has_claim"]
                ):
                    actions.append(
                        f"Use corinthos workflow reconcile {existing['execution_id']} {workflow.contract_id} --revision {workflow.revision_id} --work-item {item.work_item_id}."
                    )
                else:
                    actions.append(
                        "Use corinthos workflow executions to inspect the current workspace execution and its lease."
                    )
            else:
                actions.append(
                    f"Use corinthos workflow reconcile {execution['execution_id']} {workflow.contract_id} --revision {workflow.revision_id}."
                )
        elif not reduced and current["state"] != "COMPLETED":
            stage = "EXECUTING" if current["has_claim"] else "WORKFLOW_READY"
            actions.append(
                f"Use corinthos workflow status {current['execution_id']} and the existing checkpoint commands."
            )
        elif blockers:
            stage = "BLOCKED"
        elif can_complete:
            stage = "COMPLETION_READY"
            actions.append("Confirm adaptive completion explicitly.")
        elif (not reduced) or (session is not None):
            stage = "VALIDATION_REQUIRED"
            actions.append("Inspect independent Validation evidence for this exact work.")
            if validation == "VERIFIED" and item.status != WorkStatus.ACTIVE:
                actions.append(
                    "Set the operational Work Item status to ACTIVE before adaptive completion."
                )
        else:
            stage = "READY"
            actions.append("Choose a provider and start an Agent Session.")
        return assessment | {
            "flow_kind": assessment["effective_flow"],
            "stage": stage,
            "gates": gates,
            "blockers": blockers,
            "next_actions": actions,
            "validation_state": validation,
            "validation_policy": item.validation_policy,
            "validation_result_refs": result_refs,
            "project_ref": project.to_json() if project else None,
            "workflow_ref": workflow.to_json() if workflow else None,
            "execution": execution,
            "latest_session": session,
            "latest_projection": projection,
            "latest_handoff": handoff,
            "provider_continuity": continuity,
            "can_start": can_start,
            "can_complete": can_complete,
            "report_status": "BLOCKED" if blockers else validation,
        }

    def status(self, work_item_id):
        _id(work_item_id, "Work Item ID", _WORK_ID)
        with self.context.repository.read() as connection:
            if connection is None:
                raise WorkError("Adaptive Workflow requires an open v9 project.")
            repository = WorkRepository(connection)
            return self._view(connection, repository.item(repository.row(work_item_id)))

    def start(self, work_item_id, provider, **options):
        initial = self.status(work_item_id)
        if not initial["can_start"]:
            raise ConflictError("The selected Work Item is not ready for reduced execution.")

        def check_work(connection):
            repository = WorkRepository(connection)
            item = repository.item(repository.row(work_item_id))
            if (
                item.updated_at != initial["updated_at"]
                or not self._view(connection, item, evidence=False)["can_start"]
            ):
                raise ConflictError("Work Item scope or readiness changed before session creation.")

        self.supervisor.start(self.root, work_item_id, provider, _check_work=check_work, **options)
        return self.status(work_item_id)

    def complete(self, work_item_id, expected_updated_at):
        if not isinstance(expected_updated_at, str) or not expected_updated_at:
            raise WorkError("Adaptive completion requires the current Work Item timestamp.")

        def guard(connection, item):
            if not self._view(connection, item)["can_complete"]:
                raise ConflictError(
                    "The adaptive scope, authority or Validation gates are unsatisfied."
                )

        WorkService(self.root).transition(
            work_item_id, "COMPLETED", expected_updated_at=expected_updated_at, _guard=guard
        )
        return self.status(work_item_id)

    def report(self, work_item_id):
        _id(work_item_id, "Work Item ID", _WORK_ID)
        with self.context.repository.read() as connection:
            if connection is None:
                raise WorkError("Work Item reporting requires an open v9 project.")
            repository = WorkRepository(connection)
            item = repository.item(repository.row(work_item_id))
            flow = self._view(connection, item)
            evidence = _report_refs(connection, item.project_id, flow["validation_result_refs"])
            updates = [
                dict(row) | {"data": json.loads(row["data"])}
                for row in connection.execute(
                    """SELECT actor_id, occurred_at, data FROM lc_events
                       WHERE project_id = ? AND kind = 'WORK_ITEM_SCOPE_CHANGED'
                         AND json_extract(data, '$.work_item_id') = ? ORDER BY sequence DESC LIMIT ?""",
                    (item.project_id, item.work_item_id, _REFERENCE_LIMIT),
                )
            ]
            report, _ = redact(
                {
                    "work_item_id": item.work_item_id,
                    "objective": item.objective,
                    "acceptance_criteria": item.acceptance_criteria,
                    "affected_modules": [asdict(module) for module in item.affected_modules],
                    "dependencies": item.dependencies,
                    "flow": flow,
                    "scope_history": updates,
                    "evidence_report_refs": evidence,
                    "overall_status": flow["report_status"],
                }
            )
            return report


def _report_refs(connection, project_id, validation_refs):
    if not validation_refs:
        return []
    revision_ids = sorted(ref["revision_id"] for ref in validation_refs)
    params = ",".join("?" for _ in revision_ids)
    rows = connection.execute(
        f"""SELECT DISTINCT c.contract_id, r.revision_id FROM contract_references l
           JOIN revisions r ON r.revision_id = l.source_revision_id
           JOIN contracts c ON c.contract_id = r.contract_id
           WHERE l.target_revision_id IN ({params}) AND c.project_id = ?
             AND c.contract_type = 'EVIDENCE_REPORT' ORDER BY r.revision_id LIMIT ?""",
        (*revision_ids, project_id, _REFERENCE_LIMIT),
    )
    return [ContractRef(a, b, "EVIDENCE_REPORT", project_id).to_json() for a, b in rows]
