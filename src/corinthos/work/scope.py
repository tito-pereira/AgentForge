# SPDX-License-Identifier: MPL-2.0
"""Assess structured Work Item scope and record explicit operator decisions."""

from __future__ import annotations

import sqlite3

from corinthos.contracts import ConflictError, ContractRef, ContractStore
from corinthos.contracts.store import _REVISIONS, _stored_document
from corinthos.lifecycle.repository import LifecycleRepository

from .model import ScopeLevel, WorkError, WorkItem
from .repository import WorkRepository
from .service import _WORK_ID, WorkService, _choice, _id, _timestamp

POLICY_VERSION = 1
_ORDER = {scope: rank for rank, scope in enumerate(ScopeLevel)}


def _active_document(connection, project_id, contract_type):
    row = connection.execute(
        _REVISIONS + " WHERE project_id = ? AND contract_type = ? "
        "AND active_revision_id = revision_id",
        (project_id, contract_type),
    ).fetchone()
    return _stored_document(row) if row is not None else None


def _current(connection, reference):
    active = ContractStore._active(connection, reference.contract_id)
    return active is not None and ContractRef.from_document(active) == reference


def _authority_signals(connection, item):
    signals = set()
    known_modules = {
        module.module_id: module.module_ref
        for module in item.affected_modules
        if module.module_ref is not None
    }
    if any(not _current(connection, ref) for ref in known_modules.values()):
        signals.add("AFFECTED_MODULE_REVISION_STALE")
    workflow = _active_document(connection, item.project_id, "WORKFLOW")
    if not workflow or not known_modules:
        return signals
    payload = workflow["payload"]
    matched = {
        module["module_id"]
        for module in payload["modules"]
        if known_modules.get(module["module_id"])
        == ContractRef.from_json(module["module_contract_ref"])
    }
    if matched and not _current(connection, ContractRef.from_json(payload["project_contract_ref"])):
        signals.add("APPLICABLE_WORKFLOW_PROJECT_REVISION_STALE")
    if any(
        decision["module_id"] in matched
        and not _current(connection, ContractRef.from_json(decision["decision_contract_ref"]))
        for decision in payload["technology_decisions"]
    ):
        signals.add("APPLICABLE_WORKFLOW_TECHNOLOGY_REVISION_STALE")
    return signals


def _has_active_session(connection, work_item_id):
    return (
        connection.execute(
            """SELECT 1 FROM agent_sessions WHERE work_item_id = ?
           AND state IN ('STARTING', 'RUNNING', 'CANCELLING') LIMIT 1""",
            (work_item_id,),
        ).fetchone()
        is not None
    )


def _bound_execution(connection, item, *, include_completed):
    return (
        connection.execute(
            """SELECT 1 FROM wf_executions AS execution
           JOIN wf_workspace_leases AS lease USING (execution_id)
           WHERE execution.project_id = ? AND execution.workspace = lease.workspace
             AND execution.state != 'SUPERSEDED'
             AND (? OR execution.state != 'COMPLETED')
             AND json_extract(execution.bindings, '$.work_item.work_item_id') = ? LIMIT 1""",
            (item.project_id, include_completed, item.work_item_id),
        ).fetchone()
        is not None
    )


class ScopePolicyService:
    """Derive a deterministic assessment from exact project owners."""

    def __init__(self, root):
        self.work = WorkService(root)

    @staticmethod
    def assess_item(connection: sqlite3.Connection, item: WorkItem) -> dict:
        signals = _authority_signals(connection, item)
        minimum = ScopeLevel.PROJECT if signals else ScopeLevel.TASK
        unknowns = {"RISK_UNKNOWN"}
        if any(module.module_ref is None for module in item.affected_modules):
            unknowns.add("AFFECTED_MODULE_AUTHORITY_UNKNOWN")
        if len(item.affected_modules) > 1:
            signals.add("MULTIPLE_AFFECTED_MODULES")
        if item.dependencies:
            signals.add("WORK_ITEM_DEPENDENCIES_PRESENT")
        if item.parent_work_item_id is not None:
            signals.add("WORK_ITEM_PARENT_PRESENT")
        recommended = minimum
        if minimum == ScopeLevel.TASK and signals.intersection(
            {"MULTIPLE_AFFECTED_MODULES", "WORK_ITEM_DEPENDENCIES_PRESENT"}
        ):
            recommended = ScopeLevel.CHANGE
        return {
            "work_item_id": item.work_item_id,
            "selected_scope": item.scope_level.value,
            "recommended_scope": recommended.value,
            "minimum_required_scope": minimum.value,
            "signals": sorted(signals),
            "unknowns": sorted(unknowns),
            "downgrade_requires_confirmation": _ORDER[item.scope_level] > _ORDER[minimum],
            "effective_flow": max(item.scope_level, minimum, key=_ORDER.__getitem__).value,
            "policy_version": POLICY_VERSION,
            "updated_at": item.updated_at,
        }

    def assess(self, work_item_id) -> dict:
        _id(work_item_id, "Work Item ID", _WORK_ID)
        with self.work._read() as repository:
            if repository is None:
                raise WorkError("Work Item was not found in this project.")
            return self.assess_item(
                repository.connection, repository.item(repository.row(work_item_id))
            )

    def set(
        self,
        work_item_id,
        scope_level,
        expected_updated_at,
        confirm_downgrade=False,
        *,
        actor_id="local-operator",
    ) -> dict:
        """Apply one explicit scope decision and append its audit in the same transaction."""
        _id(work_item_id, "Work Item ID", _WORK_ID)
        actor = _id(actor_id, "scope decision actor ID")
        desired = _choice(ScopeLevel, scope_level, "Work Item scope")
        if not isinstance(expected_updated_at, str) or type(confirm_downgrade) is not bool:
            raise WorkError(
                "Provide the current Work Item timestamp and an explicit boolean confirmation."
            )
        store = self.work._write_store()
        with store._transaction() as connection:
            repository = WorkRepository(connection)
            row = self.work._mutable(repository, work_item_id, expected_updated_at)
            item = repository.item(row)
            assessment = self.assess_item(connection, item)
            if desired == item.scope_level:
                return assessment
            downgrade = _ORDER[desired] < _ORDER[item.scope_level]
            if downgrade and not confirm_downgrade:
                raise WorkError("A scope downgrade requires explicit confirmation.")
            if downgrade and _ORDER[desired] < _ORDER[assessment["minimum_required_scope"]]:
                raise WorkError("The scope is below the structurally required minimum.")
            if downgrade and _has_active_session(connection, work_item_id):
                raise ConflictError(
                    "Stop the active Agent Session before downgrading its Work Item."
                )
            if _bound_execution(connection, item, include_completed=downgrade):
                raise ConflictError("Reconcile the bound Workflow execution before changing scope.")
            updated_at = _timestamp(item.updated_at)
            repository.save_scope(work_item_id, desired, updated_at)
            LifecycleRepository(store).event(
                item.project_id,
                "WORK_ITEM_SCOPE_CHANGED",
                {
                    "work_item_id": work_item_id,
                    "old_scope": item.scope_level.value,
                    "new_scope": desired.value,
                    "updated_at": updated_at,
                    "policy_version": POLICY_VERSION,
                    "confirm_downgrade": confirm_downgrade,
                },
                connection=connection,
                actor_id=actor,
            )
            return self.assess_item(connection, repository.item(repository.row(work_item_id)))
