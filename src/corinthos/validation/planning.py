# SPDX-License-Identifier: MPL-2.0
"""Derive and publish independently reviewed Validation plans."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from corinthos.contracts import ContractRef, PublishContext
from corinthos.contracts.model import (
    ID_PATTERN,
    AuthorityError,
    ConflictError,
    IntegrityError,
    canonical_json,
)
from corinthos.contracts.semantics import (
    derive_validation_obligations,
    require_validation_interfaces,
    validation_gate,
)
from corinthos.standard import load_standard

from .procedures import digest, validate_binding
from .repository import ValidationRepository

_IMPLEMENTATION_TYPES = {"WORKFLOW", "MODULE", "TECHNOLOGY_DECISION"}
_COMPOUND_METHOD = "Run focused checks and review the exact obligation."
_COMMAND_METHODS = {"test", "automated test", "contract test", "command"}
_REVIEW_KEYS = {"actor_id", "criterion_sha256", "binding_sha256", "rationale"}


def _reference(value):
    return value if isinstance(value, ContractRef) else ContractRef.from_json(value)


def _identifier(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise IntegrityError("Validation requires a valid identifier.")
    return value


def _target_ids(values):
    if not isinstance(values, (list, tuple)) or not values:
        raise IntegrityError("Select at least one exact Validation scope target.")
    identifiers = [_identifier(value) for value in values]
    if len(identifiers) != len(set(identifiers)):
        raise IntegrityError("Validation scope targets must be unique.")
    return sorted(identifiers)


def _plan_content(payload):
    execution = payload["execution_plan"]
    return {
        **payload,
        "execution_plan": {
            **execution,
            "conditions": [
                item
                for item in execution["conditions"]
                if not item.startswith("method-reviews-sha256:")
            ],
        },
    }


class ValidationPlanner:
    """Select obligations from approved sources and publish ready, exact plans."""

    def __init__(self, store, policy_path, policy_schema_path):
        self.store = store
        self.repository = ValidationRepository(store)
        self.policy_path = policy_path
        self.policy_schema_path = policy_schema_path

    def _read(self, reference):
        document = self.store.get(reference)
        if document is None or ContractRef.from_document(document) != reference:
            raise IntegrityError("An exact Validation source revision is unavailable.")
        return document

    def _scope(self, project_ref, level, target_ref, target_ids):
        try:
            validation_gate(level)
        except (KeyError, TypeError):
            raise IntegrityError("Select a supported Validation scope.") from None
        if target_ref is None:
            if level != "PRODUCT":
                raise IntegrityError("This Validation scope needs an exact target contract.")
            target_ref = project_ref
        else:
            target_ref = _reference(target_ref)
        expected = {"PRODUCT": "PROJECT", "MODULE": "MODULE"}.get(level, "WORKFLOW")
        if (
            project_ref.contract_type != "PROJECT"
            or target_ref.project_id != project_ref.project_id
            or target_ref.contract_type != expected
        ):
            raise IntegrityError("The Validation target has the wrong project or contract type.")
        if target_ids is None:
            if level == "PRODUCT":
                target_ids = [project_ref.project_id]
            elif level == "MODULE":
                target_ids = [self._read(target_ref)["payload"]["module_id"]]
        return {
            "level": level,
            "target_ids": _target_ids(target_ids),
            "target_contract_ref": target_ref.to_json(),
            "objective": f"Independently evaluate the approved {level.lower()} obligations.",
            "boundaries": [
                "Evaluate only the declared scope and exact sources.",
                "Report technical evidence and leave product acceptance to the owner.",
            ],
        }

    def _sources(self, project_ref, scope):
        events = self.store.list_events()

        def history(kind, project_id):
            for event in events:
                if event["contract_type"] == kind and event["project_id"] == project_id:
                    yield self._read(
                        ContractRef(event["contract_id"], event["revision_id"], kind, project_id)
                    )

        return derive_validation_obligations(
            project_ref, scope, self.store.get, self.store.resolve_active, history=history
        )

    def _interface_context(self, module, item):
        if item["provider_module_id"] == module["payload"]["module_id"]:
            provider = module
        else:
            consumer = next(
                row
                for row in module["payload"]["consumed_interfaces"]
                if row["provider_module_id"] == item["provider_module_id"]
                and row["interface_id"] == item["interface_id"]
                and row["required_interface_revision"] == item["interface_revision"]
            )
            provider = self._read(_reference(consumer["provider_contract_ref"]))
        interface = next(
            row
            for row in provider["payload"]["provided_interfaces"]
            if row["interface_id"] == item["interface_id"]
            and row["interface_revision"] == item["interface_revision"]
        )
        return {
            "declared_check": item,
            "provider_ref": ContractRef.from_document(provider).to_json(),
            "interface": interface,
        }

    def _row(self, documents, standard, reference, identifier, item, mandatory):
        methods = item.get("verification_methods", [])
        evidence = item.get("evidence_required", ["Independent check observation"])
        source_context = item
        if reference is None:
            source_context = standard["commandments"][identifier]
            criterion = source_context["description"]
            source = {
                "standard_rule_ref": {
                    "standard_id": "nukytera-standard",
                    "version": standard["standard_version"],
                    "rule_id": identifier,
                }
            }
            identity = ["STANDARD", identifier]
        else:
            criterion = item.get("criterion", item.get("description"))
            source = {"contract_ref": reference.to_json(), "obligation_id": identifier}
            identity = [reference.contract_type.value, reference.contract_id, identifier]
            if "interface_revision" in item:
                source_context = self._interface_context(documents[reference], item)
        if not isinstance(criterion, str) or not criterion.strip():
            raise IntegrityError("A scoped Validation obligation lacks a verifiable criterion.")
        return {
            "check_id": "check-" + digest(identity)[:32],
            "source_ref": source,
            "criterion": criterion,
            "gate_classification": "MANDATORY" if mandatory else "OPTIONAL",
            "verification_methods": methods,
            "required_evidence": evidence,
            "review_required": (
                reference is None
                or bool(item.get("standard_rule_ref"))
                or "interface_revision" in item
                or any("review" in kind.casefold() for kind in evidence)
            ),
            "source_context": source_context,
        }

    def derive(self, project_ref, level, *, target_ref=None, target_ids=None):
        """Build a detached draft directly from the active approved scope and Standard."""
        project_ref = _reference(project_ref)
        scope = self._scope(project_ref, level, target_ref, target_ids)
        standard = load_standard(self.policy_path, self.policy_schema_path)
        commandments = standard.get("commandments") if isinstance(standard, dict) else None
        if (
            not isinstance(commandments, dict)
            or standard.get("standard_version") != "0.1"
            or commandments.keys() != {"M1", "M2", "M3", "M4", "M5"}
            or any(
                not isinstance(rule, dict)
                or rule.get("required") is not True
                or not isinstance(rule.get("description"), str)
                or not rule["description"].strip()
                for rule in commandments.values()
            )
        ):
            raise IntegrityError("Validation requires all five enabled Standard Commandments.")
        sources, required, optional = self._sources(project_ref, scope)
        documents = {reference: self._read(reference) for reference in sources}
        for reference in documents:
            active = self.store.resolve_active(reference.contract_id)
            if active is None or ContractRef.from_document(active) != reference:
                raise ConflictError("Reconcile the active Validation sources before planning.")
        require_validation_interfaces(documents.values(), self.store.get, self.store.resolve_active)
        obligations = [
            self._row(documents, standard, reference, identifier, item, mandatory)
            for entries, mandatory in ((required, True), (optional, False))
            for (reference, identifier), item in entries.items()
        ]
        return {
            "validation_scope": scope,
            "source_contract_refs": [
                reference.to_json()
                for reference in sorted(
                    sources,
                    key=lambda ref: (ref.contract_type, ref.contract_id, ref.revision_id),
                )
            ],
            "obligations": sorted(obligations, key=lambda row: row["check_id"]),
            "standard_sha256": digest(standard),
        }

    def _verify_draft(self, draft, actor_id):
        if not isinstance(draft, dict) or set(draft) != {
            "validation_scope",
            "source_contract_refs",
            "obligations",
            "standard_sha256",
        }:
            raise IntegrityError("Use a draft derived from the approved Validation sources.")
        scope = draft["validation_scope"]
        if (
            not isinstance(scope, dict)
            or not {"level", "target_contract_ref", "target_ids"} <= scope.keys()
            or not isinstance(draft["source_contract_refs"], list)
        ):
            raise IntegrityError("The Validation draft has an invalid scope or source list.")
        sources = [_reference(raw) for raw in draft["source_contract_refs"]]
        projects = [ref for ref in sources if ref.contract_type == "PROJECT"]
        if len(projects) != 1:
            raise IntegrityError("A Validation plan needs one exact approved Project source.")
        current = self.derive(
            projects[0],
            scope["level"],
            target_ref=scope["target_contract_ref"],
            target_ids=scope["target_ids"],
        )
        if draft != current:
            raise ConflictError("The Validation draft does not match the complete current scope.")
        implementers = {
            self._read(ref)["metadata"]["provenance"]["actor_id"]
            for ref in sources
            if ref.contract_type in _IMPLEMENTATION_TYPES
        }
        if actor_id in implementers:
            raise AuthorityError("An implementation publisher cannot publish its own audit plan.")
        return current, projects[0], implementers

    @staticmethod
    def _ready_checks(draft, bindings, reviews, implementers):
        rows = {row["check_id"]: row for row in draft["obligations"]}
        if (
            not isinstance(bindings, dict)
            or not isinstance(reviews, dict)
            or rows.keys() != bindings.keys()
            or rows.keys() != reviews.keys()
        ):
            raise IntegrityError("Every exact matrix check requires a procedure and method review.")
        bindings = json.loads(canonical_json(bindings))
        reviews = json.loads(canonical_json(reviews))
        procedures, matrix, assessed = {}, [], {}
        for check_id, row in rows.items():
            binding = validate_binding(bindings[check_id])
            method = binding["method"]
            if row["verification_methods"] and method not in row["verification_methods"]:
                raise IntegrityError(f"{check_id} changes an approved verification method.")
            if not set(row["required_evidence"]).issubset(binding["required_evidence"]):
                raise IntegrityError(f"{check_id} omits required evidence.")
            if (row["review_required"] or "review" in method.casefold()) and not binding[
                "review_paths"
            ]:
                raise IntegrityError(f"{check_id} requires an explicit independent inspection.")
            if (
                method == _COMPOUND_METHOD or method.strip().casefold() in _COMMAND_METHODS
            ) and binding["command"] is None:
                raise IntegrityError(f"{check_id} requires an actual executed check.")
            review = reviews[check_id]
            if not isinstance(review, dict) or review.keys() != _REVIEW_KEYS:
                raise IntegrityError(f"{check_id} needs an exact method adequacy record.")
            reviewer = _identifier(review["actor_id"])
            if reviewer in implementers:
                raise AuthorityError("An implementation publisher cannot assess its own method.")
            criterion = {"source_ref": row["source_ref"], "criterion": row["criterion"]}
            if (
                review["criterion_sha256"] != digest(criterion)
                or review["binding_sha256"] != digest(binding)
                or not isinstance(review["rationale"], str)
                or not review["rationale"].strip()
                or len(review["rationale"]) > 4096
                or "\x00" in review["rationale"]
            ):
                raise IntegrityError(f"{check_id} has an unbound or unsupported adequacy review.")
            procedures[check_id] = binding
            assessed[check_id] = dict(review)
            matrix.append(
                {
                    "check_id": check_id,
                    **criterion,
                    "verification_method": method,
                    "required_evidence": binding["required_evidence"],
                    "gate_classification": row["gate_classification"],
                }
            )
        return procedures, assessed, matrix

    def publish(self, draft, bindings, reviews, *, actor_id, contract_id=None, previous=None):
        """Publish an intact VC and its separately persisted operational procedures."""
        actor_id = _identifier(actor_id)
        draft, project, implementers = self._verify_draft(draft, actor_id)
        bindings, reviews, matrix = self._ready_checks(draft, bindings, reviews, implementers)
        scope = draft["validation_scope"]
        if previous is not None:
            previous = _reference(previous)
            if (
                previous.contract_type != "VALIDATION"
                or previous.project_id != project.project_id
                or contract_id not in (None, previous.contract_id)
            ):
                raise IntegrityError("The preceding Validation plan has incompatible identity.")
            contract_id = previous.contract_id
        if contract_id is None:
            target = _reference(scope["target_contract_ref"])
            identity = [project.project_id, target.contract_id, scope["level"], scope["target_ids"]]
            contract_id = "validation-" + digest(identity)[:32]
        _identifier(contract_id)
        payload = {
            "validation_scope": scope,
            "source_contract_refs": draft["source_contract_refs"],
            "verification_matrix": matrix,
            "execution_plan": {
                "procedures": [
                    f"bindings-sha256:{digest(bindings)}",
                    *(f"{key}: {value['description']}" for key, value in bindings.items()),
                ],
                "environment": "Evaluate the exact retained candidate with isolated scratch data.",
                "tools": [],
                "conditions": [
                    f"standard-sha256:{draft['standard_sha256']}",
                    f"method-reviews-sha256:{digest(reviews)}",
                ],
                "dependencies": [],
            },
            "independence_policy": {
                "self_certification": False,
                "method": "Use separately reviewed exact procedures and independent observations.",
            },
            "evidence_requirements": [
                "Bind retained evidence to the exact plan, check, source, run and candidate."
            ],
            "gate_policy": {"gate": validation_gate(scope["level"])},
            "trigger_and_revalidation_policy": [
                "Use a new run after repair or target change. Revise a materially changed plan."
            ],
        }
        active = self.store.resolve_active(contract_id)
        version = 1
        if active is not None:
            active_ref = ContractRef.from_document(active)
            if (
                active_ref.contract_type != "VALIDATION"
                or active_ref.project_id != project.project_id
            ):
                raise ConflictError("The Validation plan identifier is already in use.")
            if _plan_content(active["payload"]) == _plan_content(payload):
                if (
                    previous in (None, active_ref)
                    or active["metadata"]["supersedes"] == previous.to_json()
                ):
                    self.repository.bindings(active_ref)
                    return active_ref
            if previous is not None and previous != active_ref:
                raise ConflictError("The preceding Validation plan is no longer active.")
            if previous is None:
                raise ConflictError("Changing a plan requires its exact active predecessor.")
            version = active["metadata"]["version"] + 1
        elif previous is not None:
            raise ConflictError("The preceding Validation plan is unavailable.")
        document = {
            "metadata": {
                "contract_id": contract_id,
                "revision_id": "validation-revision-" + uuid4().hex,
                "contract_type": "VALIDATION",
                "project_id": project.project_id,
                "version": version,
                "schema_version": "1.0",
                "status": "PUBLISHED",
                "created_at": datetime.now(UTC).isoformat(),
                "supersedes": None if previous is None else previous.to_json(),
                "standard_ref": {"standard_id": "nukytera-standard", "version": "0.1"},
                "provenance": {
                    "engine": "VALIDATION",
                    "actor_id": actor_id,
                    "source": "Independent operational audit planning",
                },
                "approval": None,
            },
            "payload": payload,
        }
        return self.repository.publish_plan(
            document, bindings, reviews=reviews, context=PublishContext("VALIDATION", actor_id)
        )
