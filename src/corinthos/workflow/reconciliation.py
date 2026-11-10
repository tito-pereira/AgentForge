# SPDX-License-Identifier: MPL-2.0
"""Inspect exact plan revisions and route evidenced product conflicts to negotiation."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    ContractStore,
    IntegrityError,
    PublishContext,
    validate_schema,
)
from corinthos.contracts.model import ID_PATTERN, canonical_json
from corinthos.project_manager import ProjectManager


def _reference(value) -> ContractRef:
    return value if isinstance(value, ContractRef) else ContractRef.from_json(value)


def _indexed(items, key):
    return {item[key]: item for item in items}


def _changed(previous, current):
    return {
        identifier
        for identifier in previous.keys() | current.keys()
        if previous.get(identifier) != current.get(identifier)
    }


def _downstream(affected, records):
    affected = set(affected)
    while True:
        expanded = affected | {
            identifier
            for identifier, row in records.items()
            if affected.intersection(row["depends_on"])
        }
        if expanded == affected:
            return affected
        affected = expanded


def _union_dependencies(previous, current):
    return {
        identifier: {
            "depends_on": sorted(
                set(previous.get(identifier, {}).get("depends_on", []))
                | set(current.get(identifier, {}).get("depends_on", []))
            )
        }
        for identifier in previous.keys() | current.keys()
    }


def _project_changes(previous, current, modules):
    """Map objective stable-ID changes and conservatively retain global boundaries."""
    if any(
        previous[field] != current[field]
        for field in ("vision", "scope", "constraints", "success_criteria")
    ):
        return set(modules), {
            item["requirement_id"] for item in previous["requirements"] + current["requirements"]
        }
    requirements = _changed(
        _indexed(previous["requirements"], "requirement_id"),
        _indexed(current["requirements"], "requirement_id"),
    )
    affected = {
        identifier
        for identifier, row in modules.items()
        if requirements.intersection(row["requirement_ids"])
    }
    prior_proposals = _indexed(previous["structural_proposals"], "proposal_id")
    current_proposals = _indexed(current["structural_proposals"], "proposal_id")
    proposals = _changed(prior_proposals, current_proposals)
    old_decisions = _indexed(previous["negotiated_decisions"], "decision_id")
    new_decisions = _indexed(current["negotiated_decisions"], "decision_id")
    for identifier in _changed(old_decisions, new_decisions):
        for record in (old_decisions.get(identifier), new_decisions.get(identifier)):
            if record is not None:
                proposals.update(record["proposal_ids"])
    for identifier in proposals:
        linked = [
            record
            for record in (prior_proposals.get(identifier), current_proposals.get(identifier))
            if record
        ]
        requirement_ids = {value for record in linked for value in record["requirement_ids"]}
        constraint_ids = {value for record in linked for value in record["constraint_ids"]}
        if constraint_ids or not requirement_ids:
            affected.update(modules)
        else:
            affected.update(
                key
                for key, row in modules.items()
                if requirement_ids.intersection(row["requirement_ids"])
            )
        requirements.update(requirement_ids)
    return affected, requirements


def _impact(previous, current):
    old_workflow, new_workflow = previous["workflow"]["payload"], current["workflow"]["payload"]
    old_modules = _indexed(old_workflow["modules"], "module_id")
    new_modules = _indexed(new_workflow["modules"], "module_id")
    modules = {**old_modules, **new_modules}
    affected_modules = _changed(old_modules, new_modules)
    old_associations = {identifier: set() for identifier in old_modules}
    new_associations = {identifier: set() for identifier in new_modules}
    for source, associations in (
        (old_workflow, old_associations),
        (new_workflow, new_associations),
    ):
        for row in source["technology_decisions"]:
            associations[row["module_id"]].add(_reference(row["decision_contract_ref"]))
    affected_modules.update(_changed(old_associations, new_associations))
    project_modules, changed_requirements = _project_changes(
        previous["project"]["payload"], current["project"]["payload"], modules
    )
    affected_modules.update(project_modules)
    affected_modules = _downstream(affected_modules, _union_dependencies(old_modules, new_modules))
    old_checkpoints = _indexed(old_workflow["checkpoints"], "checkpoint_id")
    new_checkpoints = _indexed(new_workflow["checkpoints"], "checkpoint_id")
    affected_checkpoints = _changed(old_checkpoints, new_checkpoints)
    for source in (old_checkpoints, new_checkpoints):
        affected_checkpoints.update(
            identifier
            for identifier, row in source.items()
            if affected_modules.intersection(row["module_ids"])
            or changed_requirements.intersection(row["requirement_ids"])
        )
    if old_workflow["execution_policy"] != new_workflow["execution_policy"]:
        affected_checkpoints.update(old_checkpoints.keys() | new_checkpoints.keys())
    old_milestones = _indexed(old_workflow["playtest_milestones"], "milestone_id")
    new_milestones = _indexed(new_workflow["playtest_milestones"], "milestone_id")
    changed_milestones = _changed(old_milestones, new_milestones)
    for source in (old_milestones, new_milestones):
        for identifier in changed_milestones.intersection(source):
            affected_checkpoints.update(source[identifier]["required_checkpoint_ids"])
    affected_checkpoints = _downstream(
        affected_checkpoints, _union_dependencies(old_checkpoints, new_checkpoints)
    )
    changed_milestones.update(
        identifier
        for records in (old_milestones, new_milestones)
        for identifier, row in records.items()
        if affected_checkpoints.intersection(row["required_checkpoint_ids"])
    )
    return {
        "affected_module_ids": sorted(affected_modules),
        "affected_checkpoint_ids": sorted(affected_checkpoints),
        "preserved_module_ids": sorted(
            (old_modules.keys() & new_modules.keys()) - affected_modules
        ),
        "preserved_checkpoint_ids": sorted(
            (old_checkpoints.keys() & new_checkpoints.keys()) - affected_checkpoints
        ),
        "affected_milestone_ids": sorted(
            _downstream(changed_milestones, _union_dependencies(old_milestones, new_milestones))
        ),
        "reasons": [
            "Changed exact module/technology bindings and stable Project obligations propagate through provider and checkpoint dependencies.",
            "Scope, global constraints, success criteria or unscoped decisions conservatively affect the complete plan.",
            "Preservation retains original attempt, contract and artifact identities; it does not relabel historical evidence.",
        ],
    }


class RevisionReconciler:
    """Pure impact reports plus explicit Kernel/Project Manager revision handoffs."""

    def __init__(self, store_or_root):
        self.store = (
            store_or_root
            if isinstance(store_or_root, ContractStore)
            else ContractStore(store_or_root)
        )

    def _read(self, reference, kind=None, project_id=None):
        reference = _reference(reference)
        if (
            kind is not None
            and reference.contract_type != kind
            or project_id is not None
            and reference.project_id != project_id
        ):
            raise IntegrityError("The reconciliation source has an incompatible type or project.")
        document = self.store.get(reference)
        if document is None:
            raise IntegrityError("An exact reconciliation source is unavailable.")
        validate_schema(document)
        return document

    def _plan(self, reference):
        workflow = self._read(reference, "WORKFLOW")
        project_id = workflow["metadata"]["project_id"]
        payload = workflow["payload"]
        project = self._read(payload["project_contract_ref"], "PROJECT", project_id)
        sources = {
            ContractRef.from_document(document): document for document in (workflow, project)
        }
        modules = {}
        for row in payload["modules"]:
            document = self._read(row["module_contract_ref"], "MODULE", project_id)
            if document["payload"]["module_id"] != row["module_id"]:
                raise IntegrityError("A Workflow module does not match its exact source.")
            modules[row["module_id"]] = document
            sources[ContractRef.from_document(document)] = document
        for row in payload["technology_decisions"]:
            document = self._read(row["decision_contract_ref"], "TECHNOLOGY_DECISION", project_id)
            sources[ContractRef.from_document(document)] = document
        # Archived provider references prove the exact consumed terms. The
        # Workflow-selected provider is the active binding checked below.
        for module in modules.values():
            for consumed in module["payload"]["consumed_interfaces"]:
                archived = self._read(consumed["provider_contract_ref"], "MODULE", project_id)
                provider = modules.get(consumed["provider_module_id"])
                if (
                    provider is None
                    or provider["metadata"]["contract_id"] != archived["metadata"]["contract_id"]
                ):
                    raise IntegrityError("A consumer has an inconsistent provider lineage.")
                key = (consumed["interface_id"], consumed["required_interface_revision"])
                definitions = [
                    {
                        (item["interface_id"], item["interface_revision"]): item
                        for item in document["payload"]["provided_interfaces"]
                    }
                    for document in (archived, provider)
                ]
                if key not in definitions[0] or definitions[0][key] != definitions[1].get(key):
                    raise IntegrityError(
                        "The selected provider does not preserve the consumed interface terms."
                    )
        return {"workflow": workflow, "project": project, "modules": modules, "sources": sources}

    def inspect(self, workflow_ref):
        """Detect active-source drift without changing contracts or operational state."""
        plan = self._plan(workflow_ref)
        workflow = plan["workflow"]
        baseline = _impact(plan, plan)
        affected_modules, affected_checkpoints = set(), set()
        changes = []
        expected_refs = sorted(
            plan["sources"], key=lambda item: (item.contract_type, item.contract_id)
        )
        for expected in expected_refs:
            active = self.store.resolve_active(expected.contract_id)
            actual = None if active is None else ContractRef.from_document(active)
            if actual == expected:
                continue
            if actual is not None and (
                actual.project_id != expected.project_id
                or actual.contract_type != expected.contract_type
            ):
                raise IntegrityError("An active reconciliation source has incompatible identity.")
            changes.append(
                {
                    "expected_ref": expected.to_json(),
                    "active_ref": None if actual is None else actual.to_json(),
                }
            )
            if active is None:
                affected_modules.update(plan["modules"])
            elif expected.contract_type == "WORKFLOW":
                impact = _impact(plan, self._plan(actual))
                affected_modules.update(impact["affected_module_ids"])
                affected_checkpoints.update(impact["affected_checkpoint_ids"])
            elif expected.contract_type == "PROJECT":
                rows = _indexed(workflow["payload"]["modules"], "module_id")
                impacted, requirements = _project_changes(
                    plan["project"]["payload"], active["payload"], rows
                )
                affected_modules.update(impacted)
                affected_checkpoints.update(
                    row["checkpoint_id"]
                    for row in workflow["payload"]["checkpoints"]
                    if requirements.intersection(row["requirement_ids"])
                )
            elif expected.contract_type == "MODULE":
                affected_modules.update(
                    identifier
                    for identifier, document in plan["modules"].items()
                    if document["metadata"]["contract_id"] == expected.contract_id
                )
            else:
                affected_modules.update(
                    row["module_id"]
                    for row in workflow["payload"]["technology_decisions"]
                    if _reference(row["decision_contract_ref"]).contract_id == expected.contract_id
                )
        module_rows = _indexed(workflow["payload"]["modules"], "module_id")
        affected_modules = _downstream(affected_modules, module_rows)
        checkpoint_rows = _indexed(workflow["payload"]["checkpoints"], "checkpoint_id")
        affected_checkpoints.update(
            identifier
            for identifier, row in checkpoint_rows.items()
            if affected_modules.intersection(row["module_ids"])
        )
        affected_checkpoints = _downstream(affected_checkpoints, checkpoint_rows)
        milestone_rows = _indexed(workflow["payload"]["playtest_milestones"], "milestone_id")
        affected_milestones = _downstream(
            {
                identifier
                for identifier, row in milestone_rows.items()
                if affected_checkpoints.intersection(row["required_checkpoint_ids"])
            },
            milestone_rows,
        )
        baseline.update(
            current=not changes,
            workflow_ref=ContractRef.from_document(workflow).to_json(),
            source_refs=[reference.to_json() for reference in expected_refs],
            changes=changes,
            affected_module_ids=sorted(affected_modules),
            affected_checkpoint_ids=sorted(affected_checkpoints),
            preserved_module_ids=sorted(module_rows.keys() - affected_modules),
            preserved_checkpoint_ids=sorted(checkpoint_rows.keys() - affected_checkpoints),
            affected_milestone_ids=sorted(affected_milestones),
        )
        return baseline

    def compare(self, previous_workflow_ref, new_workflow_ref):
        """Propose conservative carry-over for a separately approved current plan."""
        previous, current = self._plan(previous_workflow_ref), self._plan(new_workflow_ref)
        before, after = (
            ContractRef.from_document(item["workflow"]) for item in (previous, current)
        )
        if before.contract_id != after.contract_id or before.project_id != after.project_id:
            raise IntegrityError("Reconciliation requires the same project and Workflow lineage.")
        if not self.inspect(after)["current"]:
            raise ConflictError("The replacement Workflow or one of its sources is stale.")
        report = _impact(previous, current)
        report.update(previous_workflow_ref=before.to_json(), new_workflow_ref=after.to_json())
        return report

    def create_revision_request(self, workflow_ref, diagnosis, *, actor_id, request_id=None):
        """Publish only an explicit bounded structural diagnosis, never an automatic bug escalation."""
        plan = self._plan(workflow_ref)
        project = plan["project"]
        for document in (plan["workflow"], project):
            if self.store.resolve_active(document["metadata"]["contract_id"]) != document:
                raise ConflictError(
                    "A structural request requires the current approved Workflow and Project base."
                )
        required = {
            "kind",
            "affected_proposals",
            "inconsistencies",
            "evidence",
            "alternatives",
            "impact",
        }
        if (
            type(diagnosis) is not dict
            or set(diagnosis) != required
            or diagnosis["kind"] != "STRUCTURAL_CONFLICT"
        ):
            raise IntegrityError(
                "A revision request needs an explicit bounded structural-conflict diagnosis."
            )
        diagnosis = deepcopy(diagnosis)
        canonical_json(diagnosis)
        if request_id is None:
            request_id = "request-" + uuid4().hex
        if not isinstance(request_id, str) or not ID_PATTERN.fullmatch(request_id):
            raise IntegrityError("A structural request needs a valid stable request identifier.")
        project_id = project["metadata"]["project_id"]
        contract_id = "revision-request-" + uuid5(NAMESPACE_URL, project_id + "/" + request_id).hex
        payload = {
            "request_id": request_id,
            "project_id": project_id,
            "base_contract_version": ContractRef.from_document(project).to_json(),
            **{key: diagnosis[key] for key in required - {"kind"}},
        }
        document = {
            "metadata": {
                "contract_id": contract_id,
                "revision_id": contract_id + "-r1",
                "contract_type": "PROJECT_REVISION_REQUEST",
                "project_id": project_id,
                "version": 1,
                "schema_version": "1.0",
                "status": "PUBLISHED",
                "created_at": datetime.now(UTC).isoformat(),
                "supersedes": None,
                "standard_ref": deepcopy(project["metadata"]["standard_ref"]),
                "provenance": {
                    "engine": "WORKFLOW",
                    "actor_id": actor_id,
                    "source": "Explicit Workflow structural-conflict diagnosis",
                },
                "approval": None,
            },
            "payload": payload,
        }
        validate_schema(document)
        for evidence in payload["evidence"]:
            source = self._read(evidence["source_ref"], project_id=project_id)
            if not evidence["evidence_ids"] and not evidence["limitations"]:
                raise IntegrityError(
                    "Contract-only structural evidence must state its verification limitations."
                )
            if (
                evidence["evidence_ids"]
                and source["metadata"]["contract_type"] != "VALIDATION_RESULT"
            ):
                raise IntegrityError(
                    "Validation evidence IDs require a real published Validation Result."
                )
        self._request_scope(plan, payload["impact"])
        existing = self.store.get(ContractRef.from_document(document))
        if existing is not None:
            if (
                existing["payload"] != payload
                or existing["metadata"]["provenance"] != document["metadata"]["provenance"]
            ):
                raise ConflictError(
                    "The request identity already records another structural diagnosis."
                )
            return ContractRef.from_document(existing)
        return self.store.publish(document, context=PublishContext("WORKFLOW", actor_id))

    def _request_scope(self, plan, impact):
        workflow = plan["workflow"]["payload"]
        allowed = {
            "module_ids": set(plan["modules"]),
            "checkpoint_ids": {row["checkpoint_id"] for row in workflow["checkpoints"]},
            "milestone_ids": {row["milestone_id"] for row in workflow["playtest_milestones"]},
            "interface_ids": {
                row["interface_id"]
                for document in plan["modules"].values()
                for row in document["payload"]["provided_interfaces"]
            },
        }
        if any(not set(impact[key]) <= values for key, values in allowed.items()):
            raise IntegrityError(
                "A structural request names impact outside its exact engineering plan."
            )
        decisions = {
            _reference(row["decision_contract_ref"]) for row in workflow["technology_decisions"]
        }
        if any(_reference(raw) not in decisions for raw in impact["technology_decision_refs"]):
            raise IntegrityError(
                "A structural request names technology outside its exact engineering plan."
            )

    def negotiate_request(self, request_ref, triage, *, actor_id):
        """Open the real bounded PM intake; the request itself approves no change."""
        reference = _reference(request_ref)
        self._read(reference, "PROJECT_REVISION_REQUEST")
        return ProjectManager(self.store._project_root).receive_prr(
            reference, triage, actor_id=actor_id
        )

    def start_project_revision(self, project_ref, reason, *, actor_id):
        """Route user-initiated changes directly to PM without manufacturing a PRR."""
        reference = _reference(project_ref)
        self._read(reference, "PROJECT")
        return ProjectManager(self.store._project_root).revise(reference, reason, actor_id=actor_id)
