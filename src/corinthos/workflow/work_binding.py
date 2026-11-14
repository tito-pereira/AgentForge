# SPDX-License-Identifier: MPL-2.0
"""Bind operational Work Items to exact approved Workflow executions."""

import json
import os
from hashlib import sha256
from pathlib import Path

from corinthos.contracts import (
    AuthorityError,
    ConflictError,
    ContractRef,
    ContractStore,
    IntegrityError,
    StoreError,
)
from corinthos.contracts.model import canonical_json
from corinthos.work.model import ScopeLevel, WorkStatus
from corinthos.work.repository import WorkRepository
from corinthos.work.service import _WORK_ID, _id

from .verification import AuditExpectation

_PROJECT_SCOPES = {ScopeLevel.PROJECT, ScopeLevel.CRITICAL}
_WORK_TERMINAL = {WorkStatus.COMPLETED, WorkStatus.CANCELLED}
_CHECKPOINT_PAGE = 25


def workspace_key(resolved_workspace: Path):
    """Use the existing Workflow lease identity for an already resolved path."""
    value = str(resolved_workspace)
    return value.casefold() if os.name == "nt" else value


def work_fingerprint(item):
    """Fingerprint work content independently of its status and update time."""
    value = {
        "work_item_id": item.work_item_id,
        "project_id": item.project_id,
        "parent_work_item_id": item.parent_work_item_id,
        "scope_level": item.scope_level.value,
        "objective": item.objective,
        "acceptance_criteria": list(item.acceptance_criteria),
        "validation_policy": item.validation_policy,
        "affected_modules": [
            {
                "module_id": module.module_id,
                "module_ref": module.module_ref.to_json() if module.module_ref else None,
            }
            for module in sorted(item.affected_modules, key=lambda row: row.module_id)
        ],
        "dependencies": sorted(item.dependencies),
    }
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _approval_kind(document):
    approval = document["metadata"]["approval"]
    return approval["kind"] if approval is not None else None


def applicable_workflow(connection, workflow, item):
    """Check current canonical references and exact coverage of Work Item criteria."""
    reference = ContractRef.from_document(workflow)
    if reference.contract_type != "WORKFLOW" or reference.project_id != item.project_id:
        return False
    if ContractStore._active(connection, reference.contract_id) != workflow:
        return False
    payload = workflow["payload"]
    project_ref = ContractRef.from_json(payload["project_contract_ref"])
    project = ContractStore._active(connection, project_ref.contract_id)
    if (
        project is None
        or ContractRef.from_document(project) != project_ref
        or project_ref.contract_type != "PROJECT"
        or project_ref.project_id != reference.project_id
        or _approval_kind(project) != "HUMAN"
    ):
        return False

    modules = {
        row["module_id"]: ContractRef.from_json(row["module_contract_ref"])
        for row in payload["modules"]
    }
    if any(
        expected.module_ref is None or modules.get(expected.module_id) != expected.module_ref
        for expected in item.affected_modules
    ):
        return False
    decisions = {
        ContractRef.from_json(row["decision_contract_ref"])
        for row in payload["technology_decisions"]
    }
    for source in set(modules.values()) | decisions:
        active = ContractStore._active(connection, source.contract_id)
        if (
            source.project_id != reference.project_id
            or active is None
            or ContractRef.from_document(active) != source
        ):
            return False

    affected = {module.module_id for module in item.affected_modules}
    checkpoints = [
        row
        for row in payload["checkpoints"]
        if not affected or affected.intersection(row["module_ids"])
    ]
    if affected - {module for row in checkpoints for module in row["module_ids"]}:
        return False
    covered = {identifier for row in checkpoints for identifier in row["requirement_ids"]}
    if affected:
        covered &= {
            identifier
            for module in payload["modules"]
            if module["module_id"] in affected
            for identifier in module["requirement_ids"]
        }
    requirements = project["payload"]["requirements"]
    if not affected and covered != {row["requirement_id"] for row in requirements}:
        return False
    criteria = {
        criterion["criterion"]
        for row in requirements
        if row["requirement_id"] in covered
        for criterion in row["acceptance_criteria"]
    }
    criteria.update(
        criterion["criterion"] for row in checkpoints for criterion in row["completion_criteria"]
    )
    return set(item.acceptance_criteria) <= criteria


