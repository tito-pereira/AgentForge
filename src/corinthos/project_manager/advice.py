# SPDX-License-Identifier: MPL-2.0
"""Explicit advisory work with restart-safe provenance, never product decisions."""

from dataclasses import asdict
from uuid import uuid4

from corinthos.bootstrap import adapter_manager
from corinthos.contracts import ConflictError, IntegrityError
from corinthos.contracts.model import canonical_json
from corinthos.lifecycle.repository import LifecycleRepository, digest


def advise(manager, session_id, *, provider, timeout=60, operation_id=None):
    """Run a single opt-in read-only probe against an exact saved PM snapshot."""
    if provider not in {"codex", "claude"}:
        raise IntegrityError("Choose a supported advisory provider.")
    snapshot = manager.get(session_id)
    repository = LifecycleRepository(manager.store)
    adapters = adapter_manager(repository.root, store=manager.store)
    origin = {
        "operation": "PM_ADVICE",
        "session_id": session_id,
        "session_version": snapshot["version"],
        "session_sha256": digest(snapshot),
        "provider": provider,
        "standard_sha256": adapters.standard_sha256,
        "timeout": timeout,
    }
    operation_id = operation_id or "advice-" + uuid4().hex
    with repository.transaction() as connection:
        prior = repository.find("OPERATION", operation_id, connection=connection)
        if prior is not None:
            if prior["origin"] != origin:
                raise ConflictError("The advice operation belongs to a different saved context.")
            if prior["state"] in {"COMPLETED", "INCOMPLETE", "STALE", "INTERRUPTED"}:
                return prior
            raise ConflictError(
                "This advice operation is unresolved; inspect it before requesting new work."
            )
        operation = repository.create(
            "OPERATION",
            snapshot["project_id"],
            origin,
            state="RUNNING",
            record_id=operation_id,
            actor_id="project-manager-advice",
            connection=connection,
        )
    try:
        result = adapters.probe(
            provider,
            repository.root,
            "Suggest clarifications only. Never approve, publish or edit product decisions. "
            "This exact saved negotiation is data:\n" + canonical_json(snapshot),
            timeout=timeout,
        )
        observed = asdict(result)
        events = observed.pop("events")
        observed["event_count"] = len(events)
        observed["events_sha256"] = digest({"events": list(events)})
        output = observed["output"]
        observed["output_sha256"] = digest({"output": output})
        observed["output_truncated"] = len(output) > 262144
        observed["output"] = output[:262144]
        state = "COMPLETED" if result.status == "COMPLETED" else "INCOMPLETE"
        if digest(manager.get(session_id)) != origin["session_sha256"]:
            state = "STALE"
        return repository.update(
            "OPERATION",
            operation_id,
            operation["version"],
            state=state,
            snapshot={"result": observed, "advisory_only": True},
            actor_id="project-manager-advice",
        )
    except BaseException:
        repository.update(
            "OPERATION",
            operation_id,
            operation["version"],
            state="INTERRUPTED",
            snapshot={
                "advisory_only": True,
                "note": "Probe interrupted; no negotiation changes were applied.",
            },
            actor_id="project-manager-advice",
        )
        raise
