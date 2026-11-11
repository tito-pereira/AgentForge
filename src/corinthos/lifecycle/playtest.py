# SPDX-License-Identifier: MPL-2.0
"""Workflow-owned playtest pins, atomic promotion and source-bound feedback.

Sessions are explicit logical pins. This service never launches an application or
infers that a process stopped from a timeout, an absent agent or a reused PID.
"""

import json
import os
import stat
from hashlib import file_digest
from pathlib import Path
from uuid import uuid4

from corinthos.contracts import ConflictError, ContractRef, IntegrityError
from corinthos.contracts.artifacts import is_link, private_directory
from corinthos.contracts.model import canonical_json
from corinthos.project_manager.approval import _terminal, local_actor_id
from corinthos.project_manager.presentation import render_fields
from corinthos.workflow.reconciliation import RevisionReconciler

from .builds import BuildService
from .repository import LifecycleRepository, digest, identifier, now

_PINS = frozenset({"PREPARING", "OPEN", "INTERRUPTED"})
_SESSION_STATES = _PINS | {"ENDED", "SWITCHED"}
_FEEDBACK_STATES = frozenset({"OPEN", "TRIAGED", "RESOLVED", "DISMISSED"})
_LIMIT = 256 * 1024 * 1024


def _text(value, *, limit=16_384):
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > limit:
        raise IntegrityError("Provide nonblank text within the documented size limit.")
    return value


def _inspection(value):
    if (
        not isinstance(value, dict)
        or value.get("process_stopped") is not True
        or value.get("effects_inspected") is not True
    ):
        raise IntegrityError("Inspect actual stopped processes and effects before releasing a pin.")
    return {
        "process_stopped": True,
        "effects_inspected": True,
        "summary": _text(value.get("summary"), limit=4096),
    }


def _directory(path):
    info = path.lstat()
    if is_link(info) or not stat.S_ISDIR(info.st_mode) or path.resolve(strict=True) != path:
        raise IntegrityError("An owned playtest directory was replaced or linked.")
    return path