def _binding_for(connection, workflow, work_item_id):
    """Validate a selected owner against current facts in the caller's transaction."""
    _id(work_item_id, "Work Item ID", _WORK_ID)
    repository = WorkRepository(connection)
    item = repository.item(repository.row(work_item_id))
    if item.scope_level not in _PROJECT_SCOPES or item.status in _WORK_TERMINAL:
        raise ConflictError(
            "Workflow execution requires a nonterminal PROJECT or CRITICAL Work Item."
        )
    if item.scope_level is ScopeLevel.CRITICAL and _approval_kind(workflow) != "HUMAN":
        raise AuthorityError("A CRITICAL Work Item requires an explicitly human-approved Workflow.")
    if not applicable_workflow(connection, workflow, item):
        raise ConflictError("The active Workflow does not prove exact coverage for this Work Item.")
    return {
        "work_item_id": work_item_id,
        "content_sha256": work_fingerprint(item),
    }, item.scope_level


def critical_audit_expectations(workflow):
    reference = ContractRef.from_document(workflow)
    checkpoints = workflow["payload"]["checkpoints"]
    prerequisites = {identifier for row in checkpoints for identifier in row["depends_on"]}
    return {
        identifier: AuditExpectation("CHECKPOINT", reference, (identifier,))
        for row in checkpoints
        if (identifier := row["checkpoint_id"]) not in prerequisites
    }


def bind_configuration(connection, workflow, bindings, work_item_id):
    """Add the verified owner and any independent audits required for CRITICAL work."""
    binding, scope = _binding_for(connection, workflow, work_item_id)
    if "work_item" in bindings and bindings["work_item"] != binding:
        raise ConflictError("The Work Item binding differs from the current work content.")
    bindings["work_item"] = binding
    if scope is ScopeLevel.CRITICAL:
        for identifier, expected in critical_audit_expectations(workflow).items():
            recorded = bindings["checkpoints"][identifier].setdefault("audit_expectations", [])
            if not isinstance(recorded, list):
                raise IntegrityError("Audit expectations must be an explicit structured list.")
            expectation = expected.to_json()
            if expectation not in recorded:
                recorded.append(expectation)


def require_current_binding(connection, workflow, bindings):
    """A live bound execution is eligible only for the exact Work Item content."""
    if "work_item" not in bindings:
        return
    binding = bindings["work_item"]
    if type(binding) is not dict or set(binding) != {"work_item_id", "content_sha256"}:
        raise StoreError("Stored Work Item binding is invalid.")
    current, scope = _binding_for(connection, workflow, binding["work_item_id"])
    if binding != current:
        raise ConflictError("The bound Work Item changed. Reconcile before continuing.")
    if scope is ScopeLevel.CRITICAL and not _audits_recorded(workflow, bindings):
        raise IntegrityError("A CRITICAL execution is missing its independent audit scopes.")


def _audits_recorded(workflow, bindings):
    return all(
        expectation.to_json() in bindings["checkpoints"][identifier].get("audit_expectations", ())
        for identifier, expectation in critical_audit_expectations(workflow).items()
    )


def remove_predecessor_critical_audits(bindings, old, new):
    """Discard predecessor CRITICAL expectations that the successor will recalculate."""
    if ContractRef.from_document(old) == ContractRef.from_document(new):
        return
    specifications = bindings.get("checkpoints")
    if not isinstance(specifications, dict):
        return
    for identifier, expected in critical_audit_expectations(old).items():
        specification = specifications.get(identifier)
        audits = (
            specification.get("audit_expectations") if isinstance(specification, dict) else None
        )
        expectation = expected.to_json()
        if isinstance(audits, list) and expectation in audits:
            audits.remove(expectation)
            if not audits:
                del specification["audit_expectations"]


def require_unique_binding(connection, workflow, bindings):
    binding = bindings.get("work_item")
    if binding is None:
        return
    if connection.execute(
        """SELECT 1 FROM wf_executions
           WHERE project_id = ? AND state != 'SUPERSEDED'
             AND json_extract(bindings, '$.work_item.work_item_id') = ? LIMIT 1""",
        (workflow["metadata"]["project_id"], binding["work_item_id"]),
    ).fetchone():
        raise ConflictError("This Work Item already has a current Workflow execution.")


