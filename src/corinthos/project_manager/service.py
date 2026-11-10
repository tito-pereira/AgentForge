# SPDX-License-Identifier: MPL-2.0
"""Human-led Project negotiation, independent of terminal presentation."""

from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from time import time
from uuid import uuid4

from corinthos.contracts import ContractRef, ContractStore, validate_schema
from corinthos.contracts.model import ID_PATTERN, ConflictError, IntegrityError, canonical_json
from corinthos.contracts.schema import _validator
from corinthos.contracts.semantics import validate_semantics

from .repository import SessionRepository

_CLOSED = {"PUBLISHED", "CANCELLED", "CLOSED_UNCHANGED", "RETURNED"}
_PROPOSAL_STATES = {"ACCEPTED", "REJECTED", "WITHDRAWN", "NEEDS_CLARIFICATION"}
_PLACEHOLDERS = {"tbd", "todo", "unknown", "to be decided", "to be defined", "?"}
_MAX_TEXT = 20_000
_STATES = _CLOSED | {
    "DRAFT",
    "NEEDS_CLARIFICATION",
    "READY_FOR_REVIEW",
    "AWAITING_EXPLICIT_APPROVAL",
    "PUBLISHING",
    "DEFERRED",
}


def _identifier(prefix):
    return f"{prefix}-{uuid4().hex}"


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise IntegrityError("Enter nonempty text of at most 20,000 characters.")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise IntegrityError("Text contains unsupported control characters.")
    return value.strip()


def _texts(value):
    if not isinstance(value, list) or len(value) > 200:
        raise IntegrityError("Provide a list of at most 200 text items.")
    return [_text(item) for item in value]


def _identifiers(value):
    if (
        not isinstance(value, list)
        or len(value) > 200
        or any(not _valid_id(item) for item in value)
        or len(set(value)) != len(value)
    ):
        raise IntegrityError("Proposal links require distinct valid identifiers.")
    return list(value)


def _fields(operation, required, optional=()):
    if set(operation) - {"action", *required, *optional} or not set(required) <= operation.keys():
        raise IntegrityError("The negotiation action has invalid fields.")


def _claim(snapshot, supplied, prefix, existing=()):
    identifier = _identifier(prefix) if supplied is None else supplied
    if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
        raise IntegrityError("The negotiation item has an invalid identifier.")
    if identifier in snapshot["used_ids"] and identifier not in existing:
        raise IntegrityError("A negotiation identifier cannot be reused for another item.")
    if identifier not in snapshot["used_ids"]:
        snapshot["used_ids"].append(identifier)
    return identifier


def _replace(items, key, item):
    for index, current in enumerate(items):
        if current[key] == item[key]:
            items[index] = item
            return
    items.append(item)


def _remove(items, key, identifier):
    if not any(item[key] == identifier for item in items):
        raise IntegrityError("The negotiation item does not exist.")
    items[:] = [item for item in items if item[key] != identifier]


def _payload_ids(payload):
    return [
        *(item["requirement_id"] for item in payload["requirements"]),
        *(item["constraint_id"] for item in payload["constraints"]),
        *(item["criterion_id"] for item in payload["success_criteria"]),
        *(
            criterion["criterion_id"]
            for item in payload["requirements"]
            for criterion in item["acceptance_criteria"]
        ),
        *(item["proposal_id"] for item in payload["structural_proposals"]),
        *(item["decision_id"] for item in payload["negotiated_decisions"]),
    ]


def _normalized(text):
    return " ".join(text.casefold().split())


def _shape(condition):
    if not condition:
        raise ValueError


def _valid_id(value):
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def _draft_payload(payload):
    """Reuse the Kernel shape checks, permitting incomplete draft collections."""
    document = {
        "metadata": {
            "contract_id": "draft-check",
            "revision_id": "draft-check-r1",
            "contract_type": "PROJECT",
            "project_id": "draft-check",
            "version": 1,
            "schema_version": "1.0",
            "status": "DRAFT",
            "created_at": "2026-01-01T00:00:00Z",
            "supersedes": None,
            "standard_ref": {"standard_id": "nukytera-standard", "version": "0.1"},
            "provenance": {
                "engine": "PROJECT_MANAGER",
                "actor_id": "draft-check",
                "source": "Operational draft shape check",
            },
            "approval": None,
        },
        "payload": payload,
    }
    for error in _validator("PROJECT", "1.0").iter_errors(document):
        path = tuple(error.absolute_path)
        incomplete = path in {
            ("payload", "requirements"),
            ("payload", "success_criteria"),
            ("payload", "scope", "included"),
        }
        incomplete = incomplete or (
            len(path) == 4
            and path[:2] == ("payload", "requirements")
            and path[-1] == "acceptance_criteria"
        )
        _shape(error.validator == "minItems" and incomplete)


