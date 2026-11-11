# SPDX-License-Identifier: MPL-2.0
"""Deterministic ERC payloads from a coherent, independently collected snapshot."""

from copy import deepcopy
from hashlib import sha256

from corinthos.contracts import ContractRef, IntegrityError
from corinthos.contracts.model import ID_PATTERN, canonical_json
from corinthos.contracts.semantics import _module_checks, _obligation_key

from .rendering import safe_prose

_KINDS = {"CHECKPOINT", "MILESTONE", "PRODUCT", "HISTORY", "EVOLUTION"}
_RULES = ("M1", "M2", "M3", "M4", "M5")
_REQUEST_FIELDS = {
    "kind",
    "artifact_identity",
    "checkpoint_ids",
    "milestone_id",
    "audience",
    "objective",
}


def _reference(document):
    return ContractRef.from_document(document)


def _identifier(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise IntegrityError("Reporting requires valid scoped identifiers.")
    return value


def _scope(snapshot, request, project):
    if set(request) - _REQUEST_FIELDS:
        raise IntegrityError("A report request contains unsupported fields or authority claims.")
    kind = request.get("kind", "PRODUCT")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise IntegrityError("The requested report kind is unsupported.")
    identity = snapshot["artifact_identity"]
    if request.get("artifact_identity", identity) != identity:
        raise IntegrityError("The request and captured artifact identities differ.")
    checkpoints = request.get("checkpoint_ids", [])
    if not isinstance(checkpoints, (list, tuple)):
        raise IntegrityError("Checkpoint scope requires a sequence of identifiers.")
    checkpoints = [_identifier(value) for value in checkpoints]
    if len(set(checkpoints)) != len(checkpoints):
        raise IntegrityError("Checkpoint scope cannot repeat an identifier.")
    milestone = request.get("milestone_id")
    if milestone is not None:
        _identifier(milestone)
    if kind == "CHECKPOINT" and not checkpoints:
        raise IntegrityError("A Checkpoint report requires its complete checkpoint set.")
    if kind == "MILESTONE" and milestone is None:
        raise IntegrityError("A Milestone report requires an exact milestone.")
    if kind != "CHECKPOINT" and checkpoints:
        raise IntegrityError("Checkpoint lineage belongs to a Checkpoint report.")
    if kind != "MILESTONE" and milestone is not None:
        raise IntegrityError("Milestone lineage belongs to a Milestone report.")
    target = identity.get("build_id") or identity.get("snapshot_id") or identity.get("commit")
    return (
        {
            "target_id": _identifier(target or project.project_id),
            "audience": safe_prose(request.get("audience", "Project owner")),
            "as_of": snapshot["as_of"],
            "kind": kind,
            "objective": safe_prose(
                request.get("objective", "Review exact project facts, evidence and remaining gaps.")
            ),
            "boundaries": [
                f"{snapshot['mode']} source snapshot with exact publication and event cutoffs.",
                "Whole candidate identity " + canonical_json(identity) + ".",
                "Technical status, delivery, availability and human acceptance have separate authority.",
                "Historical results retain their own scope, date and complete artifact identity.",
            ],
        },
        sorted(checkpoints),
        milestone,
    )


def _sources(snapshot, scope, checkpoints, milestone):
    project = _reference(snapshot["project"])
    documents = {_reference(document): document for document in snapshot["documents"]}
    documents[project] = snapshot["project"]
    selected = snapshot["selected_results"]
    sources = {}

    def add(reference):
        document = documents.get(reference)
        if document is None or reference.project_id != project.project_id:
            raise IntegrityError("A report source is missing or belongs to another project.")
        existing = sources.get(reference.contract_id)
        if existing is not None and _reference(existing) != reference:
            raise IntegrityError("A report snapshot combines conflicting source revisions.")
        sources[reference.contract_id] = document
        return document

    add(project)
    expected_level = {"CHECKPOINT": "CHECKPOINT", "MILESTONE": "PLAYTEST_MILESTONE"}.get(
        scope["kind"], "PRODUCT"
    )
    expected_ids = {"CHECKPOINT": checkpoints, "MILESTONE": [milestone]}.get(
        scope["kind"], [project.project_id]
    )
    for result in selected:
        reference = _reference(result)
        if reference.contract_type != "VALIDATION_RESULT":
            raise IntegrityError("A report digest requires published Validation Results.")
        add(reference)
        payload = result["payload"]
        if payload["target_and_execution"]["artifact_identity"] != snapshot["artifact_identity"]:
            raise IntegrityError("A report digest cannot combine different candidate identities.")
        plan = add(ContractRef.from_json(payload["validation_plan_ref"]))
        plan_scope = plan["payload"]["validation_scope"]
        if plan_scope["level"] != expected_level or set(plan_scope["target_ids"]) != set(
            expected_ids
        ):
            raise IntegrityError("A report result does not cover its exact gate scope.")
        for raw in plan["payload"]["source_contract_refs"]:
            add(ContractRef.from_json(raw))
    if not selected:
        for raw in snapshot["active"].values():
            reference = ContractRef.from_json(raw)
            if reference.contract_type in {"WORKFLOW", "MODULE", "TECHNOLOGY_DECISION"}:
                add(reference)
    selected_refs = {_reference(item) for item in selected}
    historical = [
        document
        for document in snapshot["documents"]
        if _reference(document).contract_type == "VALIDATION_RESULT"
        and _reference(document).project_id == project.project_id
        and _reference(document) not in selected_refs
    ]
    for document in historical:
        # Only the immutable result joins the trail, not its conflicting source closure.
        add(_reference(document))
    requests = {}
    for document in snapshot["documents"]:
        reference = _reference(document)
        if (
            reference.contract_type == "PROJECT_REVISION_REQUEST"
            and reference.project_id == project.project_id
            and document["metadata"]["version"]
            > requests.get(reference.contract_id, {}).get("metadata", {}).get("version", 0)
        ):
            requests[reference.contract_id] = document
    for document in requests.values():
        add(_reference(document))
    return documents, list(sources.values()), historical + list(requests.values())


def _evidence(snapshot):
    allowed = {
        item["evidence_id"]: item
        for result in snapshot["selected_results"]
        for item in result["payload"]["evidence_refs"]
    }
    verified = {}
    for observation in snapshot["evidence"]:
        item = observation["ref"]
        if allowed.get(item["evidence_id"]) != item:
            raise IntegrityError("Report evidence differs from its selected Validation Result.")
        if observation["state"] == "VERIFIED":
            verified[item["evidence_id"]] = deepcopy(item)
    return list(verified.values())


def _technical(snapshot):
    gates = snapshot["gates"]
    selected = {_reference(document) for document in snapshot["selected_results"]}
    for gate in gates:
        raw = gate.get("result_ref")
        backed = raw is not None and ContractRef.from_json(raw) in selected
        if backed and gate["eligibility"] == "BLOCKED" and gate["recorded_state"] == "BLOCKED":
            return "BLOCKED"
    if gates and all(
        gate["eligibility"] == gate["recorded_state"] == "SATISFIED"
        and gate.get("result_ref") is not None
        and ContractRef.from_json(gate["result_ref"]) in selected
        for gate in gates
    ):
        return "VALIDATED"
    return "NOT_VERIFIED"


def _quality(snapshot, evidence, documents):
    quality = {rule: {"evidence_ids": [], "gaps": []} for rule in _RULES}
    indexed = {item["evidence_id"]: item for item in evidence}
    for result in snapshot["selected_results"]:
        for check in result["payload"]["check_results"]:
            reference, rule = _obligation_key(check["source_ref"])
            if reference is not None and reference.contract_type == "MODULE":
                source = documents[reference]["payload"]
                module_check = _module_checks(source).get(rule, {})
                rule = (module_check.get("standard_rule_ref") or {}).get("rule_id")
                reference = None
            if reference is not None or rule not in quality:
                continue
            ids = [value for value in check["evidence_ids"] if value in indexed]
            if any(indexed[value]["source_ref"] != check["source_ref"] for value in ids):
                raise IntegrityError("A Commandment check and its evidence have different sources.")
            quality[rule]["evidence_ids"].extend(ids)
            if check["status"] != "CONFORMANT" or not ids:
                outcome = check["status"] or "NOT_APPLICABLE"
                quality[rule]["gaps"].append(
                    f"{check['check_id']} recorded {outcome} in {_reference(result).revision_id}. "
                    + safe_prose(check["rationale"])
                )
    for rule, observation in quality.items():
        if not observation["evidence_ids"]:
            observation["gaps"].append(
                f"No verified {rule} evidence is indexed for this exact scoped digest."
            )
        observation["evidence_ids"] = sorted(set(observation["evidence_ids"]))
        observation["gaps"] = sorted(set(observation["gaps"]))
    return quality


def _metrics(results):
    metrics = []
    for result in results:
        checks = result["payload"]["check_results"]
        if not checks:
            continue
        reference = _reference(result).to_json()
        for status in ("CONFORMANT", "NONCONFORMANT", "NOT_VERIFIED", None):
            label = status or "NOT_APPLICABLE"
            metrics.append(
                {
                    "name": f"{label.lower()}_checks",
                    "definition": f"{label} check outcomes in this exact VRC divided by its total checks.",
                    "value": sum(item["status"] == status for item in checks),
                    "denominator": len(checks),
                    "source_ref": reference,
                }
            )
    return metrics


def _result_note(result, *, historical):
    reference = _reference(result)
    payload = result["payload"]
    execution = payload["target_and_execution"]
    checks = payload["check_results"]
    counts = ", ".join(
        f"{sum(item['status'] == status for item in checks)} {status}"
        for status in ("CONFORMANT", "NONCONFORMANT", "NOT_VERIFIED")
    )
    return (
        f"{'Historical' if historical else 'Effective'} VRC {reference.contract_id}@{reference.revision_id}, "
        f"run {execution['validation_run_id']}, created {result['metadata']['created_at']}, "
        f"started {execution['started_at']}, finished {execution['finished_at'] or 'unrecorded'}, "
        f"artifact {canonical_json(execution['artifact_identity'])}, "
        f"execution {execution['status']}, scope {payload['gate_assessment']['scope']}, "
        f"gate {payload['gate_assessment']['gate']}, recorded gate {payload['gate_assessment']['state']}, "
        f"{counts}. This result retains its own candidate and scope."
    )


def _contract_history(snapshot):
    project = _reference(snapshot["project"]).project_id
    kinds = {
        "PROJECT",
        "WORKFLOW",
        "MODULE",
        "TECHNOLOGY_DECISION",
        "VALIDATION",
        "PROJECT_REVISION_REQUEST",
    }
    documents = sorted(
        (
            document
            for document in snapshot["documents"]
            if (ref := _reference(document)).project_id == project and ref.contract_type in kinds
        ),
        key=lambda document: (
            document["metadata"]["created_at"],
            document["metadata"]["contract_id"],
            document["metadata"]["version"],
            document["metadata"]["revision_id"],
        ),
    )
    notes = []
    for document in documents:
        reference = _reference(document)
        metadata, payload = document["metadata"], document["payload"]
        digest = sha256(canonical_json(document).encode("utf-8")).hexdigest()
        notes.append(
            f"Contract lineage {canonical_json(reference.to_json())}, version {metadata['version']}, "
            f"created {metadata['created_at']}, status {metadata['status']}, "
            f"supersedes {canonical_json(metadata['supersedes'])}, "
            f"recorded publication approval {canonical_json(metadata['approval'])}, "
            f"canonical SHA-256 {digest}. Historical publication authority is not a new product acceptance."
        )
        if reference.contract_type == "PROJECT":
            notes.extend(
                f"Project decision {item['decision_id']} in {reference.revision_id}: "
                + safe_prose(item["decision"])
                + " Rationale: "
                + safe_prose(item["rationale"])
                for item in payload["negotiated_decisions"]
            )
        elif reference.contract_type == "TECHNOLOGY_DECISION":
            notes.append(
                f"Technology decision in {reference.revision_id}: "
                + safe_prose(payload["decision_scope"]["subject"])
                + "; selected option "
                + safe_prose(canonical_json(payload["selected_option"]))
                + "; rationale "
                + safe_prose(payload["decision_rationale"])
            )
        elif reference.contract_type == "MODULE":
            notes.append(
                f"Module {payload['module_id']} in {reference.revision_id}: "
                + safe_prose(payload["purpose_and_boundaries"]["purpose"])
            )
        elif reference.contract_type == "WORKFLOW":
            notes.append(
                f"Workflow plan {reference.revision_id}, Project {canonical_json(payload['project_contract_ref'])}, "
                f"checkpoints {canonical_json([item['checkpoint_id'] for item in payload['checkpoints']])}, "
                f"milestones {canonical_json([item['milestone_id'] for item in payload['playtest_milestones']])}."
            )
        elif reference.contract_type == "PROJECT_REVISION_REQUEST":
            notes.append(
                f"Project revision request {payload['request_id']} in {reference.revision_id}, "
                f"base {canonical_json(payload['base_contract_version'])}, "
                f"affected proposals {canonical_json(payload['affected_proposals'])}. "
                "Publication records a proposed change; approval or adoption is not inferred."
            )
            notes.extend(
                f"PRR {payload['request_id']} inconsistency {item['kind']}: "
                + safe_prose(item["description"])
                + "; confirmed facts "
                + safe_prose(canonical_json(item["confirmed_facts"]))
                + "; uncertainties "
                + safe_prose(canonical_json(item["uncertainties"]))
                for item in payload["inconsistencies"]
            )
    return notes


def _review_history(snapshot):
    notes = []
    for document in snapshot.get("review_documents", []):
        reference = _reference(document)
        metadata, payload = document["metadata"], document["payload"]
        approval = metadata["approval"]
        lineage, scope = payload["version_and_delivery_lineage"], payload["report_scope"]
        if (
            reference.contract_type != "EVIDENCE_REPORT"
            or reference.project_id != _reference(snapshot["project"]).project_id
            or metadata["status"] != "PUBLISHED"
            or lineage["project_id"] != reference.project_id
            or lineage["delivery"] != "DELIVERED"
            or lineage["acceptance"] not in {"ACCEPTED", "WITH_RESERVATIONS"}
            or approval is None
            or approval["kind"] != "HUMAN"
            or payload["feedback_and_acceptance"]["review_approval_id"] != approval["approval_id"]
        ):
            raise IntegrityError(
                "Historical product reviews require exact recorded human authority."
            )
        digest = sha256(canonical_json(document).encode("utf-8")).hexdigest()
        notes.append(
            f"Historical human-reviewed ERC {canonical_json(reference.to_json())}, "
            f"created {metadata['created_at']}, supersedes {canonical_json(metadata['supersedes'])}, "
            f"canonical SHA-256 {digest}, recorded approval {canonical_json(approval)}, "
            f"report kind {scope['kind']}, target {scope['target_id']}, as_of {scope['as_of']}, "
            "original version and delivery lineage "
            + safe_prose(canonical_json(lineage))
            + ". This review belongs only to that recorded report and product lineage; "
            "it does not review the new ordinary technical report."
        )
        notes.extend(
            f"Historical feedback in {reference.revision_id}: " + safe_prose(canonical_json(item))
            for item in payload["feedback_and_acceptance"]["feedback"]
        )
    return notes


def _operation_note(operation):
    fields = (
        "type",
        "kind",
        "sequence",
        "occurred_at",
        "action",
        "state",
        "checkpoint_id",
        "event_id",
        "turn_id",
        "session_id",
        "execution_id",
        "attempt_id",
        "run_id",
        "previous_attempt_id",
        "previous_run_id",
        "reason",
        "summary",
        "tests_passed",
        "observed_checks",
        "started_at",
        "finished_at",
    )
    values = [f"{key}={safe_prose(operation[key])}" for key in fields if key in operation]
    if operation.get("details"):
        values.append("projected_details=" + safe_prose(canonical_json(operation["details"])))
    return "Captured operational observation " + ", ".join(values) + "." if values else None


def _documentation(snapshot):
    candidate = snapshot.get("manifest", {}).get("candidate")
    files = (candidate or {}).get("inventory", {}).get("files", {})
    paths = sorted(path for path in files if path.lower().endswith((".md", ".rst")))
    return [
        "Candidate documentation "
        + safe_prose(path)
        + f", SHA-256 {files[path]['sha256']}, snapshot {snapshot['artifact_identity'].get('snapshot_id', 'unrecorded')}. "
        "The candidate inventory identifies this source independently of Validation evidence."
        for path in paths
    ]


def _executable_observations(snapshot):
    notes, gaps = [], []
    for result in snapshot["selected_results"]:
        run = result["payload"]["target_and_execution"]["validation_run_id"]
        rows = [
            item
            for item in snapshot["evidence"]
            if item["state"] == "VERIFIED"
            and item["ref"]["execution_context"]["validation_run_id"] == run
            and "observation" in item
        ]
        if not rows:
            gaps.append(
                f"Executable-observation telemetry was not captured for {_reference(result).revision_id}."
            )
            continue
        backed = {item["ref"]["check_id"] for item in rows if item["observation"]["command_backed"]}
        shared = {
            item["ref"]["check_id"]
            for item in rows
            if item["observation"]["command_backed"] and item["observation"]["command_shared"]
        }
        denominator = len(result["payload"]["check_results"])
        notes.append(
            f"VRC {_reference(result).revision_id}, run {run}, has {len(backed)}/{denominator} "
            f"checks with command-backed observations in verified retained envelopes. "
            f"The count of checks using explicitly shared same-run command observations is {len(shared)}. "
            "These are check observations, not a count of independent command executions."
        )
    return notes, gaps


def compose(snapshot, request):
    """Compose one truthful payload without reading or changing source state."""
    project = _reference(snapshot["project"])
    if project.contract_type != "PROJECT":
        raise IntegrityError("A report needs its exact Project Contract.")
    scope, checkpoints, milestone = _scope(snapshot, request, project)
    documents, sources, changes = _sources(snapshot, scope, checkpoints, milestone)
    evidence = _evidence(snapshot)
    technical = _technical(snapshot)
    delivery = snapshot.get("delivery", {})
    delivered = delivery.get("delivery", "NOT_DELIVERED")
    available = delivery.get("availability", False)
    if delivered not in {"DELIVERED", "NOT_DELIVERED"} or type(available) is not bool:
        raise IntegrityError("Delivery facts have unsupported states.")
    if (delivered == "DELIVERED" or available) and not delivery.get("provenance"):
        raise IntegrityError("Delivery or availability needs concrete verified provenance.")
    gaps = [safe_prose(value) for value in (*snapshot["gaps"], *delivery.get("gaps", []))]
    if not delivery:
        gaps.append("Product version, delivery and availability have no recorded verified source.")
    gaps.extend(
        safe_prose(item["reason"]) for item in snapshot["evidence"] if item["state"] != "VERIFIED"
    )
    gaps.extend(
        safe_prose(gate["reason"])
        for gate in snapshot["gates"]
        if gate["eligibility"] == "NOT_VERIFIED" and gate.get("reason")
    )
    gaps.append("Token use, universal quality scores and unrecorded telemetry are not inferred.")
    gaps.append(
        "Historical human reviews retain their original product lineage; this ordinary technical report carries no new human acceptance review."
        if snapshot.get("review_documents")
        else "No supported Feedback Tracker or exact-product human acceptance review was captured for this ordinary technical report."
    )
    if scope["kind"] in {"HISTORY", "EVOLUTION"}:
        gaps.append(
            "The report describes recorded history and does not operate an evolution lifecycle."
        )
    notes = [_result_note(result, historical=False) for result in snapshot["selected_results"]]
    notes.extend(
        _result_note(result, historical=True)
        for result in changes
        if _reference(result).contract_type == "VALIDATION_RESULT"
    )
    notes.extend(_contract_history(snapshot))
    notes.extend(_review_history(snapshot))
    observation_notes, observation_gaps = _executable_observations(snapshot)
    notes.extend(observation_notes)
    gaps.extend(observation_gaps)
    documentation = _documentation(snapshot)
    notes.extend(documentation)
    if not documentation:
        gaps.append("Versioned candidate documentation paths are unavailable in this capture.")
    notes.extend(
        note for operation in snapshot["operations"] if (note := _operation_note(operation))
    )
    decisions = {
        document["metadata"]["approval"]["approval_id"]
        for document in sources
        if document["metadata"]["approval"] is not None
    }
    decisions.update(
        item["decision_id"] for item in snapshot["project"]["payload"]["negotiated_decisions"]
    )
    selected = snapshot["selected_results"]
    blockers = sorted(
        {
            identifier
            for result in selected
            for identifier in result["payload"]["gate_assessment"]["blocking_check_ids"]
        }
    )
    summary = (
        f"{technical} at the captured cutoff. {len(selected)} effective Validation Results "
        f"cover {sum(len(result['payload']['check_results']) for result in selected)} check observations "
        f"with {len(blockers)} blocking check IDs. Counts preserve each VRC denominator. "
        "Workflow completion history and present technical eligibility are reported separately."
    )
    return {
        "report_scope": scope,
        "source_refs": [_reference(document).to_json() for document in sources],
        "version_and_delivery_lineage": {
            "project_id": project.project_id,
            "product_version": safe_prose(delivery.get("product_version", "UNRECORDED")),
            "build_id": snapshot["artifact_identity"].get("build_id"),
            "milestone_id": milestone,
            "checkpoint_ids": checkpoints,
            "previous_version": (
                safe_prose(delivery["previous_version"])
                if delivery.get("previous_version") is not None
                else None
            ),
            "technical_validation": technical,
            "delivery": delivered,
            "availability": available,
            "acceptance": "NOT_REVIEWED",
        },
        "execution_and_validation_digest": {
            "validation_result_refs": [_reference(document).to_json() for document in selected],
            "summary": summary,
            "blocked_check_ids": blockers,
        },
        "engineering_quality_and_documentation": _quality(snapshot, evidence, documents),
        "decisions_and_change_history": {
            "decision_ids": sorted(decisions),
            "change_refs": [_reference(document).to_json() for document in changes],
            "notes": [safe_prose(note) for note in notes],
        },
        "artifact_and_evidence_index": evidence,
        "feedback_and_acceptance": {"review_approval_id": None, "feedback": []},
        "risks_metrics_and_next_actions": {
            "risks": sorted(set(gaps)),
            "metrics": _metrics(selected),
            "next_actions": [
                "Validation owns any required verification or proof-integrity follow-up.",
                "Workflow owns repair and resubmission within approved obligations.",
                "The project owner retains product decisions and human acceptance.",
            ],
        },
    }