def _bound_rows(connection, item):
    return connection.execute(
        """
        SELECT e.*, l.attempt_id AS claimed_attempt_id
        FROM wf_executions e JOIN wf_workspace_leases l USING(execution_id)
        WHERE e.project_id = ? AND e.workspace = l.workspace AND e.state != 'SUPERSEDED'
          AND json_extract(e.bindings, '$.work_item.work_item_id') = ?
        ORDER BY e.execution_id LIMIT 2
        """,
        (item.project_id, item.work_item_id),
    ).fetchall()


def unbound_work_execution(connection, item, root):
    """Locate only an unbound head in the requested exact project workspace."""
    row = connection.execute(
        """
        SELECT e.execution_id, e.workflow_ref, e.bindings, e.bindings_sha256,
               l.attempt_id AS claimed_attempt_id
        FROM wf_executions e JOIN wf_workspace_leases l USING(execution_id)
        WHERE e.project_id = ? AND e.workspace = ? AND e.workspace = l.workspace
          AND e.state != 'SUPERSEDED' AND json_type(e.bindings, '$.work_item') IS NULL
        """,
        (item.project_id, workspace_key(Path(root).resolve(strict=True))),
    ).fetchone()
    if row is None:
        return None
    if sha256(row["bindings"].encode("utf-8")).hexdigest() != row["bindings_sha256"]:
        raise StoreError("Stored execution bindings have an inconsistent digest.")
    reference = ContractRef.from_json(json.loads(row["workflow_ref"]))
    if (
        reference.contract_type != "WORKFLOW"
        or reference.project_id != item.project_id
        or ContractStore._lookup(connection, reference) is None
    ):
        raise StoreError("The unbound exact Workflow cannot be verified.")
    return {
        "execution_id": row["execution_id"],
        "workflow_ref": reference.to_json(),
        "has_claim": row["claimed_attempt_id"] is not None,
    }


def work_execution(connection, item):
    """Read bounded current workspace-head facts for one explicitly bound Work Item."""
    rows = _bound_rows(connection, item)
    if not rows:
        return None
    if len(rows) != 1:
        raise StoreError("Multiple Workflow executions claim the same Work Item.")
    row = rows[0]
    if sha256(row["bindings"].encode("utf-8")).hexdigest() != row["bindings_sha256"]:
        raise StoreError("Stored execution bindings have an inconsistent digest.")
    bindings = json.loads(row["bindings"])
    binding = bindings["work_item"]
    if type(binding) is not dict or set(binding) != {"work_item_id", "content_sha256"}:
        raise StoreError("Stored Work Item binding is invalid.")
    reference = ContractRef.from_json(json.loads(row["workflow_ref"]))
    workflow = ContractStore._lookup(connection, reference)
    if workflow is None or reference.project_id != item.project_id:
        raise StoreError("The bound exact Workflow cannot be verified.")
    approval = _approval_kind(workflow)
    current = (
        binding["content_sha256"] == work_fingerprint(item)
        and item.scope_level in _PROJECT_SCOPES
        and (
            item.scope_level is not ScopeLevel.CRITICAL
            or (approval == "HUMAN" and _audits_recorded(workflow, bindings))
        )
        and applicable_workflow(connection, workflow, item)
    )
    checkpoints = connection.execute(
        """SELECT checkpoint_id, state, attempt_id, inherited_from FROM wf_checkpoints
           WHERE execution_id = ? ORDER BY checkpoint_id LIMIT ?""",
        (row["execution_id"], _CHECKPOINT_PAGE + 1),
    ).fetchall()
    return {
        "execution_id": row["execution_id"],
        "state": row["state"],
        "version": row["version"],
        "workflow_ref": reference.to_json(),
        "workflow_approval_kind": approval,
        "work_item": binding,
        "binding_current": current,
        "has_claim": row["claimed_attempt_id"] is not None,
        "checkpoints": [
            {
                **dict(checkpoint),
                "inherited_from": json.loads(checkpoint["inherited_from"])
                if checkpoint["inherited_from"] is not None
                else None,
            }
            for checkpoint in checkpoints[:_CHECKPOINT_PAGE]
        ],
        "checkpoints_truncated": len(checkpoints) > _CHECKPOINT_PAGE,
    }