def _validate_snapshot(snapshot):
    """Reject malformed operational state before presentation, editing or recovery."""
    try:
        required = {
            "session_id",
            "project_id",
            "contract_id",
            "version",
            "state",
            "base_ref",
            "source_prr",
            "request_id",
            "reason",
            "payload",
            "proposals",
            "questions",
            "feasibility",
            "review",
            "published_ref",
            "used_ids",
            "created_at",
        }
        _shape(type(snapshot) is dict and set(snapshot) == required)
        _shape(all(_valid_id(snapshot[key]) for key in ("session_id", "project_id", "contract_id")))
        _shape(type(snapshot["version"]) is int and snapshot["version"] >= 1)
        _shape(isinstance(snapshot["state"], str) and snapshot["state"] in _STATES)
        _text(snapshot["reason"])
        created = datetime.fromisoformat(snapshot["created_at"])
        _shape(created.tzinfo is not None)
        _draft_payload(snapshot["payload"])
        for key, kind in (
            ("base_ref", "PROJECT"),
            ("source_prr", "PROJECT_REVISION_REQUEST"),
            ("published_ref", "PROJECT"),
        ):
            if snapshot[key] is not None:
                reference = ContractRef.from_json(snapshot[key])
                _shape(
                    reference.project_id == snapshot["project_id"]
                    and reference.contract_type == kind
                )
                if kind == "PROJECT":
                    _shape(reference.contract_id == snapshot["contract_id"])
        _shape((snapshot["request_id"] is None) == (snapshot["source_prr"] is None))
        if snapshot["request_id"] is not None:
            _shape(_valid_id(snapshot["request_id"]) and snapshot["base_ref"] is not None)
        _shape(
            type(snapshot["used_ids"]) is list
            and all(_valid_id(item) for item in snapshot["used_ids"])
        )
        _shape(type(snapshot["proposals"]) is dict)
        for identifier, record in snapshot["proposals"].items():
            _shape(_valid_id(identifier) and type(record) is dict)
            _shape(
                {"proposal", "status", "alternatives", "scope"} <= record.keys()
                and not record.keys()
                - {"proposal", "status", "alternatives", "scope", "last_decision"}
            )
            _shape(
                isinstance(record["status"], str)
                and record["status"] in _PROPOSAL_STATES | {"PROPOSED"}
            )
            _texts(record["alternatives"])
            _text(record["scope"])
            proposal = record["proposal"]
            _shape(type(proposal) is dict and proposal.get("proposal_id") == identifier)
            probe = deepcopy(snapshot["payload"])
            probe["structural_proposals"] = [proposal]
            probe["negotiated_decisions"] = (
                [record["last_decision"]] if "last_decision" in record else []
            )
            _draft_payload(probe)
        _shape(type(snapshot["questions"]) is list and type(snapshot["feasibility"]) is list)
        for question in snapshot["questions"]:
            _shape(type(question) is dict and set(question) == {"question_id", "text", "answer"})
            _shape(_valid_id(question["question_id"]))
            _text(question["text"])
            if question["answer"] is not None:
                _text(question["answer"])
        for finding in snapshot["feasibility"]:
            _shape(
                type(finding) is dict
                and set(finding) == {"assessment_id", "description", "status", "evidence"}
            )
            _shape(
                _valid_id(finding["assessment_id"])
                and isinstance(finding["status"], str)
                and finding["status"] in {"NOT_VERIFIED", "ASSUMPTION", "CONFIRMED"}
            )
            _text(finding["description"])
            _texts(finding["evidence"])
            _shape(finding["status"] != "CONFIRMED" or bool(finding["evidence"]))
        review = snapshot["review"]
        if review is not None:
            _shape(type(review) is dict and set(review) == {"document", "sha256", "expires_at"})
            _shape(
                type(review["expires_at"]) in (int, float)
                and isfinite(review["expires_at"])
                and review["expires_at"] > 0
            )
            validate_schema(review["document"])
            reference = ContractRef.from_document(review["document"])
            _shape(
                reference.contract_type == "PROJECT"
                and reference.project_id == snapshot["project_id"]
                and reference.contract_id == snapshot["contract_id"]
            )
            _shape(
                review["document"]["metadata"]["status"] == "PUBLISHED"
                and review["document"]["metadata"]["supersedes"] == snapshot["base_ref"]
                and review["document"]["payload"] == snapshot["payload"]
            )
            _shape(
                review["sha256"]
                == sha256(canonical_json(review["document"]).encode("utf-8")).hexdigest()
            )
        if snapshot["state"] in {"AWAITING_EXPLICIT_APPROVAL", "PUBLISHING", "PUBLISHED"}:
            _shape(review is not None)
        if snapshot["state"] == "PUBLISHED":
            _shape(
                snapshot["published_ref"] == ContractRef.from_document(review["document"]).to_json()
            )
        else:
            _shape(snapshot["published_ref"] is None)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise IntegrityError(
            "The stored negotiation state is invalid. Preserve the private database for recovery."
        ) from None
    return snapshot