def _file_state(path):
    before = path.lstat()
    if is_link(before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise IntegrityError("Retention requires ordinary unlinked files.")
    with path.open("rb") as stream:
        if not os.path.samestat(before, os.fstat(stream.fileno())):
            raise IntegrityError("A retention file changed while opening it.")
        sha = file_digest(stream, "sha256").hexdigest()
    # Windows 3.12 fstat/lstat expose different ctime semantics; compare one API.
    after = path.lstat()
    fields = ("st_size", "st_mtime_ns", "st_ctime_ns", "st_dev", "st_ino", "st_nlink")
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise IntegrityError("A retention file changed while inspecting its bytes.")
    return {
        "size": before.st_size,
        "mtime_ns": before.st_mtime_ns,
        "ctime_ns": before.st_ctime_ns,
        "sha256": sha,
        "device": before.st_dev,
        "inode": before.st_ino,
    }


def _inventory(path):
    """Bounded exact deletion inventory; never follows links or hardlinked files."""
    _directory(path)
    result, directories, total = [], [], 0
    stack = [path]
    while stack:
        directory = _directory(stack.pop())
        for child in sorted(directory.iterdir()):
            info = child.lstat()
            if is_link(info):
                raise IntegrityError("Retention cannot follow links or reparse points.")
            relative = child.relative_to(path).as_posix()
            if stat.S_ISDIR(info.st_mode):
                directories.append(relative)
                stack.append(child)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
                if total > _LIMIT:
                    raise IntegrityError("Retention inventory exceeds its byte bound.")
                result.append({"path": relative, **_file_state(child)})
            else:
                raise IntegrityError("Retention requires ordinary unlinked files.")
            if len(result) + len(directories) > 10_000:
                raise IntegrityError("Retention inventory exceeds its entry bound.")
    return {
        "files": sorted(result, key=lambda row: row["path"]),
        "directories": sorted(directories),
        "bytes": total,
    }


class PlaytestService:
    """Coordinate existing Build/Validation authority without manufacturing proof."""

    def __init__(self, store_or_root):
        self.repository = LifecycleRepository(store_or_root)
        self.store, self.root = self.repository.store, self.repository.root
        self.builds = BuildService(self.root)

    def _operation(self, project_id, action, request, operation_id, connection):
        operation_id = identifier(operation_id or "playtest-op-" + uuid4().hex)
        origin = {"operation": "PLAYTEST_" + action, "request": request}
        old = self.repository.find("OPERATION", operation_id, connection=connection)
        if old is not None:
            if old["project_id"] != project_id or old["origin"] != origin:
                raise ConflictError("The operation ID is already bound to another exact request.")
            return old
        return self.repository.create(
            "OPERATION",
            project_id,
            origin,
            record_id=operation_id,
            state="RUNNING",
            connection=connection,
        )

    def _complete(self, operation, result, connection):
        self.repository.update(
            "OPERATION",
            operation["record_id"],
            operation["version"],
            state="COMPLETED",
            snapshot={"result": result},
            connection=connection,
            event="PLAYTEST_OPERATION_COMPLETED",
        )
        return result

    def configure(self, project_id, *, enabled):
        if type(enabled) is not bool:
            raise IntegrityError("IPE configuration requires an explicit boolean.")
        with self.repository.transaction() as connection:
            project = self.repository.project(project_id, create=True, connection=connection)
            if not enabled and (self._pins(project_id, connection) or project["pending_build_id"]):
                raise ConflictError("End inspected sessions and resolve pending promotion first.")
            return self.repository._update_project(
                project_id,
                project["version"],
                enabled=enabled,
                connection=connection,
                event="PLAYTEST_CONFIGURED",
            )

    def _project(self, project_id, connection):
        row = self.repository.project(project_id, connection=connection)
        if row is None or not row["enabled"]:
            raise ConflictError("Enable Interactive Project Evolution explicitly first.")
        return row

    def _pins(self, project_id, connection):
        sessions = self.repository.list("SESSION", project_id, connection=connection)
        if any(row["state"] not in _SESSION_STATES for row in sessions):
            raise IntegrityError("An unknown session state prevents a safe transition.")
        return [row for row in sessions if row["state"] in _PINS]

    def status(self, project_id):
        """Pure local observations; no native discovery, launch, expiry or unpin."""
        with self.store._connection() as connection:
            project = self.repository.project(project_id, connection=connection)
            return {
                "project": project,
                "pins": self._pins(project_id, connection),
                "feedback": self.repository.list("FEEDBACK", project_id, connection=connection),
            }

    def _admission_history(self, project_id, build_id, connection):
        for event in reversed(
            self.repository.events(project_id, record_id=build_id, connection=connection)
        ):
            if event["kind"] == "PLAYTEST_PROMOTED":
                return event["data"]["admission"]
        raise ConflictError("This build has no guarded historical playtest promotion.")

    def _cumulative(self, project, successor, connection):
        active = project["active_build_id"]
        if active is None or active == successor["build_id"]:
            return
        previous = self._admission_history(project["project_id"], active, connection)
        if previous["milestone_id"] not in successor["milestone_ids"] or not set(
            previous["checkpoint_ids"]
        ) <= set(successor["checkpoint_ids"]):
            raise ConflictError(
                "Promotion cannot regress the cumulative milestone/checkpoint scope."
            )
        if previous["workflow_ref"] != successor["workflow_ref"]:
            self._reconciled_lineage(previous, successor, connection)

    def _reconciled_lineage(self, previous, successor, connection):
        """Use actual approved ancestry and execution carry-over, never a caller marker."""
        before = ContractRef.from_json(previous["workflow_ref"])
        after = ContractRef.from_json(successor["workflow_ref"])
        if before.contract_id != after.contract_id or before.project_id != after.project_id:
            raise ConflictError("Promotion requires the same logical approved Workflow lineage.")
        document = self.store._active(connection, after.contract_id)
        if document is None or ContractRef.from_document(document) != after:
            raise ConflictError("The successor Workflow is no longer the active approved revision.")
        ancestry = set()
        for _ in range(256):
            reference = ContractRef.from_document(document)
            ancestry.add(reference.revision_id)
            if reference == before:
                break
            parent = document["metadata"]["supersedes"]
            if parent is None:
                raise ConflictError(
                    "The Workflow has no approved descendant path from the active build."
                )
            parent = ContractRef.from_json(parent)
            if parent.contract_id != before.contract_id or parent.project_id != before.project_id:
                raise IntegrityError("Workflow ancestry changed its logical project binding.")
            document = self.store._lookup(connection, parent)
            if document is None:
                raise IntegrityError("An exact approved Workflow ancestor is unavailable.")
        else:
            raise IntegrityError("Workflow ancestry exceeds its bounded traversal.")
        impact = RevisionReconciler(self.store).compare(before, after)
        old_build = self.repository.get("BUILD", previous["build_id"], connection=connection)
        new_build = self.repository.get("BUILD", successor["build_id"], connection=connection)
        old_id = identifier(old_build["origin"].get("execution_id"))
        current_id = identifier(new_build["origin"].get("execution_id"))
        if current_id == old_id:
            raise ConflictError("A changed Workflow requires an actual successor execution.")
        executions, visited = self.builds.executions, set()
        carried = set(successor["checkpoint_ids"])
        while current_id != old_id:
            if current_id in visited or len(visited) >= 256:
                raise IntegrityError("Execution reconciliation has cyclic or excessive ancestry.")
            visited.add(current_id)
            current = executions._view(connection, executions._row(connection, current_id))
            rows = connection.execute(
                "SELECT data FROM wf_execution_events WHERE execution_id=? AND kind='EXECUTION_RECONCILED'",
                (current_id,),
            ).fetchall()
            if len(rows) != 1:
                raise ConflictError(
                    "The successor has no actual unambiguous execution reconciliation."
                )
            fact = json.loads(rows[0]["data"])
            predecessor_id = identifier(fact.get("previous_execution_id"))
            predecessor = executions._view(connection, executions._row(connection, predecessor_id))
            if (
                current["project_id"] != before.project_id
                or predecessor["project_id"] != before.project_id
                or current["workspace"] != predecessor["workspace"]
                or current["workflow_ref"]["revision_id"] not in ancestry
                or predecessor["workflow_ref"]["revision_id"] not in ancestry
            ):
                raise ConflictError(
                    "Execution reconciliation does not follow the exact project/Workflow ancestry."
                )
            for checkpoint_id in list(carried):
                checkpoint = current["checkpoints"].get(checkpoint_id)
                if checkpoint is None or checkpoint["state"] != "COMPLETED":
                    raise ConflictError(
                        "Every cumulative checkpoint must have completed in the successor."
                    )
                inherited = checkpoint["inherited_from"]
                if inherited is None:
                    carried.remove(checkpoint_id)
                    continue
                prior = predecessor["checkpoints"].get(checkpoint_id)
                if (
                    checkpoint_id not in fact.get("preserved_checkpoint_ids", [])
                    or inherited.get("execution_id") != predecessor_id
                    or inherited.get("workflow_ref") != predecessor["workflow_ref"]
                    or inherited.get("checkpoint_id") != checkpoint_id
                    or prior is None
                    or prior["state"] != "COMPLETED"
                    or inherited.get("attempt_id") != prior["attempt_id"]
                    or checkpoint["attempt_id"] != prior["attempt_id"]
                    or not executions._compatible(
                        connection,
                        self.store,
                        self.store._lookup(
                            connection, ContractRef.from_json(predecessor["workflow_ref"])
                        ),
                        self.store._lookup(
                            connection, ContractRef.from_json(current["workflow_ref"])
                        ),
                        checkpoint_id,
                        predecessor["bindings"],
                        current["bindings"],
                    )
                ):
                    raise ConflictError(
                        "A carried checkpoint lacks its exact compatible original execution proof."
                    )
            current_id = predecessor_id
        if carried & set(impact["affected_checkpoint_ids"]):
            raise ConflictError(
                "Affected checkpoints must be newly completed after the active build execution."
            )

    def _promote(self, project, admission, connection):
        project = self.repository._update_project(
            project["project_id"],
            project["version"],
            active_build_id=admission["build_id"],
            pending_build_id=None,
            connection=connection,
            event="PLAYTEST_TARGET_CHANGED",
        )
        self.repository.event(
            project["project_id"],
            "PLAYTEST_PROMOTED",
            {"admission": admission, "tracker_id": project["tracker_id"]},
            record_id=admission["build_id"],
            connection=connection,
        )
        return project

    def promote(self, project_id, build_id, *, operation_id=None):
        request = {"build_id": identifier(build_id)}
        with self.repository.transaction() as connection:
            operation = self._operation(project_id, "PROMOTE", request, operation_id, connection)
            if operation["state"] == "COMPLETED":
                return operation["snapshot"]["result"]
            if operation["state"] == "CANCELLED":
                raise ConflictError("This exact promotion was cancelled; use a fresh operation ID.")
            project = self._project(project_id, connection)
            admission = self.builds.require_eligible(build_id, connection)
            if admission["project_id"] != project_id:
                raise IntegrityError("The candidate belongs to another project.")
            self._cumulative(project, admission, connection)
            if project["pending_build_id"] not in {None, build_id}:
                raise ConflictError("Resolve the other pending promotion explicitly first.")
            if project["active_build_id"] != build_id and self._pins(project_id, connection):
                project = self.repository._update_project(
                    project_id,
                    project["version"],
                    pending_build_id=build_id,
                    connection=connection,
                    event="PLAYTEST_SUCCESSOR_WAITING",
                )
                result = {
                    "operation_id": operation["record_id"],
                    "state": "WAITING",
                    "project": project,
                    "build_id": build_id,
                }
                self.repository.update(
                    "OPERATION",
                    operation["record_id"],
                    operation["version"],
                    state="WAITING",
                    snapshot={"result": result},
                    connection=connection,
                    event="PLAYTEST_PROMOTION_WAITING",
                )
                return result
            if project["active_build_id"] != build_id:
                project = self._promote(project, admission, connection)
            return self._complete(
                operation,
                {
                    "operation_id": operation["record_id"],
                    "state": "PROMOTED",
                    "project": project,
                    "build_id": build_id,
                },
                connection,
            )

    def cancel_pending(self, project_id, build_id, *, reason):
        """An explicit cancellation preserves the queued request and its history."""
        reason = _text(reason, limit=4096)
        with self.repository.transaction() as connection:
            project = self._project(project_id, connection)
            if project["pending_build_id"] != build_id:
                raise ConflictError("The exact pending candidate changed.")
            project = self.repository._update_project(
                project_id,
                project["version"],
                pending_build_id=None,
                connection=connection,
                event="PLAYTEST_PENDING_CANCELLED",
            )
            for operation in self.repository.list(
                "OPERATION", project_id, state="WAITING", connection=connection
            ):
                if operation["origin"] == {
                    "operation": "PLAYTEST_PROMOTE",
                    "request": {"build_id": build_id},
                }:
                    self.repository.update(
                        "OPERATION",
                        operation["record_id"],
                        operation["version"],
                        state="CANCELLED",
                        snapshot={"reason": reason},
                        connection=connection,
                    )
            return project

    def _session_path(self, session_id):
        return private_directory(self.root, "artifacts", create=True) / ("playtest-" + session_id)

    def _prepare_data(self, session_id, binding, *, retry=False):
        folder = self._session_path(session_id)
        marker = canonical_json(binding)
        if folder.exists():
            _directory(folder)
            info = (folder / "owner.json").lstat()
            if (
                not retry
                or is_link(info)
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (folder / "owner.json").read_text(encoding="utf-8") != marker
                or {entry.name for entry in folder.iterdir()} != {"owner.json", "data"}
                or list(_directory(folder / "data").iterdir())
            ):
                raise IntegrityError("Inspect existing session data; it cannot be adopted blindly.")
        else:
            folder.mkdir(mode=0o700)
            (folder / "owner.json").write_text(marker, encoding="utf-8")
            (folder / "data").mkdir(mode=0o700)
        return str(_directory(folder / "data"))

    def _interrupted(self, operation_id, session_id=None):
        with self.repository.transaction() as connection:
            operation = self.repository.get("OPERATION", operation_id, connection=connection)
            if operation["state"] == "COMPLETED":
                return
            self.repository.update(
                "OPERATION",
                operation_id,
                operation["version"],
                state="INTERRUPTED",
                snapshot={**operation["snapshot"], "inspection_required": True},
                connection=connection,
            )
            if session_id:
                session = self.repository.get("SESSION", session_id, connection=connection)
                if session["state"] == "PREPARING":
                    self.repository.update(
                        "SESSION",
                        session_id,
                        session["version"],
                        state="INTERRUPTED",
                        snapshot=session["snapshot"],
                        connection=connection,
                    )

    def start(self, project_id, *, build_id=None, operation_id=None):
        """Reserve an exact build pin and fresh data; deliberately launch no process."""
        with self.repository.transaction() as connection:
            request = {"build_id": build_id}
            operation = self._operation(
                project_id, "SESSION_START", request, operation_id, connection
            )
            if operation["state"] == "COMPLETED":
                return operation["snapshot"]["result"]
            project = self._project(project_id, connection)
            selected = build_id or project["active_build_id"]
            if operation["state"] != "RUNNING" or operation["snapshot"]:
                raise ConflictError(
                    "Inspect and recover the interrupted session; do not relaunch it."
                )
            if selected is None or selected != project["active_build_id"]:
                raise ConflictError("Start a session only on the current active build.")
            admission = self.builds.require_eligible(selected, connection)
            session_id = "session-" + uuid4().hex
            origin = {
                "admission": admission,
                "build_id": selected,
                "tracker_id": project["tracker_id"],
                "predecessor_id": None,
                "operation_id": operation["record_id"],
                "launch_mode": "EXPLICIT_LOGICAL_PIN",
                "data_root": str(self._session_path(session_id) / "data"),
            }
            self.repository.create(
                "SESSION",
                project_id,
                origin,
                record_id=session_id,
                state="PREPARING",
                connection=connection,
            )
            operation = self.repository.update(
                "OPERATION",
                operation["record_id"],
                operation["version"],
                snapshot={"session_id": session_id},
                connection=connection,
            )
        try:
            self._prepare_data(
                session_id, {"session_id": session_id, "origin_sha256": digest(origin)}
            )
            with self.repository.transaction() as connection:
                session = self.repository.get("SESSION", session_id, connection=connection)
                if session["state"] != "PREPARING":
                    raise ConflictError("The session was inspected or ended during preparation.")
                if self.builds.require_eligible(selected, connection) != admission:
                    raise ConflictError(
                        "Build admission changed while preparing the isolated session data."
                    )
                session = self.repository.update(
                    "SESSION",
                    session_id,
                    session["version"],
                    state="OPEN",
                    connection=connection,
                    event="PLAYTEST_SESSION_OPENED",
                )
                current = self.repository.get(
                    "OPERATION", operation["record_id"], connection=connection
                )
                return self._complete(current, session, connection)
        except BaseException:
            self._interrupted(operation["record_id"], session_id)
            raise

    def end(self, session_id, *, inspection, operation_id=None):
        inspection = _inspection(inspection)
        with self.repository.transaction() as connection:
            session = self.repository.get("SESSION", session_id, connection=connection)
            operation = self._operation(
                session["project_id"],
                "SESSION_END",
                {"session_id": session_id, "inspection": inspection},
                operation_id,
                connection,
            )
            if operation["state"] == "COMPLETED":
                return operation["snapshot"]["result"]
            if session["state"] not in _PINS:
                raise ConflictError("This session has already ended or switched.")
            session = self.repository.update(
                "SESSION",
                session_id,
                session["version"],
                state="ENDED",
                snapshot={"inspection": inspection, "ended_at": now()},
                connection=connection,
                event="PLAYTEST_SESSION_ENDED",
            )
            # A stale queued candidate must never prevent an inspected pin release.
            return self._complete(operation, session, connection)

    def switch(self, session_id, build_id, *, inspection, operation_id=None):
        inspection = _inspection(inspection)
        with self.repository.transaction() as connection:
            old = self.repository.get("SESSION", session_id, connection=connection)
            operation = self._operation(
                old["project_id"],
                "SESSION_SWITCH",
                {"session_id": session_id, "build_id": build_id, "inspection": inspection},
                operation_id,
                connection,
            )
            if operation["state"] == "COMPLETED":
                return operation["snapshot"]["result"]
            if operation["state"] == "CANCELLED":
                raise ConflictError("This switch was abandoned; use a fresh operation ID.")
            project = self._project(old["project_id"], connection)
            if old["state"] not in _PINS or old["origin"]["build_id"] != project["active_build_id"]:
                raise ConflictError("Switch only an inspected pin of the current active build.")
            if {row["record_id"] for row in self._pins(old["project_id"], connection)} != {
                session_id
            }:
                raise ConflictError(
                    "Other sessions still pin the old build; end them explicitly first."
                )
            admission = self.builds.require_eligible(build_id, connection)
            if (
                admission["project_id"] != old["project_id"]
                or build_id == project["active_build_id"]
            ):
                raise IntegrityError("Switch to a distinct eligible build in the same project.")
            if project["pending_build_id"] not in {None, build_id}:
                raise ConflictError("Another successor is pending.")
            self._cumulative(project, admission, connection)
            successor_id = operation["snapshot"].get("successor_id", "session-" + uuid4().hex)
            origin = {
                "admission": admission,
                "build_id": build_id,
                "tracker_id": project["tracker_id"],
                "predecessor_id": session_id,
                "operation_id": operation["record_id"],
                "launch_mode": "EXPLICIT_LOGICAL_PIN",
                "data_root": str(self._session_path(successor_id) / "data"),
            }
            binding = {"session_id": successor_id, "origin_sha256": digest(origin)}
            operation = self.repository.update(
                "OPERATION",
                operation["record_id"],
                operation["version"],
                state="RUNNING",
                snapshot={"successor_id": successor_id},
                connection=connection,
            )
        try:
            self._prepare_data(successor_id, binding, retry=True)
            with self.repository.transaction() as connection:
                project = self._project(old["project_id"], connection)
                current = self.repository.get("SESSION", session_id, connection=connection)
                if current["version"] != old["version"] or current["state"] not in _PINS:
                    raise ConflictError("The old session changed during switch preparation.")
                if {row["record_id"] for row in self._pins(old["project_id"], connection)} != {
                    session_id
                }:
                    raise ConflictError("A new session still pins the old build.")
                fresh = self.builds.require_eligible(build_id, connection)
                if fresh != admission or project["pending_build_id"] not in {None, build_id}:
                    raise ConflictError(
                        "The successor admission changed during switch preparation."
                    )
                self._cumulative(project, fresh, connection)
                self._promote(project, fresh, connection)
                self.repository.update(
                    "SESSION",
                    session_id,
                    current["version"],
                    state="SWITCHED",
                    snapshot={
                        "inspection": inspection,
                        "successor_id": successor_id,
                        "ended_at": now(),
                    },
                    connection=connection,
                    event="PLAYTEST_SESSION_SWITCHED",
                )
                successor = self.repository.create(
                    "SESSION",
                    old["project_id"],
                    origin,
                    record_id=successor_id,
                    state="OPEN",
                    connection=connection,
                )
                current_op = self.repository.get(
                    "OPERATION", operation["record_id"], connection=connection
                )
                return self._complete(current_op, successor, connection)
        except BaseException:
            self._interrupted(operation["record_id"])
            raise

    def abandon_operation(self, operation_id, *, inspection):
        """Close inspected preparation without releasing any existing session pin."""
        inspection = _inspection(inspection)
        with self.repository.transaction() as connection:
            operation = self.repository.get("OPERATION", operation_id, connection=connection)
            if operation["origin"].get("operation") not in {
                "PLAYTEST_SESSION_START",
                "PLAYTEST_SESSION_SWITCH",
            }:
                raise IntegrityError("Only an actual session preparation can be abandoned here.")
            if operation["state"] == "CANCELLED":
                return operation
            if operation["state"] == "COMPLETED":
                raise ConflictError("The preparation completed; inspect its resulting session.")
            for session in self._pins(operation["project_id"], connection):
                if session["origin"]["operation_id"] == operation_id:
                    raise ConflictError(
                        "End the inspected resulting session before abandoning preparation."
                    )
            return self.repository.update(
                "OPERATION",
                operation_id,
                operation["version"],
                state="CANCELLED",
                snapshot={**operation["snapshot"], "inspection": inspection},
                connection=connection,
                event="PLAYTEST_PREPARATION_ABANDONED",
            )

    def feedback(
        self,
        project_id,
        build_id,
        body,
        *,
        context="",
        session_id=None,
        operation_id=None,
        synthetic=False,
    ):
        if type(synthetic) is not bool:
            raise IntegrityError("Synthetic observation marking requires a boolean.")
        return self._feedback(
            project_id,
            build_id,
            body,
            context=context,
            session_id=session_id,
            operation_id=operation_id,
            observer="SYNTHETIC" if synthetic else "OPERATOR",
        )

    def feedback_from_terminal(self, project_id, build_id, *, session_id=None, operation_id=None):
        """Label HUMAN only after actual bounded input from the foreground terminal."""
        with self.store._connection() as connection:
            target = self._admission_history(project_id, build_id, connection)
        with _terminal() as (reader, writer):
            writer.write(render_fields({"feedback_target": target, "session_id": session_id}))
            writer.write("\nObservation (one line; not product acceptance): ")
            writer.flush()
            body = reader.readline(16_385)
            _text(body)
        return self._feedback(
            project_id,
            build_id,
            body,
            context="Foreground terminal observation",
            session_id=session_id,
            operation_id=operation_id,
            observer="HUMAN",
        )

    def _feedback(self, project_id, build_id, body, *, context, session_id, operation_id, observer):
        body = _text(body)
        if not isinstance(context, str) or len(context.encode("utf-8")) > 4096:
            raise IntegrityError("Feedback context exceeds its bounded text limit.")
        request = {
            "build_id": identifier(build_id),
            "body": body,
            "context": context,
            "session_id": session_id,
            "observer": observer,
        }
        with self.repository.transaction() as connection:
            operation = self._operation(project_id, "FEEDBACK", request, operation_id, connection)
            if operation["state"] == "COMPLETED":
                return operation["snapshot"]["result"]
            admission = self._admission_history(project_id, build_id, connection)
            project = self.repository.project(project_id, connection=connection)
            if session_id:
                session = self.repository.get("SESSION", session_id, connection=connection)
                if (
                    session["project_id"] != project_id
                    or session["origin"]["build_id"] != build_id
                    or session["origin"]["admission"]["artifact_identity"]
                    != admission["artifact_identity"]
                    or session["state"] not in {"OPEN", "ENDED", "SWITCHED"}
                ):
                    raise IntegrityError("Feedback must retain the actual eligible session origin.")
            origin = {
                **request,
                "admission": admission,
                "tracker_id": project["tracker_id"],
                "observed_at": now(),
                "observer_actor": local_actor_id(),
            }
            record = self.repository.create(
                "FEEDBACK",
                project_id,
                origin,
                state="OPEN",
                snapshot={"route": "UNTRIAGED"},
                connection=connection,
                event="PLAYTEST_FEEDBACK_RECORDED",
            )
            return self._complete(operation, record, connection)

    def triage(
        self,
        feedback_id,
        *,
        category,
        reason,
        state="TRIAGED",
        related_ids=(),
        expected_version=None,
    ):
        routes = {
            "BUG": "WORKFLOW_VALIDATION",
            "REQUIREMENT": "PROJECT_MANAGER",
            "OBSERVATION": "NO_CHANGE",
        }
        if category not in routes or state not in _FEEDBACK_STATES - {"OPEN"}:
            raise IntegrityError("Use an explicit feedback category and treatment state.")
        reason = _text(reason, limit=4096)
        if not isinstance(related_ids, (tuple, list)) or len(related_ids) > 64:
            raise IntegrityError("Provide a bounded list of related operational identifiers.")
        related_ids = [identifier(value) for value in related_ids]
        with self.repository.transaction() as connection:
            record = self.repository.get("FEEDBACK", feedback_id, connection=connection)
            if record["state"] not in _FEEDBACK_STATES:
                raise IntegrityError("Unknown feedback treatment state.")
            return self.repository.update(
                "FEEDBACK",
                feedback_id,
                record["version"] if expected_version is None else expected_version,
                state=state,
                snapshot={
                    "category": category,
                    "reason": reason,
                    "route": routes[category],
                    "related_ids": related_ids,
                    "dispatch": "RECORDED_FOR_EXPLICIT_ACTION",
                },
                connection=connection,
                event="PLAYTEST_FEEDBACK_TRIAGED",
            )

    def _protected(self, project_id, connection):
        project = self.repository.project(project_id, connection=connection)
        protected = {
            value for value in (project["active_build_id"], project["pending_build_id"]) if value
        }
        protected.update(row["origin"]["build_id"] for row in self._pins(project_id, connection))
        for version in self.repository.list("VERSION", project_id, connection=connection):
            build_id = version["origin"].get("artifact_identity", {}).get("build_id")
            if build_id:
                protected.add(build_id)
        for operation in self.repository.list("OPERATION", project_id, connection=connection):
            if operation["state"] in {"COMPLETED", "CANCELLED"}:
                continue
            request = operation["origin"].get("request", {})
            build_id = request.get("build_id") or operation["origin"].get("build_id")
            if build_id:
                protected.add(build_id)
        return protected

    def _payload(self, build):
        base = private_directory(self.root, "snapshots")
        folder = _directory(base / identifier(build["record_id"]))
        path = folder / "candidate"
        if str(path) != build["origin"].get("candidate_root"):
            raise IntegrityError("Only the exact owned build candidate can be retired.")
        _directory(folder)
        return path

    def retention_preview(self, project_id, *, keep_previous=1):
        if type(keep_previous) is not int or not 0 <= keep_previous <= 100:
            raise IntegrityError("Keep between zero and 100 previous unpinned candidates.")
        with self.store._connection() as connection:
            project = self.repository.project(project_id, connection=connection)
            if project is None:
                raise IntegrityError("No project lifecycle exists to retain.")
            protected = self._protected(project_id, connection)
            builds = self.repository.list("BUILD", project_id, connection=connection)
            available = [
                row
                for row in builds
                if row["state"] == "SEALED" and row["record_id"] not in protected
            ]
            if keep_previous:
                available_ids = {row["record_id"] for row in available}
                previous = []
                for event in reversed(self.repository.events(project_id, connection=connection)):
                    build_id = event["record_id"]
                    if (
                        event["kind"] == "PLAYTEST_PROMOTED"
                        and build_id in available_ids
                        and build_id not in previous
                    ):
                        previous.append(build_id)
                previous.extend(
                    row["record_id"]
                    for row in reversed(available)
                    if row["record_id"] not in previous
                )
                protected.update(previous[:keep_previous])
            targets = []
            for build in available:
                if build["record_id"] in protected:
                    continue
                payload = self._payload(build)
                targets.append(
                    {
                        "build_id": build["record_id"],
                        "record_version": build["version"],
                        "origin_sha256": build["origin_sha256"],
                        "path": str(payload),
                        "inventory": _inventory(payload),
                    }
                )
            plan = {
                "project_id": project_id,
                "project_version": project["version"],
                "keep_previous": keep_previous,
                "protected_build_ids": sorted(protected),
                "targets": targets,
                "bytes": sum(row["inventory"]["bytes"] for row in targets),
            }
            return {
                **plan,
                "plan_sha256": digest(plan),
                "pressure": "NO_SAFE_DELETION" if not targets else "SAFE_TARGETS_AVAILABLE",
            }

    def retention_apply(self, plan, *, operation_id=None, inspection=None):
        """Apply the exact preview; partial filesystem effects remain recoverable."""
        if not isinstance(plan, dict):
            raise IntegrityError("Provide the complete reviewed retention preview.")
        core = {key: value for key, value in plan.items() if key not in {"plan_sha256", "pressure"}}
        if digest(core) != plan.get("plan_sha256"):
            raise IntegrityError("The retention preview hash differs.")
        project_id = identifier(plan.get("project_id"))
        with self.repository.transaction() as connection:
            operation = self._operation(
                project_id, "RETENTION", {"plan": plan}, operation_id, connection
            )
            if operation["state"] == "COMPLETED":
                return operation["snapshot"]["result"]
            recovering = bool(operation["snapshot"].get("reserved"))
            if recovering:
                inspection = _inspection(inspection)
            else:
                current = self.retention_preview(project_id, keep_previous=plan["keep_previous"])
                if current != plan:
                    raise ConflictError(
                        "Retention references or owned bytes changed; preview again."
                    )
            protected = self._protected(project_id, connection)
            for target in plan["targets"]:
                if target["build_id"] in protected:
                    raise ConflictError("A retention target acquired a live reference.")
                build = self.repository.get("BUILD", target["build_id"], connection=connection)
                if (
                    build["origin_sha256"] != target["origin_sha256"]
                    or (not recovering and build["version"] != target["record_version"])
                    or build["state"] not in ({"RETIRING"} if recovering else {"SEALED"})
                ):
                    raise ConflictError("The exact retention target changed.")
                if str(self._payload(build)) != target["path"]:
                    raise IntegrityError("Retention cannot delete another path.")
                self.repository.update(
                    "BUILD",
                    build["record_id"],
                    build["version"],
                    state="RETIRING",
                    snapshot=build["snapshot"],
                    connection=connection,
                    event="BUILD_RETIREMENT_RESERVED",
                )
            operation = self.repository.update(
                "OPERATION",
                operation["record_id"],
                operation["version"],
                state="RUNNING",
                snapshot={"reserved": True, "inspection": inspection},
                connection=connection,
            )
        try:
            for target in plan["targets"]:
                path = Path(target["path"])
                _directory(path.parent)
                try:
                    path.lstat()
                except FileNotFoundError:
                    if recovering:
                        continue
                    raise
                actual = _inventory(path)
                expected = target["inventory"]
                if recovering:
                    if any(row not in expected["files"] for row in actual["files"]) or not set(
                        actual["directories"]
                    ) <= set(expected["directories"]):
                        raise IntegrityError("Unexpected effects prevent retention recovery.")
                elif actual != expected:
                    raise IntegrityError("Owned candidate bytes changed before deletion.")
                for row in actual["files"]:
                    candidate = path / row["path"]
                    if _file_state(candidate) != {
                        key: value for key, value in row.items() if key != "path"
                    }:
                        raise IntegrityError("A retention file changed before deletion.")
                    candidate.unlink()
                for relative in sorted(
                    actual["directories"], key=lambda value: len(value.split("/")), reverse=True
                ):
                    _directory(path / relative).rmdir()
                _directory(path).rmdir()
            with self.repository.transaction() as connection:
                for target in plan["targets"]:
                    build = self.repository.get("BUILD", target["build_id"], connection=connection)
                    if build["state"] != "RETIRING":
                        raise ConflictError("A retirement reservation changed during deletion.")
                    self.repository.update(
                        "BUILD",
                        build["record_id"],
                        build["version"],
                        state="RETIRED",
                        snapshot={
                            **build["snapshot"],
                            "retirement_operation": operation["record_id"],
                        },
                        connection=connection,
                        event="BUILD_PAYLOAD_RETIRED",
                    )
                operation = self.repository.get(
                    "OPERATION", operation["record_id"], connection=connection
                )
                return self._complete(
                    operation,
                    {
                        "retired_build_ids": [row["build_id"] for row in plan["targets"]],
                        "operation_id": operation["record_id"],
                        "bytes": plan["bytes"],
                    },
                    connection,
                )
        except BaseException:
            self._interrupted(operation["record_id"])
            raise
