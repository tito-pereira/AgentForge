# SPDX-License-Identifier: MPL-2.0
"""Contextual publication checks for the eight structurally valid contracts."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from graphlib import CycleError, TopologicalSorter
from typing import Any

from .model import ConflictError, ContractRef, IntegrityError, iter_references

type Document = dict[str, Any]
type Lookup = Callable[[ContractRef], Document | None]
type Active = Callable[[str], Document | None]
type History = Callable[[str, str], Iterable[Document]]
type ArtifactVerifier = Callable[[str, str], None]
type ObligationKey = tuple[ContractRef | None, str]

_COMMANDMENTS = {"M1", "M2", "M3", "M4", "M5"}


@dataclass
class _Context:
    project_id: str
    contract_id: str
    actor_id: str
    created_at: str
    lookup: Lookup
    active: Active
    history: History
    verify_artifact: ArtifactVerifier
    resolved: dict[ContractRef, Document] = field(default_factory=dict)

    def resolve(self, reference: ContractRef, expected_type: str | None = None) -> Document:
        if reference.project_id != self.project_id:
            raise IntegrityError("Contract reference crosses the project boundary.")
        if expected_type is not None and reference.contract_type != expected_type:
            raise IntegrityError("Contract reference has the wrong type for its use.")
        if reference not in self.resolved:
            document = self.lookup(reference)
            if document is None or ContractRef.from_document(document) != reference:
                raise IntegrityError("Exact contract revision could not be resolved.")
            if document["metadata"]["status"] != "PUBLISHED":
                raise IntegrityError("Contract reference must point to a published revision.")
            approval = document["metadata"]["approval"]
            if reference.contract_type in {"PROJECT", "TECHNOLOGY_DECISION"} and (
                approval is None or approval["kind"] != "HUMAN"
            ):
                raise IntegrityError("Binding source lacks recorded human approval.")
            self.resolved[reference] = document
        return self.resolved[reference]

    def require_active(self, document: Document) -> None:
        reference = ContractRef.from_document(document)
        current = self.active(reference.contract_id)
        if current is None or ContractRef.from_document(current) != reference:
            raise IntegrityError("The binding contract revision is no longer active.")


def _index(records: Iterable[Document], key: str, label: str) -> dict[str, Document]:
    index = {}
    for record in records:
        identifier = record[key]
        if identifier in index:
            raise IntegrityError(f"Duplicate {label} identifier.")
        index[identifier] = record
    return index


def _require_subset(actual: Iterable, allowed: Iterable, label: str) -> None:
    if not set(actual).issubset(allowed):
        raise IntegrityError(f"Unknown or out-of-scope {label} reference.")


def _check_dependencies(records: dict[str, Document], label: str) -> None:
    for record in records.values():
        _require_subset(record["depends_on"], records, f"{label} dependency")
    try:
        tuple(
            TopologicalSorter(
                {key: item["depends_on"] for key, item in records.items()}
            ).static_order()
        )
    except CycleError:
        raise IntegrityError(f"Circular {label} dependency.") from None


def _requirement_items(payload: Document) -> dict[str, Document]:
    items = _index(payload["requirements"], "requirement_id", "requirement")
    items.update(
        (criterion["criterion_id"], criterion)
        for requirement in payload["requirements"]
        for criterion in requirement["acceptance_criteria"]
    )
    return items


def _project_items(payload: Document) -> dict[str, Document]:
    items = _requirement_items(payload)
    items.update(_index(payload["constraints"], "constraint_id", "constraint"))
    items.update(_index(payload["success_criteria"], "criterion_id", "success criterion"))
    return items


def _obligation_key(source: Document) -> ObligationKey:
    if "standard_rule_ref" in source:
        return None, source["standard_rule_ref"]["rule_id"]
    return ContractRef.from_json(source["contract_ref"]), source["obligation_id"]


def _project(payload: Document, context: _Context) -> None:
    requirements = _index(payload["requirements"], "requirement_id", "requirement")
    constraints = _index(payload["constraints"], "constraint_id", "constraint")
    criteria = _index(
        [
            *payload["success_criteria"],
            *(
                criterion
                for requirement in requirements.values()
                for criterion in requirement["acceptance_criteria"]
            ),
        ],
        "criterion_id",
        "project criterion",
    )
    if len(requirements.keys() | constraints.keys() | criteria.keys()) != (
        len(requirements) + len(constraints) + len(criteria)
    ):
        raise IntegrityError("Project obligations share an ambiguous identifier.")
    proposals = _index(payload["structural_proposals"], "proposal_id", "structural proposal")
    for proposal in proposals.values():
        _require_subset(proposal["requirement_ids"], requirements, "proposal requirement")
        _require_subset(proposal["constraint_ids"], constraints, "proposal constraint")
    for decision in _index(payload["negotiated_decisions"], "decision_id", "decision").values():
        _require_subset(decision["proposal_ids"], proposals, "negotiated proposal")


def _decision_drivers(
    payload: Document, context: _Context, project: Document | None = None
) -> None:
    for source in payload["decision_drivers"]["source_refs"]:
        reference, identifier = _obligation_key(source)
        if reference is None:
            continue
        origin = context.resolve(reference, "PROJECT")
        items = _project_items(origin["payload"])
        _require_subset([identifier], items, "technology decision driver")
        if project is None:
            context.require_active(origin)
        elif reference.contract_id != project["metadata"]["contract_id"] or (
            _project_items(project["payload"]).get(identifier) != items[identifier]
        ):
            raise IntegrityError(
                "Technology decision relies on a changed or removed Project obligation."
            )


def _decision(payload: Document, context: _Context) -> None:
    _decision_drivers(payload, context)
    options = _index(payload["ai_recommendations"], "option_id", "technology option")
    if [option["rank"] for option in options.values()] != list(range(1, len(options) + 1)):
        raise IntegrityError("Technology recommendations must be in consecutive rank order.")
    selected = payload["selected_option"]
    if not options or selected is None:
        raise IntegrityError("A technology decision needs viable options and a selected choice.")
    if selected["source"] == "RECOMMENDED":
        _require_subset([selected["option_id"]], options, "selected technology option")
    _index(payload["verification_criteria"], "criterion_id", "technology criterion")


def _interfaces(payload: Document) -> dict[tuple[str, str], Document]:
    interfaces = {
        (item["interface_id"], item["interface_revision"]): item
        for item in payload["provided_interfaces"]
    }
    if len(interfaces) != len(payload["provided_interfaces"]):
        raise IntegrityError("Duplicate provided interface revision.")
    return interfaces


def _module_checks(payload: Document) -> dict[str, Document]:
    spec = payload["verification_spec"]
    return _index(
        (
            check
            for group in (
                "requirement_checks",
                "constraint_checks",
                "interface_checks",
                "quality_checks",
            )
            for check in spec[group]
        ),
        "check_id",
        "module check",
    )


def _module_project_items(
    payload: Document, context: _Context, project: Document | None = None
) -> set[str]:
    """Check exact global obligations and prove equivalence when retaining a module."""
    required = set()
    project_references = set()
    for group in ("requirement_refs", "constraint_refs"):
        for source in payload[group]:
            reference, identifier = _obligation_key(source)
            if reference is None:
                raise IntegrityError(
                    "Module requirements and constraints must reference the Project Contract."
                )
            project_references.add(reference)
            original = context.resolve(reference, "PROJECT")["payload"]
            if group == "requirement_refs":
                items = _requirement_items(original)
            else:
                items = _index(original["constraints"], "constraint_id", "constraint")
            _require_subset([identifier], items, "module project obligation")
            binding = project if project is not None else context.active(reference.contract_id)
            if (
                binding is None
                or reference.contract_id != binding["metadata"]["contract_id"]
                or (_project_items(binding["payload"]).get(identifier) != items[identifier])
            ):
                raise IntegrityError("A module refers to a changed or removed Project obligation.")
            if group == "requirement_refs":
                required.update(
                    requirement["requirement_id"]
                    for requirement in original["requirements"]
                    if requirement["requirement_id"] == identifier
                    or any(
                        item["criterion_id"] == identifier
                        for item in requirement["acceptance_criteria"]
                    )
                )
    if len(project_references) > 1:
        raise IntegrityError(
            "Module obligations must refer to one exact Project Contract revision."
        )
    return required


def _module(payload: Document, context: _Context) -> None:
    _module_project_items(payload, context)
    providers = _interfaces(payload)
    for previous in context.history("MODULE", context.project_id):
        previous_payload = previous["payload"]
        same_contract = previous["metadata"]["contract_id"] == context.contract_id
        same_module = previous_payload["module_id"] == payload["module_id"]
        if same_contract != same_module:
            raise IntegrityError("Module identity must be unique and stable across revisions.")
        if same_contract:
            for key, definition in _interfaces(previous_payload).items():
                if key in providers and providers[key] != definition:
                    raise IntegrityError("A published interface revision cannot be redefined.")
    interfaces = {
        (payload["module_id"], identifier, revision) for identifier, revision in providers
    }
    consumed = set()
    for consumer in payload["consumed_interfaces"]:
        provider = context.resolve(
            ContractRef.from_json(consumer["provider_contract_ref"]), "MODULE"
        )["payload"]
        interface = (consumer["interface_id"], consumer["required_interface_revision"])
        key = (consumer["provider_module_id"], *interface)
        if key in consumed:
            raise IntegrityError("Duplicate consumed interface revision.")
        consumed.add(key)
        if (
            provider["module_id"] != consumer["provider_module_id"]
            or provider["module_id"] == payload["module_id"]
        ):
            raise IntegrityError("Consumed interface names the wrong provider module.")
        _require_subset([interface], _interfaces(provider), "provider interface revision")
        interfaces.add(key)
    for item in payload["technology_decision_refs"]:
        decision = context.resolve(ContractRef.from_json(item), "TECHNOLOGY_DECISION")["payload"]
        _require_subset(
            [payload["module_id"]],
            decision["decision_scope"]["module_ids"],
            "technology decision scope",
        )

    _module_checks(payload)
    spec = payload["verification_spec"]
    for source_group, check_group in (
        ("requirement_refs", "requirement_checks"),
        ("constraint_refs", "constraint_checks"),
    ):
        sources = {_obligation_key(source) for source in payload[source_group]}
        checked = {_obligation_key(check["source_ref"]) for check in spec[check_group]}
        if checked != sources or any(not check["blocking"] for check in spec[check_group]):
            raise IntegrityError(
                "Module verification must cover each binding requirement and constraint."
            )
    covered_interfaces = {
        (check["provider_module_id"], check["interface_id"], check["interface_revision"])
        for check in spec["interface_checks"]
    }
    if covered_interfaces != interfaces or any(
        not check["blocking"] for check in spec["interface_checks"]
    ):
        raise IntegrityError(
            "Every provided or consumed interface needs a blocking compatibility check."
        )
    rules = set()
    for check in spec["quality_checks"]:
        rule = check["standard_rule_ref"]
        if rule is not None:
            if not check["blocking"]:
                raise IntegrityError("A quality check cannot weaken a Standard obligation.")
            rules.add(rule["rule_id"])
    if rules != _COMMANDMENTS:
        raise IntegrityError("Module quality verification must cover all five Commandments.")


def _workflow(payload: Document, context: _Context) -> None:
    project = context.resolve(ContractRef.from_json(payload["project_contract_ref"]), "PROJECT")
    context.require_active(project)
    required = {item["requirement_id"] for item in project["payload"]["requirements"]}
    modules = _index(payload["modules"], "module_id", "workflow module")
    checkpoints = _index(payload["checkpoints"], "checkpoint_id", "checkpoint")
    milestones = _index(payload["playtest_milestones"], "milestone_id", "milestone")
    for records, label in (
        (modules, "module"),
        (checkpoints, "checkpoint"),
        (milestones, "milestone"),
    ):
        _check_dependencies(records, label)

    module_documents = {}
    for identifier, row in modules.items():
        module = context.resolve(ContractRef.from_json(row["module_contract_ref"]), "MODULE")[
            "payload"
        ]
        if identifier != module["module_id"]:
            raise IntegrityError(
                "Workflow module identifier disagrees with its referenced contract."
            )
        if set(row["requirement_ids"]) != _module_project_items(module, context, project):
            raise IntegrityError(
                "Workflow requirements disagree with the module's approved obligations."
            )
        _require_subset(row["requirement_ids"], required, "workflow requirement")
        module_documents[identifier] = module
    decisions_by_module = {identifier: set() for identifier in modules}
    subjects = set()
    for row in payload["technology_decisions"]:
        identifier = row["module_id"]
        _require_subset([identifier], modules, "technology decision module")
        reference = ContractRef.from_json(row["decision_contract_ref"])
        decision = context.resolve(reference, "TECHNOLOGY_DECISION")["payload"]
        _decision_drivers(decision, context, project)
        _require_subset(
            [identifier], decision["decision_scope"]["module_ids"], "technology decision scope"
        )
        subject = (identifier, decision["decision_scope"]["subject"].strip().casefold())
        if subject in subjects:
            raise IntegrityError(
                "Conflicting or duplicate technology decisions for one module subject."
            )
        subjects.add(subject)
        decisions_by_module[identifier].add(reference)
    for identifier, module in module_documents.items():
        if decisions_by_module[identifier] != {
            ContractRef.from_json(ref) for ref in module["technology_decision_refs"]
        }:
            raise IntegrityError(
                "Workflow does not carry the module's exact approved technology decisions."
            )
        for consumer in module["consumed_interfaces"]:
            provider_id = consumer["provider_module_id"]
            _require_subset(
                [provider_id], modules[identifier]["depends_on"], "interface provider dependency"
            )
            interface = (consumer["interface_id"], consumer["required_interface_revision"])
            original = context.resolve(
                ContractRef.from_json(consumer["provider_contract_ref"]), "MODULE"
            )["payload"]
            if (
                _interfaces(module_documents[provider_id]).get(interface)
                != _interfaces(original)[interface]
            ):
                raise IntegrityError(
                    "Workflow provider does not preserve the consumed interface revision."
                )

    checkpoint_requirements = set()
    for checkpoint in checkpoints.values():
        _require_subset(checkpoint["module_ids"], modules, "checkpoint module")
        allowed = {
            item
            for module_id in checkpoint["module_ids"]
            for item in modules[module_id]["requirement_ids"]
        }
        _require_subset(checkpoint["requirement_ids"], allowed, "checkpoint requirement")
        checkpoint_requirements.update(checkpoint["requirement_ids"])
    if checkpoint_requirements != required:
        raise IntegrityError("Workflow checkpoints omit approved global requirements.")
    previous = set()
    for identifier, milestone in milestones.items():
        _require_subset(milestone["depends_on"], previous, "earlier milestone dependency")
        _require_subset(milestone["required_checkpoint_ids"], checkpoints, "milestone checkpoint")
        previous.add(identifier)
    _workflow_criteria(checkpoints.values(), milestones.values())


def _revision_request(payload: Document, context: _Context) -> None:
    if payload["project_id"] != context.project_id:
        raise IntegrityError("Revision request project identity differs from its envelope.")
    project = context.resolve(ContractRef.from_json(payload["base_contract_version"]), "PROJECT")
    context.require_active(project)
    if any(
        previous["metadata"]["contract_id"] != context.contract_id
        and previous["payload"]["request_id"] == payload["request_id"]
        for previous in context.history("PROJECT_REVISION_REQUEST", context.project_id)
    ):
        raise IntegrityError("Revision request identifier already belongs to another contract.")
    base = project["payload"]
    affected = payload["affected_proposals"]
    groups = (
        (
            "proposal_ids",
            _index(base["structural_proposals"], "proposal_id", "structural proposal"),
        ),
        ("requirement_ids", _index(base["requirements"], "requirement_id", "requirement")),
        ("constraint_ids", _index(base["constraints"], "constraint_id", "constraint")),
        (
            "criterion_ids",
            set(_project_items(base))
            - {item["requirement_id"] for item in base["requirements"]}
            - {item["constraint_id"] for item in base["constraints"]},
        ),
    )
    if not any(affected[key] for key, _ in groups):
        raise IntegrityError("Revision request must identify a bounded structural change.")
    for key, identifiers in groups:
        _require_subset(affected[key], identifiers, "affected project obligation")
    _require_subset(payload["impact"]["requirement_ids"], groups[1][1], "impacted requirement")
    for reference in payload["impact"]["technology_decision_refs"]:
        context.resolve(ContractRef.from_json(reference), "TECHNOLOGY_DECISION")
    for entry in payload["evidence"]:
        source = context.resolve(ContractRef.from_json(entry["source_ref"]))
        if entry["evidence_ids"]:
            if source["metadata"]["contract_type"] != "VALIDATION_RESULT":
                raise IntegrityError(
                    "Revision evidence identifiers require an exact validation result source."
                )
            _require_subset(
                entry["evidence_ids"],
                (item["evidence_id"] for item in source["payload"]["evidence_refs"]),
                "revision evidence",
            )
    alternatives = payload["alternatives"]
    if bool(alternatives["options"]) == bool(alternatives["unavailable_reason"]):
        raise IntegrityError("Provide revision alternatives or justify why none are available.")


def _workflow_criteria(
    checkpoints: Iterable[Document], milestones: Iterable[Document]
) -> dict[str, Document]:
    criteria = [criterion for item in checkpoints for criterion in item["completion_criteria"]]
    criteria.extend(criterion for item in milestones for criterion in item["readiness_criteria"])
    return _index(criteria, "criterion_id", "workflow criterion")


def _milestone_ancestors(milestones: dict[str, Document], selected: set[str]) -> set[str]:
    inherited = set()
    pending = list(selected)
    while pending:
        identifier = pending.pop()
        if identifier not in inherited:
            inherited.add(identifier)
            pending.extend(milestones[identifier]["depends_on"])
    return inherited


def _workflow_scope(
    workflow: Document, level: str, target_ids: set[str], context: _Context
) -> tuple[set[ContractRef], set[str], dict[str, Document]]:
    payload = workflow["payload"]
    modules = _index(payload["modules"], "module_id", "workflow module")
    checkpoints = _index(payload["checkpoints"], "checkpoint_id", "checkpoint")
    milestones = _index(payload["playtest_milestones"], "milestone_id", "milestone")
    chosen_milestones: set[str] = set()
    if level == "PRODUCT":
        chosen_modules = set(modules)
        chosen_checkpoints = set(checkpoints)
        chosen_milestones = set(milestones)
    elif level == "INTEGRATION":
        interface_modules: dict[str, set[str]] = {}
        for identifier, row in modules.items():
            module = context.resolve(ContractRef.from_json(row["module_contract_ref"]), "MODULE")[
                "payload"
            ]
            for interface in (*module["provided_interfaces"], *module["consumed_interfaces"]):
                interface_modules.setdefault(interface["interface_id"], set()).add(identifier)
        if target_ids & modules.keys() & interface_modules.keys():
            raise IntegrityError(
                "Integration target identifier is ambiguous between module and interface."
            )
        _require_subset(target_ids, modules.keys() | interface_modules.keys(), "integration target")
        chosen_modules = target_ids & modules.keys()
        for interface_id in target_ids & interface_modules.keys():
            chosen_modules.update(interface_modules[interface_id])
        chosen_checkpoints = set()
    else:
        if level == "CHECKPOINT":
            _require_subset(target_ids, checkpoints, "validation checkpoint target")
            chosen_checkpoints = target_ids
        else:
            _require_subset(target_ids, milestones, "validation milestone target")
            chosen_milestones = _milestone_ancestors(milestones, target_ids)
            chosen_checkpoints = {
                checkpoint
                for identifier in chosen_milestones
                for checkpoint in milestones[identifier]["required_checkpoint_ids"]
            }
        chosen_modules = {
            module
            for identifier in chosen_checkpoints
            for module in checkpoints[identifier]["module_ids"]
        }
    requirement_ids = {
        requirement
        for identifier in chosen_checkpoints
        for requirement in checkpoints[identifier]["requirement_ids"]
    }
    if level in {"INTEGRATION", "PRODUCT"}:
        requirement_ids.update(
            requirement
            for identifier in chosen_modules
            for requirement in modules[identifier]["requirement_ids"]
        )
    criteria = _workflow_criteria(
        (checkpoints[identifier] for identifier in chosen_checkpoints),
        (milestones[identifier] for identifier in chosen_milestones),
    )
    return (
        {
            ContractRef.from_json(modules[identifier]["module_contract_ref"])
            for identifier in chosen_modules
        },
        requirement_ids,
        criteria,
    )


def _validation_obligations(
    scope: Document, sources: set[ContractRef], context: _Context
) -> tuple[dict[ObligationKey, Document], dict[ObligationKey, Document]]:
    level = scope["level"]
    target_ids = set(scope["target_ids"])
    target_ref = ContractRef.from_json(scope["target_contract_ref"])
    target_types = {"PRODUCT": "PROJECT", "MODULE": "MODULE"}
    target = context.resolve(target_ref, target_types.get(level, "WORKFLOW"))
    _require_subset([target_ref], sources, "validation scope source")
    project_refs = [reference for reference in sources if reference.contract_type == "PROJECT"]
    if len(project_refs) != 1:
        raise IntegrityError("Validation needs one direct approved Project Contract revision.")
    project_ref = project_refs[0]
    project = context.resolve(project_ref, "PROJECT")
    context.require_active(project)
    if level == "PRODUCT" and (target_ref != project_ref or target_ids != {context.project_id}):
        raise IntegrityError("Product validation must bind to the approved project identity.")
    if level == "PRODUCT":
        workflow_ids = {
            record["metadata"]["contract_id"]
            for record in context.history("WORKFLOW", context.project_id)
        }
        for identifier in workflow_ids:
            workflow = context.active(identifier)
            if workflow is None:
                continue
            if ContractRef.from_json(workflow["payload"]["project_contract_ref"]) != project_ref:
                raise IntegrityError(
                    "Reconcile the active Workflow with the approved Project revision."
                )
            _require_subset(
                [ContractRef.from_document(workflow)], sources, "active Workflow Contract"
            )
    if level == "MODULE" and target_ids != {target["payload"]["module_id"]}:
        raise IntegrityError("Module validation target differs from its exact Module Contract.")

    required: dict[ObligationKey, Document] = {
        (None, identifier): {} for identifier in _COMMANDMENTS
    }
    optional: dict[ObligationKey, Document] = {}
    project_items = _project_items(project["payload"])
    project_ids = set(project_items) if level == "PRODUCT" else set()
    expected_modules = {target_ref} if level == "MODULE" else set()
    requirement_ids = set()
    expected_technologies = set()
    for reference in sources:
        if reference.contract_type == "WORKFLOW":
            workflow = context.resolve(reference, "WORKFLOW")
            context.require_active(workflow)
            if ContractRef.from_json(workflow["payload"]["project_contract_ref"]) != project_ref:
                raise IntegrityError(
                    "Validation workflow does not bind the same approved Project revision."
                )
            if level != "PRODUCT" and reference != target_ref:
                raise IntegrityError("Validation workflow is outside the declared scope.")
            modules, requirements, criteria = _workflow_scope(workflow, level, target_ids, context)
            expected_modules.update(modules)
            requirement_ids.update(requirements)
            required.update(
                {(reference, identifier): item for identifier, item in criteria.items()}
            )
        elif reference.contract_type == "MODULE":
            module = context.resolve(reference, "MODULE")["payload"]
            _module_project_items(module, context, project)
            project_ids.update(
                _obligation_key(source)[1]
                for group in ("requirement_refs", "constraint_refs")
                for source in module[group]
            )
            expected_technologies.update(
                ContractRef.from_json(raw) for raw in module["technology_decision_refs"]
            )
            for identifier, check in _module_checks(module).items():
                key = (reference, identifier)
                (required if check["blocking"] else optional)[key] = check
        elif reference.contract_type == "TECHNOLOGY_DECISION":
            decision = context.resolve(reference, "TECHNOLOGY_DECISION")["payload"]
            _decision_drivers(decision, context, project)
            required.update(
                {
                    (reference, item["criterion_id"]): item
                    for item in decision["verification_criteria"]
                }
            )
        elif reference.contract_type != "PROJECT":
            raise IntegrityError("Validation source is not an approved obligation contract type.")
    _require_subset(expected_modules, sources, "scoped Module Contract")
    _require_subset(expected_technologies, sources, "scoped Technology Decision Contract")
    project_ids.update(requirement_ids)
    for requirement in project["payload"]["requirements"]:
        if requirement["requirement_id"] in project_ids:
            project_ids.update(item["criterion_id"] for item in requirement["acceptance_criteria"])
    required.update(
        {(project_ref, identifier): project_items[identifier] for identifier in project_ids}
    )
    return required, optional


def validation_gate(level: str) -> str:
    """Map a schema-defined Validation scope to its technical gate."""
    return {
        "MODULE": "CHECKPOINT",
        "INTEGRATION": "CHECKPOINT",
        "CHECKPOINT": "CHECKPOINT",
        "PLAYTEST_MILESTONE": "PLAYTEST_READINESS",
        "PRODUCT": "PRODUCT_VALIDATION",
    }[level]


def require_validation_interfaces(
    sources: Iterable[Document], lookup: Lookup, active: Active
) -> None:
    """Require current providers to retain the exact terms consumed by scoped modules."""
    for source in sources:
        module = ContractRef.from_document(source)
        if module.contract_type != "MODULE":
            continue
        for consumer in source["payload"]["consumed_interfaces"]:
            reference = ContractRef.from_json(consumer["provider_contract_ref"])
            if reference.contract_type != "MODULE" or reference.project_id != module.project_id:
                raise IntegrityError(
                    "A consumed Validation interface has the wrong provider scope."
                )
            original = lookup(reference)
            provider_id = consumer["provider_module_id"]
            if (
                original is None
                or ContractRef.from_document(original) != reference
                or original["payload"]["module_id"] != provider_id
            ):
                raise IntegrityError("The exact consumed Validation provider is unavailable.")
            key = (consumer["interface_id"], consumer["required_interface_revision"])
            terms = _interfaces(original["payload"]).get(key)
            if terms is None:
                raise IntegrityError("The exact consumed Validation interface is unavailable.")
            current = active(reference.contract_id)
            if (
                current is None
                or current["metadata"]["contract_type"] != "MODULE"
                or current["metadata"]["project_id"] != module.project_id
                or current["metadata"]["contract_id"] != reference.contract_id
                or current["payload"]["module_id"] != provider_id
                or _interfaces(current["payload"]).get(key) != terms
            ):
                raise ConflictError(
                    "The current provider no longer preserves the consumed Validation interface."
                )


def derive_validation_obligations(
    project_ref: ContractRef,
    scope: Document,
    lookup: Lookup,
    active: Active,
    *,
    history: History,
) -> tuple[set[ContractRef], dict[ObligationKey, Document], dict[ObligationKey, Document]]:
    """Select exact scoped sources and derive obligations by the publication rules."""
    context = _Context(project_ref.project_id, "", "", "", lookup, active, history, lambda *_: None)
    context.require_active(context.resolve(project_ref, "PROJECT"))
    level = scope["level"]
    target_ref = ContractRef.from_json(scope["target_contract_ref"])
    sources = {project_ref, target_ref}
    if level == "PRODUCT":
        workflows = [
            workflow
            for identifier in {
                document["metadata"]["contract_id"]
                for document in history("WORKFLOW", project_ref.project_id)
            }
            if (workflow := active(identifier)) is not None
        ]
    elif level != "MODULE":
        workflows = [context.resolve(target_ref, "WORKFLOW")]
    else:
        workflows = []
    for workflow in workflows:
        sources.add(ContractRef.from_document(workflow))
        module_refs, _, _ = _workflow_scope(workflow, level, set(scope["target_ids"]), context)
        sources.update(module_refs)
    for reference in tuple(sources):
        if reference.contract_type == "MODULE":
            module = context.resolve(reference, "MODULE")["payload"]
            sources.update(ContractRef.from_json(raw) for raw in module["technology_decision_refs"])
    required, optional = _validation_obligations(scope, sources, context)
    return sources, required, optional


def _validation(payload: Document, context: _Context) -> None:
    scope = payload["validation_scope"]
    if payload["gate_policy"]["gate"] != validation_gate(scope["level"]):
        raise IntegrityError("Validation gate does not match the declared scope.")
    sources = {ContractRef.from_json(raw) for raw in payload["source_contract_refs"]}
    required, optional = _validation_obligations(scope, sources, context)
    covered = set()
    for item in _index(payload["verification_matrix"], "check_id", "validation check").values():
        key = _obligation_key(item["source_ref"])
        if key not in required and key not in optional:
            raise IntegrityError(
                "Validation matrix refers to an undeclared or out-of-scope obligation."
            )
        if key in required and item["gate_classification"] != "MANDATORY":
            raise IntegrityError("Validation cannot downgrade a mandatory obligation.")
        if key[0] is not None and key[0].contract_type == "MODULE":
            check = required[key] if key in required else optional[key]
            _require_subset(
                [item["verification_method"]], check["verification_methods"], "verification method"
            )
            _require_subset(
                check["evidence_required"], item["required_evidence"], "required evidence kind"
            )
        covered.add(key)
    if not required.keys() <= covered:
        raise IntegrityError("Validation matrix omits mandatory scoped obligations.")


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value.upper())


def _verify_result_evidence(
    payload: Document,
    matrix: dict[str, Document],
    previous_results: list[Document],
    context: _Context,
) -> dict[str, Document]:
    execution = payload["target_and_execution"]
    evidence = _index(payload["evidence_refs"], "evidence_id", "evidence")
    old_by_id = {}
    old_by_digest: dict[str, list[Document]] = {}
    digest_by_path = {}
    for result in previous_results:
        for item in result["payload"]["evidence_refs"]:
            old_by_id[item["evidence_id"]] = item
            old_by_digest.setdefault(item["sha256"], []).append(item["artifact_identity"])
            digest_by_path[item["path"].casefold()] = item["sha256"]
    expected_context = {
        "validation_run_id": execution["validation_run_id"],
        "validation_plan_ref": payload["validation_plan_ref"],
    }
    for identifier, item in evidence.items():
        check = matrix.get(item["check_id"])
        if (
            check is None
            or item["source_ref"] != check["source_ref"]
            or (item["verification_method"] != check["verification_method"])
        ):
            raise IntegrityError("Evidence does not match a check in the exact validation plan.")
        if item["artifact_identity"] != execution["artifact_identity"] or (
            item["execution_context"] != expected_context
        ):
            raise IntegrityError(
                "Evidence belongs to a different validation run, plan, or artifact."
            )
        if item["evaluator_ref"] != execution["evaluator_ref"]:
            raise IntegrityError(
                "Evidence evaluator differs from the recorded execution evaluator."
            )
        if item["evidence_kind"] not in check["required_evidence"]:
            raise IntegrityError("Evidence kind is not admissible for the planned check.")
        if identifier in old_by_id and item != old_by_id[identifier]:
            raise IntegrityError("An immutable evidence identifier cannot be rebound.")
        if any(
            target != item["artifact_identity"] for target in old_by_digest.get(item["sha256"], [])
        ):
            raise IntegrityError("Historical evidence cannot be reused for a different artifact.")
        if digest_by_path.setdefault(item["path"].casefold(), item["sha256"]) != item["sha256"]:
            raise IntegrityError(
                "A published evidence path is already bound to a different digest."
            )
        context.verify_artifact(item["path"], item["sha256"])
    return evidence


def _validation_result(payload: Document, context: _Context) -> None:
    plan_document = context.resolve(
        ContractRef.from_json(payload["validation_plan_ref"]), "VALIDATION"
    )
    plan = plan_document["payload"]
    execution = payload["target_and_execution"]
    if execution["evaluator_ref"] != context.actor_id:
        raise IntegrityError("Execution evaluator must match the trusted Validation publisher.")
    for item in plan["source_contract_refs"]:
        reference = ContractRef.from_json(item)
        if reference.contract_type in {"WORKFLOW", "MODULE", "TECHNOLOGY_DECISION"}:
            implementer = context.resolve(reference)["metadata"]["provenance"]["actor_id"]
            if execution["evaluator_ref"] == implementer:
                raise IntegrityError(
                    "Validation cannot use an implementation publisher as evaluator."
                )
    started = _date(execution["started_at"])
    finished = _date(execution["finished_at"]) if execution["finished_at"] is not None else None
    published = _date(context.created_at)
    if started < _date(plan_document["metadata"]["created_at"]):
        raise IntegrityError("Validation execution starts before its exact plan was published.")
    if started > published or (finished is not None and finished > published):
        raise IntegrityError("Validation execution cannot occur after result publication.")
    if finished is not None and finished < started:
        raise IntegrityError("Validation execution finishes before it starts.")
    if execution["status"] == "COMPLETED" and finished is None:
        raise IntegrityError("A completed validation execution needs a finish time.")
    previous = list(context.history("VALIDATION_RESULT", context.project_id))
    if any(
        item["payload"]["target_and_execution"]["validation_run_id"]
        == execution["validation_run_id"]
        for item in previous
    ):
        raise IntegrityError("Validation run identifier has already been published.")
    matrix = _index(plan["verification_matrix"], "check_id", "validation check")
    results = _index(payload["check_results"], "check_id", "check result")
    if results.keys() != matrix.keys():
        raise IntegrityError("Validation result must record each exact plan check once.")
    evidence = _verify_result_evidence(payload, matrix, previous, context)
    mandatory = {
        identifier
        for identifier, item in matrix.items()
        if item["gate_classification"] == "MANDATORY"
    }
    covered = set()
    unverified = set()
    conformant = set()
    used_evidence = set()
    for identifier, result in results.items():
        check = matrix[identifier]
        if (
            result["source_ref"] != check["source_ref"]
            or result["verification_method"] != check["verification_method"]
        ):
            raise IntegrityError(
                "Check result source or method differs from the exact validation plan."
            )
        status = result["status"]
        if (status is None) != bool(result.get("not_applicable_reason")):
            raise IntegrityError("Not applicable needs a separate justified disposition.")
        if status is None and identifier in mandatory:
            raise IntegrityError("A mandatory check cannot be marked not applicable.")
        evidence_ids = set(result["evidence_ids"])
        _require_subset(evidence_ids, evidence, "check evidence")
        if any(evidence[item]["check_id"] != identifier for item in evidence_ids):
            raise IntegrityError("Check result references evidence for another check.")
        used_evidence.update(evidence_ids)
        if status in {"CONFORMANT", "NONCONFORMANT"}:
            kinds = {evidence[item]["evidence_kind"] for item in evidence_ids}
            if not set(check["required_evidence"]).issubset(kinds):
                raise IntegrityError("A concluded check lacks admissible required evidence.")
            covered.add(identifier)
        if status == "CONFORMANT":
            conformant.add(identifier)
        elif status == "NOT_VERIFIED":
            unverified.add(identifier)
    if used_evidence != evidence.keys():
        raise IntegrityError("Validation evidence is not linked to its result check.")

    coverage = payload["coverage_summary"]
    sufficient = mandatory.issubset(covered)
    if (
        set(coverage["covered_check_ids"]) != covered
        or set(coverage["unverified_check_ids"]) != unverified
        or (coverage["sufficient"] != sufficient)
    ):
        raise IntegrityError(
            "Reported validation coverage does not match recorded checks and evidence."
        )
    blockers = mandatory - conformant
    satisfied = execution["status"] == "COMPLETED" and sufficient and not blockers
    gate = payload["gate_assessment"]
    if (
        gate["gate"] != plan["gate_policy"]["gate"]
        or gate["scope"] != plan["validation_scope"]["level"]
    ):
        raise IntegrityError("Gate assessment does not match the exact plan gate and scope.")
    if gate["state"] != ("SATISFIED" if satisfied else "BLOCKED") or (
        set(gate["blocking_check_ids"]) != blockers
    ):
        raise IntegrityError(
            "Gate assessment contradicts execution, evidence, or mandatory checks."
        )
    for finding in _index(payload["findings"], "finding_id", "finding").values():
        identifier = finding["check_id"]
        _require_subset([identifier], results, "finding check")
        _require_subset(
            finding["evidence_ids"], results[identifier]["evidence_ids"], "finding evidence"
        )
        if finding["blocking"] != (identifier in blockers):
            raise IntegrityError("Finding blocking status contradicts the validation gate.")


def _report_evidence(
    payload: Document, results: list[Document], context: _Context
) -> dict[str, Document]:
    candidates = {
        item["evidence_id"]: item for result in results for item in result["evidence_refs"]
    }
    evidence = _index(payload["artifact_and_evidence_index"], "evidence_id", "report evidence")
    for identifier, item in evidence.items():
        if candidates.get(identifier) != item:
            raise IntegrityError(
                "Report evidence must be the unchanged evidence from a cited validation run."
            )
        context.verify_artifact(item["path"], item["sha256"])
    return evidence


def _report_gate_states(
    scope_kind: str,
    lineage: Document,
    results: list[Document],
    sources: Iterable[ContractRef],
    context: _Context,
) -> set[str]:
    expected_level = {"CHECKPOINT": "CHECKPOINT", "MILESTONE": "PLAYTEST_MILESTONE"}.get(
        scope_kind, "PRODUCT"
    )
    if scope_kind == "CHECKPOINT":
        expected_targets = set(lineage["checkpoint_ids"])
        if not expected_targets:
            raise IntegrityError("A checkpoint report needs a checkpoint lineage.")
    elif scope_kind == "MILESTONE":
        if lineage["milestone_id"] is None:
            raise IntegrityError("A milestone report needs a milestone lineage.")
        expected_targets = {lineage["milestone_id"]}
    else:
        expected_targets = {context.project_id}
    states = set()
    for result in results:
        plan = context.resolve(ContractRef.from_json(result["validation_plan_ref"]), "VALIDATION")
        plan_payload = plan["payload"]
        planned_scope = plan_payload["validation_scope"]
        if (
            planned_scope["level"] != expected_level
            or set(planned_scope["target_ids"]) != expected_targets
        ):
            continue
        planned_sources = {
            ContractRef.from_json(raw) for raw in plan_payload["source_contract_refs"]
        }
        planned_contract_ids = {reference.contract_id for reference in planned_sources}
        if any(
            reference.contract_id in planned_contract_ids and reference not in planned_sources
            for reference in sources
        ):
            continue
        states.add(result["gate_assessment"]["state"])
    return states


def _report(payload: Document, context: _Context) -> None:
    lineage = payload["version_and_delivery_lineage"]
    if lineage["project_id"] != context.project_id:
        raise IntegrityError("Report lineage project differs from its envelope.")
    scope = payload["report_scope"]
    sources = {
        ContractRef.from_json(raw): context.resolve(ContractRef.from_json(raw))
        for raw in payload["source_refs"]
    }
    if any(
        _date(source["metadata"]["created_at"]) > _date(scope["as_of"])
        for source in sources.values()
    ):
        raise IntegrityError("Report snapshot refers to a source published after its cutoff.")
    digest = payload["execution_and_validation_digest"]
    references = [ContractRef.from_json(raw) for raw in digest["validation_result_refs"]]
    _require_subset(references, sources, "report validation source")
    results = [
        context.resolve(reference, "VALIDATION_RESULT")["payload"] for reference in references
    ]
    targets = {
        tuple(sorted(result["target_and_execution"]["artifact_identity"].items()))
        for result in results
    }
    if len(targets) > 1:
        raise IntegrityError("Report digest combines validation results for different artifacts.")
    for result in results:
        target = result["target_and_execution"]["artifact_identity"]
        if lineage["build_id"] is not None:
            matches = target.get("build_id") == lineage["build_id"]
        else:
            matches = scope["target_id"] in target.values()
        if not matches:
            raise IntegrityError("Report validation evidence belongs to another build or artifact.")
    expected_blockers = {
        check for result in results for check in result["gate_assessment"]["blocking_check_ids"]
    }
    if set(digest["blocked_check_ids"]) != expected_blockers:
        raise IntegrityError("Report digest misstates its source validation blockers.")
    states = _report_gate_states(scope["kind"], lineage, results, sources, context)
    technical = lineage["technical_validation"]
    if technical == "VALIDATED" and states != {"SATISFIED"}:
        raise IntegrityError(
            "Report cannot claim technical validation without a matching satisfied gate."
        )
    if technical == "BLOCKED" and "BLOCKED" not in states:
        raise IntegrityError("Report cannot claim a blocked gate without a matching source result.")
    acceptance = payload["feedback_and_acceptance"]["review_approval_id"]
    if (lineage["acceptance"] == "NOT_REVIEWED") != (acceptance is None):
        raise IntegrityError("Report acceptance status and review approval must agree.")
    if acceptance is not None and lineage["delivery"] != "DELIVERED":
        raise IntegrityError("Product acceptance review requires a delivered version.")

    evidence = _report_evidence(payload, results, context)
    for rule, quality in payload["engineering_quality_and_documentation"].items():
        _require_subset(quality["evidence_ids"], evidence, "quality evidence")
        if not quality["evidence_ids"] and not quality["gaps"]:
            raise IntegrityError("Each Commandment needs evidence or an explicit reporting gap.")
        for identifier in quality["evidence_ids"]:
            reference, source_id = _obligation_key(evidence[identifier]["source_ref"])
            if reference is not None and reference.contract_type == "MODULE":
                module = context.resolve(reference, "MODULE")["payload"]
                check = _module_checks(module).get(source_id, {})
                source_id = (check.get("standard_rule_ref") or {}).get("rule_id")
                reference = None
            if reference is not None or source_id != rule:
                raise IntegrityError("Report quality evidence refers to a different obligation.")

    changes = payload["decisions_and_change_history"]
    _require_subset(
        (ContractRef.from_json(raw) for raw in changes["change_refs"]),
        sources,
        "report change source",
    )
    decisions = set()
    for reference, source in sources.items():
        approval = source["metadata"]["approval"]
        if approval is not None:
            decisions.add(approval["approval_id"])
        if reference.contract_type == "PROJECT":
            decisions.update(
                item["decision_id"] for item in source["payload"]["negotiated_decisions"]
            )
    _require_subset(changes["decision_ids"], decisions, "reported decision or approval")
    _require_subset(
        (
            ContractRef.from_json(metric["source_ref"])
            for metric in payload["risks_metrics_and_next_actions"]["metrics"]
        ),
        sources,
        "report metric source",
    )


_CHECKS = {
    "PROJECT": _project,
    "WORKFLOW": _workflow,
    "MODULE": _module,
    "TECHNOLOGY_DECISION": _decision,
    "VALIDATION": _validation,
    "VALIDATION_RESULT": _validation_result,
    "EVIDENCE_REPORT": _report,
    "PROJECT_REVISION_REQUEST": _revision_request,
}


def validate_semantics(
    document: Document,
    lookup: Lookup,
    active: Active,
    *,
    history: History,
    verify_artifact: ArtifactVerifier,
) -> None:
    """Check a schema-valid publication against exact stored revisions and evidence."""
    reference = ContractRef.from_document(document)
    context = _Context(
        reference.project_id,
        reference.contract_id,
        document["metadata"]["provenance"]["actor_id"],
        document["metadata"]["created_at"],
        lookup,
        active,
        history,
        verify_artifact,
    )
    for target in iter_references(document):
        context.resolve(target)
    _CHECKS[reference.contract_type](document["payload"], context)
