# SPDX-License-Identifier: MPL-2.0
"""Read independent Validation through the existing Workflow consumer."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from corinthos.contracts import ContractError, ContractRef, ContractStore
from corinthos.report.sources import _ReadView
from corinthos.workflow.verification import RequiredGate, ValidationGateConsumer

_MAX_PROOFS = 24


def workflow_validation(root, connection, item, execution):
    """Project only exact independent results consumed by the bound execution."""
    if execution is None:
        return "NOT_VERIFIED", []
    workflow_ref = ContractRef.from_json(execution["workflow_ref"])
    workflow = ContractStore._lookup(connection, workflow_ref)
    attempts = connection.execute(
        """SELECT a.details, a.checkpoint_id, a.state FROM wf_checkpoints c
           JOIN wf_attempts a ON a.attempt_id = c.attempt_id AND a.execution_id = c.execution_id
             AND a.checkpoint_id = c.checkpoint_id
           WHERE c.execution_id = ? AND a.state IN ('COMPLETED', 'BLOCKED')
           ORDER BY c.checkpoint_id LIMIT ?""",
        (execution["execution_id"], _MAX_PROOFS + 1),
    ).fetchall()
    if workflow is None or len(attempts) > _MAX_PROOFS:
        return "NOT_VERIFIED", []

    store = _ReadView(
        SimpleNamespace(database_path=Path(root).absolute() / ".corinthos" / "state.db"),
        connection,
        datetime.now(UTC),
        item.project_id,
    )
    consumer = ValidationGateConsumer(store)
    results = {}
    blocked = False
    proven_leaves = set()
    checkpoints = {row["checkpoint_id"]: row for row in workflow["payload"]["checkpoints"]}
    leaves = set(checkpoints) - {
        parent for row in checkpoints.values() for parent in row["depends_on"]
    }
    seen = set()
    incomplete = False
    for row in attempts:
        try:
            evidence = json.loads(row["details"])
            artifact_identity = evidence.get("artifact_identity")
            for observed in evidence.get("gates", ()):
                if not observed.get("validation_plan_ref") or not observed.get("result_ref"):
                    incomplete = True
                    continue
                plan_ref = ContractRef.from_json(observed["validation_plan_ref"])
                result_ref = ContractRef.from_json(observed["result_ref"])
                key = (row["checkpoint_id"], plan_ref, result_ref)
                seen.add(key)
                if len(seen) > _MAX_PROOFS:
                    return "NOT_VERIFIED", []
                plan = store.get(plan_ref)
                if plan is None or plan_ref.project_id != item.project_id or not artifact_identity:
                    return "NOT_VERIFIED", []
                target = ContractRef.from_json(
                    plan["payload"]["validation_scope"]["target_contract_ref"]
                )
                required = RequiredGate(
                    plan_ref, result_ref, observed["gate"], tuple(observed["scope"]), target
                )
                checked = consumer.consume(required, artifact_identity)
                blocked |= checked["state"] == "BLOCKED"
                incomplete |= checked["state"] != "SATISFIED"
                if checked["state"] == "SATISFIED":
                    results[result_ref] = result_ref.to_json()
                    if row["state"] == "COMPLETED" and row["checkpoint_id"] in leaves:
                        if (
                            target == workflow_ref
                            and plan["payload"]["validation_scope"]["level"] == "CHECKPOINT"
                            and observed["gate"] == "CHECKPOINT"
                            and observed["scope"] == [row["checkpoint_id"]]
                        ):
                            proven_leaves.add(row["checkpoint_id"])
                        elif (
                            item.scope_level != "CRITICAL"
                            and target.to_json() == workflow["payload"]["project_contract_ref"]
                            and observed["gate"] == "PRODUCT_VALIDATION"
                        ):
                            proven_leaves.add(row["checkpoint_id"])
        except (ContractError, KeyError, TypeError, ValueError, OSError, AttributeError):
            return "NOT_VERIFIED", []

    if blocked:
        return "BLOCKED", list(results.values())
    if execution["state"] != "COMPLETED" or incomplete or not results or leaves - proven_leaves:
        return "NOT_VERIFIED", list(results.values())
    return "VERIFIED", list(results.values())
