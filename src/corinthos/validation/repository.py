# SPDX-License-Identifier: MPL-2.0
"""Durable Validation drafts, sealed methods, run claims and frozen results."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from time import time
from uuid import uuid4

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    ContractStore,
    IntegrityError,
    PublishContext,
    StoreError,
)
from corinthos.contracts.model import ID_PATTERN, canonical_json
from corinthos.contracts.schema import validate_schema
from corinthos.contracts.semantics import require_validation_interfaces

_MAX_JSON = 1_048_576


@dataclass(frozen=True)
class ValidationSummary:
    run_id: str
    state: str
    plan: ContractRef
    result: ContractRef | None
    plan_is_active: bool


def _identifier(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise StoreError("Validation requires a valid stable identifier.")
    return value


def _json(value):
    if type(value) is not dict:
        raise StoreError("Validation state must be a JSON object.")
    serialized = canonical_json(value)
    if len(serialized.encode("utf-8")) > _MAX_JSON:
        raise StoreError("Validation state exceeds 1 MiB. Keep larger evidence as artifacts.")
    return serialized


def _read(value):
    try:
        result = json.loads(value)
        if _json(result) != value:
            raise ValueError
        return result
    except (ValueError, TypeError, RecursionError):
        raise StoreError(
            "Stored Validation state is inconsistent. Preserve it for inspection."
        ) from None


def _digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def _reference(value):
    ref = value if isinstance(value, ContractRef) else ContractRef.from_json(value)
    if ref.contract_type != "VALIDATION":
        raise IntegrityError("An exact Validation Contract reference is required.")
    return ref


def _method_documents(plan, bindings, reviews):
    payload = plan["payload"]
    keys = {row["check_id"] for row in payload["verification_matrix"]}
    bindings_text, reviews_text = _json(bindings), _json(reviews)
    procedures = payload["execution_plan"]["procedures"]
    conditions = payload["execution_plan"]["conditions"]
    if (
        keys != bindings.keys()
        or keys != reviews.keys()
        or f"bindings-sha256:{_digest(bindings_text)}" not in procedures
        or f"method-reviews-sha256:{_digest(reviews_text)}" not in conditions
    ):
        raise IntegrityError(
            "The exact plan does not seal the complete methods and adequacy reviews."
        )
    return bindings_text, reviews_text


def _draft(row):
    return {
        "draft_id": row["draft_id"],
        "version": row["version"],
        "draft": _read(row["snapshot"]),
    }


def _run(row):
    result = {**dict(row), "plan_ref": _read(row["plan_ref"]), "context": _read(row["context"])}
    if (
        _reference(result["plan_ref"]).revision_id != result["plan_revision_id"]
        or _digest(_json(result["context"]["artifact_identity"])) != result["artifact_sha256"]
    ):
        raise IntegrityError("The stored Validation run differs from its exact plan or target.")
    frozen = result["frozen_result"]
    if frozen is not None:
        if _digest(frozen) != result["frozen_sha256"]:
            raise IntegrityError("The frozen Validation Result digest changed.")
        result["frozen_result"] = _read(frozen)
    return result


class ValidationRepository:
    """Serialize run changes and publication within the shared Kernel database."""

    def __init__(self, store, *, clock=None):
        if not isinstance(store, ContractStore):
            raise StoreError("Validation persistence requires the existing ContractStore.")
        self.store = store
        self._clock = time if clock is None else clock

    @staticmethod
    def project_summary(connection, project_id) -> ValidationSummary | None:
        """Read the latest local run and report its exact Validation identities."""
        row = connection.execute(
            "SELECT run_id, state, plan.contract_id, plan.revision_id, "
            "p.active_revision_id, result.contract_id, result.revision_id, "
            "r.contract_type, r.project_id "
            "FROM val_runs JOIN revisions AS plan ON plan.revision_id = plan_revision_id "
            "JOIN contracts AS p ON p.contract_id = plan.contract_id "
            "LEFT JOIN revisions AS result ON result.revision_id = result_revision_id "
            "LEFT JOIN contracts AS r ON r.contract_id = result.contract_id "
            "WHERE p.project_id = ? AND p.contract_type = 'VALIDATION' "
            "ORDER BY val_runs.rowid DESC LIMIT 1",
            (_identifier(project_id),),
        ).fetchone()
        if row is None:
            return None
        run, state, plan_id, plan_revision, active, result_id, result_revision, kind, owner = row
        if result_id is not None and (kind, owner) != ("VALIDATION_RESULT", project_id):
            raise IntegrityError("The stored Validation run has an inconsistent result identity.")
        return ValidationSummary(
            _identifier(run),
            state,
            ContractRef(plan_id, plan_revision, "VALIDATION", project_id),
            ContractRef(result_id, result_revision, "VALIDATION_RESULT", project_id)
            if result_id is not None
            else None,
            active == plan_revision,
        )

    def _now(self):
        value = self._clock()
        if type(value) not in (int, float) or not isfinite(value):
            raise StoreError("The Validation clock returned an invalid time.")
        return value

    def _timestamp(self):
        return datetime.fromtimestamp(self._now(), UTC).isoformat()

    def _expiry(self, ttl):
        if type(ttl) not in (int, float) or not isfinite(ttl) or not 0 < ttl <= 86_400:
            raise StoreError("A Validation claim needs a positive lease no longer than one day.")
        return self._now() + ttl

    @staticmethod
    def _draft_row(connection, draft_id):
        row = connection.execute(
            "SELECT * FROM val_drafts WHERE draft_id = ?", (_identifier(draft_id),)
        ).fetchone()
        if row is None:
            raise StoreError("The Validation draft does not exist.")
        return row

    def save_draft(self, draft_id, draft, *, expected_version=None):
        """Create a draft or replace an explicitly observed version."""
        _identifier(draft_id)
        snapshot = _json(draft)
        with self.store._transaction() as connection:
            if expected_version is None:
                connection.execute("INSERT INTO val_drafts VALUES (?,1,?)", (draft_id, snapshot))
            else:
                if type(expected_version) is not int or not 1 <= expected_version < 2**63 - 1:
                    raise StoreError("Supply a valid observed Validation draft version.")
                changed = connection.execute(
                    "UPDATE val_drafts SET version = version + 1, snapshot = ? "
                    "WHERE draft_id = ? AND version = ?",
                    (snapshot, draft_id, expected_version),
                )
                if changed.rowcount != 1:
                    raise ConflictError("The Validation draft changed. Reload it before saving.")
            return _draft(self._draft_row(connection, draft_id))

    def get_draft(self, draft_id):
        with self.store._connection() as connection:
            return _draft(self._draft_row(connection, draft_id))

    def list_drafts(self):
        with self.store._connection() as connection:
            return [
                _draft(row) for row in connection.execute("SELECT * FROM val_drafts ORDER BY rowid")
            ]

    def publish_plan(self, document, bindings, *, reviews, context):
        """Publish a VC and its exact method/review bindings as one write."""
        document = _read(_json(document))
        ref = _reference(ContractRef.from_document(document))
        validate_schema(document)
        methods, adequacy = _method_documents(document, bindings, reviews)
        with self.store._transaction() as connection:
            row = connection.execute(
                "SELECT bindings, reviews FROM val_plan_bindings WHERE revision_id = ?",
                (ref.revision_id,),
            ).fetchone()
            if row is not None and tuple(row) != (methods, adequacy):
                raise ConflictError(
                    "The exact Validation revision already seals different methods."
                )
            if row is None:
                self._current_sources(connection, document)
            self.store._publish(connection, document, context=context)
            if row is None:
                connection.execute(
                    "INSERT INTO val_plan_bindings VALUES (?,?,?)",
                    (ref.revision_id, methods, adequacy),
                )
        return ref

    def _methods(self, connection, ref):
        plan = self.store._lookup(connection, ref)
        row = connection.execute(
            "SELECT bindings, reviews FROM val_plan_bindings WHERE revision_id = ?",
            (ref.revision_id,),
        ).fetchone()
        if plan is None or row is None:
            raise IntegrityError("This exact Validation plan has no sealed operational methods.")
        bindings, reviews = _read(row["bindings"]), _read(row["reviews"])
        _method_documents(plan, bindings, reviews)
        return bindings, reviews

    def bindings(self, plan_ref):
        with self.store._connection() as connection:
            return self._methods(connection, _reference(plan_ref))[0]

    def reviews(self, plan_ref):
        with self.store._connection() as connection:
            return self._methods(connection, _reference(plan_ref))[1]

    def _current_sources(self, connection, plan):
        payload = plan["payload"]
        sources = [ContractRef.from_json(item) for item in payload["source_contract_refs"]]
        if payload["validation_scope"]["level"] == "PRODUCT":
            project_id = plan["metadata"]["project_id"]
            workflows = {
                row["metadata"]["contract_id"]
                for row in self.store._history(connection, "WORKFLOW", project_id)
            }
            if any(
                (active := self.store._active(connection, identifier)) is not None
                and ContractRef.from_document(active) not in sources
                for identifier in workflows
            ):
                raise ConflictError(
                    "Product validation must include the current approved Workflow."
                )
        active_sources = []
        for source in sources:
            active = self.store._active(connection, source.contract_id)
            if active is None or ContractRef.from_document(active) != source:
                raise ConflictError("A Validation source changed. Reconcile the exact plan.")
            active_sources.append(active)
        require_validation_interfaces(
            active_sources,
            lambda reference: self.store._lookup(connection, reference),
            lambda identifier: self.store._active(connection, identifier),
        )
        return active_sources

    def require_current(self, connection, plan_ref):
        """Check the exact VC and its sources while holding a writer reservation."""
        ref = _reference(plan_ref)
        active = self.store._active(connection, ref.contract_id)
        if active is None or ContractRef.from_document(active) != ref:
            raise ConflictError("The exact Validation plan is unavailable or no longer active.")
        return self._current_sources(connection, active)

    @staticmethod
    def _row(connection, run_id):
        row = connection.execute(
            "SELECT * FROM val_runs WHERE run_id = ?", (_identifier(run_id),)
        ).fetchone()
        if row is None:
            raise StoreError("The Validation run does not exist.")
        return row

    def _owned(self, connection, run_id, owner):
        row = self._row(connection, run_id)
        if row["state"] != "RUNNING" or row["owner"] != owner:
            raise ConflictError("This Validation worker no longer owns the unfinished run.")
        if row["expires_at"] <= self._now():
            raise ConflictError("The Validation claim expired. Inspect effects before recovering.")
        return row

    def _event(self, connection, run_id, kind, data):
        connection.execute(
            "INSERT INTO val_events (run_id,kind,data,occurred_at) VALUES (?,?,?,?)",
            (run_id, _identifier(kind), _json(data), self._timestamp()),
        )

    @staticmethod
    def _history(connection, run_id):
        return [
            {**dict(row), "data": _read(row["data"])}
            for row in connection.execute(
                "SELECT * FROM val_events WHERE run_id = ? ORDER BY sequence", (run_id,)
            )
        ]

    def start(self, plan_ref, context, *, evaluator, previous_run_id=None, ttl=120):
        """Claim a new run before effects and keep the earlier run as history."""
        ref = _reference(plan_ref)
        context = _read(_json(context))
        artifact = context.get("artifact_identity")
        if type(artifact) is not dict or not {
            "snapshot_id",
            "build_id",
            "artifact_id",
        }.intersection(artifact):
            raise IntegrityError("A Validation run needs the exact observed artifact identity.")
        if set(artifact) - {"snapshot_id", "build_id", "artifact_id", "commit"}:
            raise IntegrityError("The observed artifact identity contains unsupported fields.")
        for key, value in artifact.items():
            if key == "commit":
                if (
                    not isinstance(value, str)
                    or len(value) not in {40, 64}
                    or any(char not in "0123456789abcdef" for char in value)
                ):
                    raise IntegrityError("The observed artifact commit hash is malformed.")
            else:
                _identifier(value)
        artifact_hash = _digest(_json(artifact))
        _identifier(evaluator)
        with self.store._transaction() as connection:
            sources = self.require_current(connection, ref)
            if any(
                item["metadata"]["contract_type"] in {"WORKFLOW", "MODULE", "TECHNOLOGY_DECISION"}
                and item["metadata"]["provenance"]["actor_id"] == evaluator
                for item in sources
            ):
                raise IntegrityError("An implementation publisher cannot evaluate this plan.")
            if previous_run_id is not None:
                previous = self._row(connection, previous_run_id)
                prior_ref = _reference(_read(previous["plan_ref"]))
                if (
                    previous["state"] != "PUBLISHED"
                    or prior_ref.project_id != ref.project_id
                    or prior_ref.contract_id != ref.contract_id
                ):
                    raise ConflictError("Revalidation needs a finalized run of this logical plan.")
            unfinished = connection.execute(
                "SELECT 1 FROM val_runs WHERE plan_revision_id = ? AND artifact_sha256 = ? "
                "AND state IN ('RUNNING','FROZEN')",
                (ref.revision_id, artifact_hash),
            ).fetchone()
            if unfinished is not None:
                raise ConflictError(
                    "An unfinished run owns this target. Inspect or finalize it first."
                )
            bindings, reviews = self._methods(connection, ref)
            for key, sealed in (("bindings", bindings), ("reviews", reviews)):
                if key in context and context[key] != sealed:
                    raise IntegrityError("A run cannot replace its sealed methods or reviews.")
                context[key] = sealed
            run_id, owner = "validation-run-" + uuid4().hex, uuid4().hex
            now = self._timestamp()
            connection.execute(
                "INSERT INTO val_runs (run_id,plan_revision_id,plan_ref,artifact_sha256,evaluator,"
                "owner,expires_at,state,context,previous_run_id,started_at) "
                "VALUES (?,?,?,?,?,?,?,'RUNNING',?,?,?)",
                (
                    run_id,
                    ref.revision_id,
                    _json(ref.to_json()),
                    artifact_hash,
                    evaluator,
                    owner,
                    self._expiry(ttl),
                    _json(context),
                    previous_run_id,
                    now,
                ),
            )
            self._event(connection, run_id, "RUN_CLAIMED", {"previous_run_id": previous_run_id})
            return _run(self._row(connection, run_id))

    def renew(self, run_id, owner, *, ttl=120):
        with self.store._transaction() as connection:
            row = self._owned(connection, run_id, owner)
            connection.execute(
                "UPDATE val_runs SET expires_at = ? WHERE run_id = ?",
                (max(row["expires_at"], self._expiry(ttl)), run_id),
            )
            return _run(self._row(connection, run_id))

    def observe(self, run_id, owner, kind, data):
        """Append an actual observation only while the worker still owns the run."""
        data = _read(_json(data))
        if kind not in ("CANDIDATE_VERIFIED", "CHECK_STARTED", "CHECK_OBSERVED", "AUDIT_STOPPED"):
            raise StoreError("Unsupported Validation worker observation.")
        with self.store._transaction() as connection:
            row = self._owned(connection, run_id, owner)
            if kind in ("CHECK_STARTED", "CHECK_OBSERVED"):
                check_id = _identifier(data.get("check_id"))
                if check_id not in _read(row["context"])["bindings"]:
                    raise IntegrityError(
                        "A Validation observation must identify an exact plan check."
                    )
                previous = {
                    event[0]
                    for event in connection.execute(
                        "SELECT kind FROM val_events WHERE run_id = ? AND kind IN "
                        "('CHECK_STARTED','CHECK_OBSERVED') AND json_extract(data, '$.check_id') = ?",
                        (run_id, check_id),
                    )
                }
                if kind in previous or (
                    kind == "CHECK_OBSERVED" and "CHECK_STARTED" not in previous
                ):
                    raise ConflictError("A Validation check needs one start and one observation.")
            self._event(connection, run_id, kind, data)

    def get(self, run_id):
        with self.store._connection() as connection:
            return _run(self._row(connection, run_id))

    def list(self):
        with self.store._connection() as connection:
            return [
                _run(row) for row in connection.execute("SELECT * FROM val_runs ORDER BY rowid")
            ]

    def history(self, run_id):
        with self.store._connection() as connection:
            self._row(connection, run_id)
            return self._history(connection, run_id)

    def _freeze(self, connection, row, build_result, *, recovered=False):
        run = _run(row)
        run_id = run["run_id"]
        finished_at = self._timestamp()
        inputs = {**_run(row), "finished_at": finished_at}
        events = self._history(connection, run_id)
        result = _read(_json(build_result(inputs, events)))
        validate_schema(result)
        ref = ContractRef.from_document(result)
        if ref.contract_type != "VALIDATION_RESULT" or result["metadata"]["status"] != "PUBLISHED":
            raise IntegrityError("A Validation run can only freeze a Validation Result.")
        payload = result["payload"]
        observations = {
            event["data"]["check_id"]: event["data"]
            for event in events
            if event["kind"] == "CHECK_OBSERVED"
        }
        for item in payload["check_results"]:
            if item["status"] == "NOT_VERIFIED":
                continue
            observed = observations.get(item["check_id"])
            if observed is None or item["status"] != observed.get("status"):
                raise IntegrityError("A concluded check needs the exact recorded observation.")
        for item in payload["evidence_refs"]:
            if item not in observations.get(item["check_id"], {}).get("evidence", []):
                raise IntegrityError("Published evidence must match a retained check observation.")
        execution = payload["target_and_execution"]
        if (
            ref.project_id != run["plan_ref"]["project_id"]
            or result["metadata"]["provenance"]["actor_id"] != run["evaluator"]
            or payload["validation_plan_ref"] != run["plan_ref"]
            or execution["validation_run_id"] != run_id
            or execution["evaluator_ref"] != run["evaluator"]
            or execution["artifact_identity"] != run["context"]["artifact_identity"]
            or execution["started_at"] != run["started_at"]
            or execution["finished_at"] != finished_at
        ):
            raise IntegrityError("The frozen result differs from the exact observed run.")
        if recovered and (
            execution["status"] == "COMPLETED" or payload["gate_assessment"]["state"] != "BLOCKED"
        ):
            raise IntegrityError("Inspected recovery must retain a truthful blocked result.")
        serialized = _json(result)
        connection.execute(
            "UPDATE val_runs SET state = 'FROZEN', finished_at = ?, frozen_result = ?, "
            "frozen_sha256 = ? WHERE run_id = ?",
            (finished_at, serialized, _digest(serialized), run_id),
        )
        self._event(connection, run_id, "RESULT_FROZEN", {"result_ref": ref.to_json()})
        return _run(self._row(connection, run_id))

    def freeze(self, run_id, owner, build_result, *, guard=None):
        """Derive and durably freeze one exact result from the committed observations."""
        with self.store._transaction() as connection:
            row = self._owned(connection, run_id, owner)
            if guard is not None:
                guard(connection, _run(row))
            return self._freeze(connection, row, build_result)

    def recover(self, run_id, inspection, build_result):
        """Fence an unfinished run after explicit external-effect and process inspection."""
        inspection = _read(_json(inspection))
        reason = inspection.get("reason")
        if (
            inspection.get("process_stopped") is not True
            or inspection.get("effects_inspected") is not True
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ConflictError("Confirm stopped processes and inspected effects before recovery.")
        with self.store._transaction() as connection:
            row = self._row(connection, run_id)
            if row["state"] != "RUNNING":
                raise ConflictError("Only an unfinished Validation run needs inspected recovery.")
            self._event(connection, run_id, "RUN_RECOVERED", inspection)
            return self._freeze(connection, row, build_result, recovered=True)

    def publish(self, run_id, *, guard=None):
        """Publish exactly the frozen result and commit the run state with the Kernel."""
        with self.store._transaction() as connection:
            return self._publish_run(connection, _run(self._row(connection, run_id)), guard)

    def finalize(self, run_id, owner, build_result, *, guard=None):
        """Freeze and publish the result in one writer reservation."""
        with self.store._transaction() as connection:
            row = self._owned(connection, run_id, owner)
            if guard is not None:
                guard(connection, _run(row))
            run = self._freeze(connection, row, build_result)
            return self._publish_run(connection, run, guard)

    def _publish_run(self, connection, run, guard):
        if run["state"] == "RUNNING":
            raise ConflictError("An unfinished Validation run cannot publish a result.")
        document = run["frozen_result"]
        ref = ContractRef.from_document(document)
        if run["state"] == "PUBLISHED":
            if (
                run["result_revision_id"] != ref.revision_id
                or self.store._lookup(connection, ref) != document
            ):
                raise IntegrityError("The published Validation run disagrees with the Kernel.")
            return ref
        if guard is not None:
            guard(connection, run)
        self.store._publish(
            connection, document, context=PublishContext("VALIDATION", run["evaluator"])
        )
        connection.execute(
            "UPDATE val_runs SET state = 'PUBLISHED', result_revision_id = ? WHERE run_id = ?",
            (ref.revision_id, run["run_id"]),
        )
        self._event(connection, run["run_id"], "RESULT_PUBLISHED", {"result_ref": ref.to_json()})
        return ref

    def is_published_run(self, plan_ref, result_ref, run_id):
        """Check that the exact immutable result came from a managed run."""
        plan_ref = _reference(plan_ref)
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT * FROM val_runs WHERE run_id = ?", (_identifier(run_id),)
            ).fetchone()
            if row is None or row["state"] != "PUBLISHED":
                return False
            run = _run(row)
            document = run["frozen_result"]
            return (
                run["plan_ref"] == plan_ref.to_json()
                and run["result_revision_id"] == result_ref.revision_id
                and ContractRef.from_document(document) == result_ref
                and self.store._lookup(connection, result_ref) == document
            )