class ProjectManager:
    """Persist structured human choices and freeze exact Kernel publication candidates."""

    def __init__(self, project_root, assistance=None):
        self.store = ContractStore(project_root)
        self.repository = SessionRepository(self.store)
        self.assistance = assistance

    def get(self, session_id):
        snapshot = _validate_snapshot(self.repository.get(session_id))
        if snapshot["state"] != "PUBLISHING":
            return snapshot
        from .approval import recover_publication

        return recover_publication(self, snapshot)

    def list(self):
        return [_validate_snapshot(snapshot) for snapshot in self.repository.list()]

    def history(self, session_id):
        self.get(session_id)
        history = self.repository.history(session_id)
        for turn in history:
            _validate_snapshot(turn["snapshot"])
        return history

    def _new(self, payload, *, actor_id, base=None, reason, prr=None):
        metadata = None if base is None else base["metadata"]
        reference = None if base is None else ContractRef.from_document(base).to_json()
        snapshot = {
            "session_id": _identifier("session"),
            "project_id": _identifier("project") if metadata is None else metadata["project_id"],
            "contract_id": _identifier("intent") if metadata is None else metadata["contract_id"],
            "state": "DRAFT",
            "base_ref": reference,
            "source_prr": None if prr is None else ContractRef.from_document(prr).to_json(),
            "request_id": None if prr is None else prr["payload"]["request_id"],
            "reason": _text(reason),
            "payload": deepcopy(payload),
            "proposals": {
                item["proposal_id"]: {
                    "proposal": deepcopy(item),
                    "status": "ACCEPTED",
                    "alternatives": [],
                    "scope": "Existing approved specification",
                }
                for item in payload["structural_proposals"]
            },
            "questions": [],
            "feasibility": [],
            "review": None,
            "published_ref": None,
            "used_ids": _payload_ids(payload),
            "created_at": datetime.now(UTC).isoformat(),
        }
        return self.repository.create(snapshot, actor_id=actor_id, action="SESSION_STARTED")

    def start(self, idea, *, actor_id):
        payload = {
            "vision": _text(idea),
            "scope": {"included": [], "excluded": [], "assumptions": [], "risks": []},
            "requirements": [],
            "constraints": [],
            "success_criteria": [],
            "structural_proposals": [],
            "negotiated_decisions": [],
        }
        return self._new(payload, actor_id=actor_id, reason="Initial project negotiation")

    def _base(self, reference):
        ref = reference if isinstance(reference, ContractRef) else ContractRef.from_json(reference)
        if ref.contract_type != "PROJECT":
            raise IntegrityError("A negotiation base must be an exact Project Contract reference.")
        base = self.store.get(ref)
        if base is None:
            raise IntegrityError("The approved Project Contract base does not exist.")
        active = self.store.resolve_active(ref.contract_id)
        if active is None or ContractRef.from_document(active) != ref:
            raise ConflictError(
                "The Project Contract base is stale. Explicit reconciliation is required."
            )
        return base

    def revise(self, base_ref, reason, *, actor_id):
        base = self._base(base_ref)
        return self._new(base["payload"], actor_id=actor_id, base=base, reason=reason)

    def receive_prr(self, prr_ref, triage, *, actor_id):
        ref = prr_ref if isinstance(prr_ref, ContractRef) else ContractRef.from_json(prr_ref)
        if ref.contract_type != "PROJECT_REVISION_REQUEST":
            raise IntegrityError("PRR intake requires an exact published revision request.")
        prr = self.store.get(ref)
        if prr is None or prr["payload"]["project_id"] != ref.project_id:
            raise IntegrityError(
                "The revision request does not identify a matching published project."
            )
        base = self._base(prr["payload"]["base_contract_version"])
        if base["metadata"]["project_id"] != ref.project_id:
            raise IntegrityError("The revision request belongs to another project.")
        if not isinstance(triage, str) or triage not in {
            "STRUCTURAL",
            "NEEDS_CLARIFICATION",
            "RETURN",
        }:
            raise IntegrityError(
                "Choose structural negotiation, clarification, or return for technical recovery."
            )
        snapshot = self._new(
            base["payload"],
            actor_id=actor_id,
            base=base,
            reason="Project Revision Request intake",
            prr=prr,
        )
        if triage == "RETURN":
            return self._transition(
                snapshot, snapshot["version"], "RETURNED", actor_id, "PRR_RETURNED"
            )
        if triage == "NEEDS_CLARIFICATION":
            snapshot["questions"].append(
                {
                    "question_id": _identifier("question"),
                    "text": "Clarify the structural incompatibility and its evidence.",
                    "answer": None,
                }
            )
            snapshot["state"] = "NEEDS_CLARIFICATION"
            return self.repository.save(
                snapshot["session_id"],
                snapshot["version"],
                snapshot,
                actor_id=actor_id,
                action="PRR_CLARIFICATION_REQUESTED",
            )
        return snapshot

    def _editable(self, session_id, expected_version):
        snapshot = self.get(session_id)
        if snapshot["version"] != expected_version:
            raise ConflictError("The negotiation changed. Reload its current version.")
        if snapshot["state"] in _CLOSED:
            raise ConflictError("This negotiation is closed. Start a new revision session.")
        if snapshot["base_ref"] is not None:
            self._base(snapshot["base_ref"])
        return snapshot

    def edit(self, session_id, expected_version, operation, *, actor_id):
        snapshot = self._editable(session_id, expected_version)
        if not isinstance(operation, dict) or not isinstance(operation.get("action"), str):
            raise IntegrityError("Provide a structured negotiation action.")
        action = operation["action"]
        handlers = {
            "set_vision": self._vision,
            "set_scope": self._scope,
            "upsert_requirement": self._requirement,
            "remove_requirement": self._remove_obligation,
            "upsert_constraint": self._simple_obligation,
            "remove_constraint": self._remove_obligation,
            "upsert_success_criterion": self._simple_obligation,
            "remove_success_criterion": self._remove_obligation,
            "propose": self._proposal,
            "decide_proposal": self._decide,
            "set_question": self._question,
            "record_feasibility": self._feasibility,
            "resume": self._resume,
        }
        if action not in handlers:
            raise IntegrityError("The negotiation action is unsupported.")
        handlers[action](snapshot, operation)
        self._bounded(snapshot, final=False)
        snapshot["review"] = None
        snapshot["state"] = "NEEDS_CLARIFICATION" if self._issues(snapshot) else "DRAFT"
        _validate_snapshot(snapshot)
        return self.repository.save(
            session_id, expected_version, snapshot, actor_id=actor_id, action=action.upper()
        )

    @staticmethod
    def _vision(snapshot, operation):
        _fields(operation, {"text"})
        snapshot["payload"]["vision"] = _text(operation["text"])

    @staticmethod
    def _scope(snapshot, operation):
        _fields(operation, {"section", "items"})
        if (
            not isinstance(operation["section"], str)
            or operation["section"] not in snapshot["payload"]["scope"]
        ):
            raise IntegrityError("Choose included scope, exclusions, assumptions, or risks.")
        snapshot["payload"]["scope"][operation["section"]] = _texts(operation["items"])

    @staticmethod
    def _requirement(snapshot, operation):
        _fields(operation, {"description", "acceptance_criteria"}, {"requirement_id"})
        items = snapshot["payload"]["requirements"]
        existing = {item["requirement_id"]: item for item in items}
        identifier = _claim(snapshot, operation.get("requirement_id"), "requirement", existing)
        criteria = operation["acceptance_criteria"]
        if not isinstance(criteria, list) or len(criteria) > 200:
            raise IntegrityError("Provide at most 200 acceptance criteria for a requirement.")
        old_criteria = {
            item["criterion_id"]
            for item in existing.get(identifier, {}).get("acceptance_criteria", [])
        }
        result = []
        for item in criteria:
            if (
                not isinstance(item, dict)
                or set(item) - {"criterion_id", "criterion"}
                or "criterion" not in item
            ):
                raise IntegrityError(
                    "An acceptance criterion requires its text and optional stable identifier."
                )
            result.append(
                {
                    "criterion_id": _claim(
                        snapshot, item.get("criterion_id"), "criterion", old_criteria
                    ),
                    "criterion": _text(item["criterion"]),
                }
            )
        if len({item["criterion_id"] for item in result}) != len(result):
            raise IntegrityError("Acceptance criterion identifiers must be unique.")
        _replace(
            items,
            "requirement_id",
            {
                "requirement_id": identifier,
                "description": _text(operation["description"]),
                "acceptance_criteria": result,
            },
        )

    @staticmethod
    def _simple_obligation(snapshot, operation):
        constraint = operation["action"] == "upsert_constraint"
        collection, key, text_key = (
            ("constraints", "constraint_id", "description")
            if constraint
            else ("success_criteria", "criterion_id", "criterion")
        )
        _fields(operation, {text_key}, {key})
        items = snapshot["payload"][collection]
        identifier = _claim(
            snapshot, operation.get(key), key.split("_")[0], {item[key] for item in items}
        )
        _replace(items, key, {key: identifier, text_key: _text(operation[text_key])})

    @staticmethod
    def _remove_obligation(snapshot, operation):
        collection, key = {
            "remove_requirement": ("requirements", "requirement_id"),
            "remove_constraint": ("constraints", "constraint_id"),
            "remove_success_criterion": ("success_criteria", "criterion_id"),
        }[operation["action"]]
        _fields(operation, {key})
        _remove(snapshot["payload"][collection], key, operation[key])

    @staticmethod
    def _proposal(snapshot, operation):
        _fields(
            operation,
            {"kind", "description", "requirement_ids", "constraint_ids"},
            {"proposal_id", "alternatives", "scope"},
        )
        if not isinstance(operation["kind"], str) or operation["kind"] not in {
            "SUGGESTION",
            "REQUIREMENT",
        }:
            raise IntegrityError("Classify the proposal as SUGGESTION or REQUIREMENT.")
        identifier = _claim(
            snapshot, operation.get("proposal_id"), "proposal", snapshot["proposals"]
        )
        proposal = {
            "proposal_id": identifier,
            "kind": operation["kind"],
            "description": _text(operation["description"]),
            "requirement_ids": _identifiers(operation["requirement_ids"]),
            "constraint_ids": _identifiers(operation["constraint_ids"]),
        }
        snapshot["proposals"][identifier] = {
            "proposal": proposal,
            "status": "PROPOSED",
            "alternatives": _texts(operation.get("alternatives", [])),
            "scope": _text(operation.get("scope", "Product-level structural proposal")),
        }

    @staticmethod
    def _decide(snapshot, operation):
        _fields(operation, {"proposal_id", "status", "decision", "rationale"})
        if not isinstance(operation["proposal_id"], str) or not isinstance(
            operation["status"], str
        ):
            raise IntegrityError("Choose a valid status for an existing proposal.")
        record = snapshot["proposals"].get(operation["proposal_id"])
        if record is None or operation["status"] not in _PROPOSAL_STATES:
            raise IntegrityError("Choose a valid status for an existing proposal.")
        record["status"] = operation["status"]
        payload = snapshot["payload"]
        identifier = operation["proposal_id"]
        decision = {
            "decision_id": _claim(snapshot, None, "decision"),
            "proposal_ids": [identifier],
            "decision": _text(operation["decision"]),
            "rationale": _text(operation["rationale"]),
        }
        unchanged = next(
            (
                previous
                for previous in payload["negotiated_decisions"]
                if identifier in previous["proposal_ids"]
                and previous["decision"] == decision["decision"]
                and previous["rationale"] == decision["rationale"]
            ),
            None,
        )
        if record["status"] == "ACCEPTED" and unchanged is not None:
            decision = deepcopy(unchanged)
        retained = []
        for previous in payload["negotiated_decisions"]:
            if identifier not in previous["proposal_ids"] or (
                record["status"] == "ACCEPTED"
                and previous["decision_id"] == decision["decision_id"]
            ):
                retained.append(previous)
                continue
            remaining = [item for item in previous["proposal_ids"] if item != identifier]
            if remaining:
                retained.append({**previous, "proposal_ids": remaining})
        payload["negotiated_decisions"] = retained
        if record["status"] == "ACCEPTED":
            _replace(payload["structural_proposals"], "proposal_id", deepcopy(record["proposal"]))
            if decision not in retained:
                payload["negotiated_decisions"].append(decision)
        else:
            payload["structural_proposals"] = [
                item
                for item in payload["structural_proposals"]
                if item["proposal_id"] != identifier
            ]
        record["last_decision"] = decision

    @staticmethod
    def _question(snapshot, operation):
        _fields(operation, {"text"}, {"question_id", "answer"})
        identifier = _claim(
            snapshot,
            operation.get("question_id"),
            "question",
            {item["question_id"] for item in snapshot["questions"]},
        )
        answer = operation.get("answer")
        _replace(
            snapshot["questions"],
            "question_id",
            {
                "question_id": identifier,
                "text": _text(operation["text"]),
                "answer": None if answer is None else _text(answer),
            },
        )

    @staticmethod
    def _feasibility(snapshot, operation):
        _fields(operation, {"description", "status", "evidence"})
        if not isinstance(operation["status"], str) or operation["status"] not in {
            "NOT_VERIFIED",
            "ASSUMPTION",
            "CONFIRMED",
        }:
            raise IntegrityError(
                "Separate unverified feasibility, assumptions, and confirmed evidence."
            )
        evidence = _texts(operation["evidence"])
        if operation["status"] == "CONFIRMED" and not evidence:
            raise IntegrityError("A confirmed feasibility fact needs explicit supporting evidence.")
        snapshot["feasibility"].append(
            {
                "assessment_id": _claim(snapshot, None, "assessment"),
                "description": _text(operation["description"]),
                "status": operation["status"],
                "evidence": evidence,
            }
        )

    @staticmethod
    def _resume(snapshot, operation):
        _fields(operation, set())

    def _document(self, snapshot, actor_id):
        base = None if snapshot["base_ref"] is None else self._base(snapshot["base_ref"])
        return {
            "metadata": {
                "contract_id": snapshot["contract_id"],
                "revision_id": _identifier("revision"),
                "contract_type": "PROJECT",
                "project_id": snapshot["project_id"],
                "version": 1 if base is None else base["metadata"]["version"] + 1,
                "schema_version": "1.0",
                "status": "PUBLISHED",
                "created_at": datetime.now(UTC).isoformat(),
                "supersedes": snapshot["base_ref"],
                "standard_ref": {"standard_id": "nukytera-standard", "version": "0.1"},
                "provenance": {
                    "engine": "PROJECT_MANAGER",
                    "actor_id": actor_id,
                    "source": "Project Manager session " + snapshot["session_id"],
                },
                "approval": {
                    "kind": "HUMAN",
                    "approval_id": _identifier("approval"),
                    "actor_id": actor_id,
                },
            },
            "payload": deepcopy(snapshot["payload"]),
        }

    def _issues(self, snapshot):
        payload = snapshot["payload"]
        issues = []
        if not payload["scope"]["included"]:
            issues.append("Define at least one included scope item.")
        if not payload["requirements"]:
            issues.append("Define at least one requirement with observable acceptance criteria.")
        if not payload["success_criteria"]:
            issues.append("Define at least one project success criterion.")
        included = {_normalized(item) for item in payload["scope"]["included"]}
        excluded = {_normalized(item) for item in payload["scope"]["excluded"]}
        if included & excluded:
            issues.append("The same normalized scope item is both included and excluded.")
        criteria = [
            *payload["success_criteria"],
            *(
                criterion
                for item in payload["requirements"]
                for criterion in item["acceptance_criteria"]
            ),
        ]
        if any(not item["acceptance_criteria"] for item in payload["requirements"]):
            issues.append("Every requirement needs at least one acceptance criterion.")
        if any(_normalized(item["criterion"]) in _PLACEHOLDERS for item in criteria):
            issues.append("Replace unresolved acceptance or success criterion placeholders.")
        if any(item["answer"] is None for item in snapshot["questions"]):
            issues.append("Resolve the outstanding clarification questions.")
        if any(
            item["status"] in {"PROPOSED", "NEEDS_CLARIFICATION"}
            for item in snapshot["proposals"].values()
        ):
            issues.append("Decide or withdraw the outstanding structural proposals.")
        if any(
            item["status"] == "ACCEPTED"
            and item["proposal"]["kind"] == "REQUIREMENT"
            and not (item["proposal"]["requirement_ids"] or item["proposal"]["constraint_ids"])
            for item in snapshot["proposals"].values()
        ):
            issues.append(
                "Link every accepted REQUIREMENT proposal to a requirement or constraint."
            )
        return issues

    def assess(self, session_id):
        snapshot = self.get(session_id)
        issues = self._issues(snapshot)
        try:
            self._bounded(snapshot, final=True)
            document = self._document(snapshot, "assessment")
            validate_schema(document)
            validate_semantics(
                document,
                self.store.get,
                self.store.resolve_active,
                history=lambda _kind, _project: [],
                verify_artifact=self.store.verify_artifact,
            )
        except IntegrityError:
            issues.append(
                "Resolve invalid draft links, identifiers, bounded scope, or a stale Project base."
            )
        except ValueError:
            issues.append("Complete the required Project Contract fields.")
        unknowns = [
            "Natural-language consistency and testability require human review.",
            "Technical feasibility and implemented product compliance are NOT_VERIFIED.",
        ]
        if self.assistance is not None:
            unknowns.append(
                "Optional assistance is advisory and has no publication or approval authority."
            )
            try:
                unknowns.extend(
                    "Advisory assistance: " + item
                    for item in _texts(self.assistance(deepcopy(snapshot)))
                )
            except Exception:
                unknowns.append(
                    "Optional assistance was unavailable or returned an invalid advisory response."
                )
        return {"issues": list(dict.fromkeys(issues)), "unknowns": unknowns}

    def review(self, session_id, expected_version, *, actor_id):
        snapshot = self._editable(session_id, expected_version)
        assessment = self.assess(session_id)
        if assessment["issues"]:
            raise IntegrityError(
                "The draft needs clarification before an exact publication review."
            )
        base = None if snapshot["base_ref"] is None else self._base(snapshot["base_ref"])
        if base is not None and snapshot["payload"] == base["payload"]:
            raise ConflictError(
                "Unchanged negotiation content does not create a new Project Contract revision."
            )
        document = self._document(snapshot, actor_id)
        validate_schema(document)
        snapshot["review"] = {
            "document": document,
            "sha256": sha256(canonical_json(document).encode("utf-8")).hexdigest(),
            "expires_at": time() + 300.0,
        }
        snapshot["state"] = "AWAITING_EXPLICIT_APPROVAL"
        return self.repository.save(
            session_id,
            expected_version,
            snapshot,
            actor_id=actor_id,
            action="EXACT_REVIEW_PREPARED",
        )

    def _transition(self, snapshot, expected_version, state, actor_id, action):
        snapshot["state"] = state
        snapshot["review"] = None
        return self.repository.save(
            snapshot["session_id"], expected_version, snapshot, actor_id=actor_id, action=action
        )

    def defer(self, session_id, expected_version, *, actor_id):
        return self._transition(
            self._editable(session_id, expected_version),
            expected_version,
            "DEFERRED",
            actor_id,
            "NEGOTIATION_DEFERRED",
        )

    def cancel(self, session_id, expected_version, *, actor_id):
        return self._transition(
            self._editable(session_id, expected_version),
            expected_version,
            "CANCELLED",
            actor_id,
            "NEGOTIATION_CANCELLED",
        )

    def keep(self, session_id, expected_version, *, actor_id):
        snapshot = self._editable(session_id, expected_version)
        if snapshot["base_ref"] is None:
            raise IntegrityError(
                "Keeping a specification requires an existing approved Project base."
            )
        return self._transition(
            snapshot, expected_version, "CLOSED_UNCHANGED", actor_id, "ORIGINAL_SPECIFICATION_KEPT"
        )

    def _bounded(self, snapshot, *, final):
        if snapshot["source_prr"] is None:
            return
        prr = self.store.get(ContractRef.from_json(snapshot["source_prr"]))
        if prr is None:
            raise IntegrityError("The negotiation's exact source revision request is unavailable.")
        base = self._base(snapshot["base_ref"])["payload"]
        candidate = snapshot["payload"]
        affected = deepcopy(prr["payload"]["affected_proposals"])
        proposals = set(affected["proposal_ids"])
        requirements, constraints, criteria = (
            set(affected[key]) for key in ("requirement_ids", "constraint_ids", "criterion_ids")
        )
        for proposal in base["structural_proposals"]:
            if proposal["proposal_id"] in proposals:
                requirements.update(proposal["requirement_ids"])
                constraints.update(proposal["constraint_ids"])
        for requirement in base["requirements"]:
            if requirement["requirement_id"] in requirements:
                criteria.update(item["criterion_id"] for item in requirement["acceptance_criteria"])
        if candidate["vision"] != base["vision"] or candidate["scope"] != base["scope"]:
            raise IntegrityError(
                "A PRR negotiation preserves the approved vision and global scope."
            )
        for field, key, allowed in (
            ("constraints", "constraint_id", constraints),
            ("success_criteria", "criterion_id", criteria),
            ("structural_proposals", "proposal_id", proposals),
        ):
            previous = {item[key]: item for item in base[field]}
            current = {item[key]: item for item in candidate[field]}
            if [item for item in base[field] if item[key] not in allowed] != [
                item
                for item in candidate[field]
                if item[key] in previous and item[key] not in allowed
            ]:
                raise IntegrityError("A PRR edit changes an unaffected obligation.")
            new_ids = current.keys() - previous.keys()
            if final and new_ids:
                if field != "constraints" or not new_ids <= {
                    identifier
                    for proposal in candidate["structural_proposals"]
                    if proposal["proposal_id"] in proposals
                    for identifier in proposal["constraint_ids"]
                }:
                    raise IntegrityError(
                        "A new PRR obligation must be linked to an affected proposal."
                    )
        old_requirements = {item["requirement_id"]: item for item in base["requirements"]}
        current_requirements = {item["requirement_id"]: item for item in candidate["requirements"]}
        for identifier, original in old_requirements.items():
            if identifier in requirements:
                continue
            current = current_requirements.get(identifier)
            if current is None or current["description"] != original["description"]:
                raise IntegrityError("A PRR edit changes an unaffected requirement.")
            if [
                item
                for item in original["acceptance_criteria"]
                if item["criterion_id"] not in criteria
            ] != [
                item
                for item in current["acceptance_criteria"]
                if item["criterion_id"] not in criteria
            ]:
                raise IntegrityError("A PRR edit changes an unaffected acceptance criterion.")
        if final and not current_requirements.keys() - old_requirements.keys() <= {
            identifier
            for proposal in candidate["structural_proposals"]
            if proposal["proposal_id"] in proposals
            for identifier in proposal["requirement_ids"]
        }:
            raise IntegrityError("A new PRR requirement must be linked to an affected proposal.")
        previous_decisions = {item["decision_id"]: item for item in base["negotiated_decisions"]}
        for decision in base["negotiated_decisions"]:
            if (
                not set(decision["proposal_ids"]) & proposals
                and decision not in candidate["negotiated_decisions"]
            ):
                raise IntegrityError("A PRR edit changes an unaffected negotiated decision.")
        for decision in candidate["negotiated_decisions"]:
            if (
                decision["decision_id"] not in previous_decisions
                and not set(decision["proposal_ids"]) <= proposals
            ):
                raise IntegrityError(
                    "A PRR decision must address the affected structural proposals."
                )
