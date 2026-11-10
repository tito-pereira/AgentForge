# SPDX-License-Identifier: MPL-2.0
"""Actual local engineering checks and a consumer for published Validation results."""

import os
import queue
import stat
import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from time import monotonic

from corinthos.adapters.process_control import start_process
from corinthos.contracts import ContractRef, IntegrityError, validate_schema
from corinthos.contracts.artifacts import is_link, private_directory
from corinthos.contracts.model import canonical_json
from corinthos.contracts.semantics import validate_semantics


@dataclass(frozen=True, slots=True)
class CommandCheck:
    check_id: str
    plan_item: str
    argv: tuple[str, ...]
    cwd: str = "."
    timeout: float = 60


@dataclass(frozen=True, slots=True)
class RequiredGate:
    validation_plan_ref: ContractRef
    result_ref: ContractRef | None
    gate: str
    scope: tuple[str, ...]
    target_ref: ContractRef


@dataclass(frozen=True, slots=True)
class CheckpointSpec:
    checkpoint_id: str
    commands: tuple[CommandCheck, ...]
    deliverables: dict[str, list[str]]
    allowed_paths: tuple[str, ...]
    review_items: tuple[str, ...] = ()
    required_gates: tuple[RequiredGate, ...] = ()

    def to_json(self):
        value = asdict(self)
        for key in ("commands", "allowed_paths", "review_items", "required_gates"):
            value[key] = list(value[key])
        for command in value["commands"]:
            command["argv"] = list(command["argv"])
        for item, gate in zip(value["required_gates"], self.required_gates, strict=True):
            item.update(
                validation_plan_ref=gate.validation_plan_ref.to_json(),
                result_ref=None if gate.result_ref is None else gate.result_ref.to_json(),
                target_ref=gate.target_ref.to_json(),
                scope=list(gate.scope),
            )
        return value

    @classmethod
    def from_json(cls, value):
        return cls(
            value["checkpoint_id"],
            tuple(CommandCheck(**command) for command in value["commands"]),
            value["deliverables"],
            tuple(value["allowed_paths"]),
            tuple(value["review_items"]),
            tuple(
                RequiredGate(
                    ContractRef.from_json(gate["validation_plan_ref"]),
                    None
                    if gate["result_ref"] is None
                    else ContractRef.from_json(gate["result_ref"]),
                    gate["gate"],
                    tuple(gate["scope"]),
                    ContractRef.from_json(gate["target_ref"]),
                )
                for gate in value["required_gates"]
            ),
        )


@dataclass(frozen=True, slots=True)
class TechnicalReview:
    actor_id: str
    accepted: bool
    criterion_ids: tuple[str, ...]
    artifact_identity: dict
    findings: tuple[str, ...] = ()


def relative_path(value, *, directory=False):
    if directory and value == ".":
        return value
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "\\" in value
        or ":" in value
    ):
        raise IntegrityError("Use a portable relative workspace path.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(
            item in {".", ".."}
            or PureWindowsPath(item).is_reserved()
            or item.endswith((".", " "))
            or any(ord(char) < 32 for char in item)
            for item in path.parts
        )
    ):
        raise IntegrityError("The workspace path is unsafe.")
    if any(item in {".git", ".corinthos", ".nukytera", ".agentforge"} for item in path.parts):
        raise IntegrityError("Execution paths cannot target private state or Git internals.")
    return value


def safe_workspace_path(root, relative, *, directory=False):
    relative_path(relative, directory=directory)
    path = root
    for component in () if relative == "." else PurePosixPath(relative).parts:
        path = path / component
        info = path.lstat()
        if is_link(info):
            raise IntegrityError("Workspace verification cannot follow links.")
    if not path.resolve(strict=True).is_relative_to(root):
        raise IntegrityError("The verification path escapes its workspace.")
    return path


def _digest_file(path):
    info = path.lstat()
    if is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise IntegrityError("Evidence requires an ordinary unlinked regular file.")
    if info.st_size > 67_108_864:
        raise IntegrityError("A workspace file exceeds the bounded snapshot limit.")
    with path.open("rb") as stream:
        if not os.path.samestat(info, os.fstat(stream.fileno())):
            raise IntegrityError("A workspace file changed while opening its snapshot.")
        digest = sha256(stream.read()).hexdigest()
        if os.fstat(stream.fileno()).st_mtime_ns != info.st_mtime_ns:
            raise IntegrityError("A workspace file changed during its snapshot.")
    return {"sha256": digest, "size": info.st_size}


def workspace_snapshot(root):
    """Hash source files while excluding local state, environments and generated caches."""
    files = {}
    for parent, directories, filenames in os.walk(root, followlinks=False):
        current = Path(parent)
        kept = []
        for name in sorted(directories):
            if (
                name
                in {
                    ".git",
                    ".corinthos",
                    ".nukytera",
                    ".agentforge",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "node_modules",
                    "build",
                    "dist",
                }
                or name.startswith(".venv")
                or name.endswith(".egg-info")
            ):
                continue
            if is_link((current / name).lstat()):
                raise IntegrityError("A source snapshot cannot traverse linked directories.")
            kept.append(name)
        directories[:] = kept
        for name in sorted(filenames):
            if name.endswith((".pyc", ".pyo")):
                continue
            path = current / name
            files[path.relative_to(root).as_posix()] = _digest_file(path)
            if len(files) > 10_000:
                raise IntegrityError("The workspace exceeds the bounded source inventory limit.")
    identity = {"snapshot_id": sha256(canonical_json(files).encode("utf-8")).hexdigest()}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        commit = result.stdout.decode("ascii").strip()
        if (
            result.returncode == 0
            and len(commit) == 40
            and all(char in "0123456789abcdef" for char in commit)
        ):
            identity["commit"] = commit
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        pass
    return {"artifact_identity": identity, "files": files}


def write_artifact(store, attempt_id, name, data):
    base = private_directory(store.database_path.parent.parent, "artifacts", create=True)
    parent = base
    for component in ("runtime", attempt_id):
        if not component or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
            for char in component
        ):
            raise IntegrityError("The runtime evidence identity is invalid.")
        parent = parent / component
        parent.mkdir(mode=0o700, exist_ok=True)
        info = parent.lstat()
        if is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise IntegrityError("Runtime evidence directories must be ordinary local directories.")
    path = parent / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    relative = path.relative_to(base).as_posix()
    digest = sha256(data).hexdigest()
    store.verify_artifact(relative, digest)
    return {"path": relative, "sha256": digest, "size": len(data)}


def command_check(store, root, attempt_id, check, cancel):
    """Run the already bound argv directly and retain bounded actual output privately."""
    cwd = safe_workspace_path(root, check.cwd, directory=True)
    started = monotonic()
    try:
        managed = start_process(
            list(check.argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            env=os.environ.copy(),
        )
        process = managed.process
    except OSError as error:
        return {
            "check_id": check.check_id,
            "plan_item": check.plan_item,
            "state": "FAILED",
            "error": "CHECK_START_FAILED",
            "cleanup_confirmed": getattr(error, "cleanup_confirmed", True),
            "exit_code": None,
        }
    chunks = queue.Queue(maxsize=16)
    stop = threading.Event()

    def read():
        try:
            while data := process.stdout.read(65_536):
                while not stop.is_set():
                    try:
                        chunks.put(data, timeout=0.05)
                        break
                    except queue.Full:
                        continue
            while not stop.is_set():
                try:
                    chunks.put(None, timeout=0.05)
                    break
                except queue.Full:
                    continue
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    output, state, ended, cleanup = bytearray(), None, False, True
    try:
        while not ended or process.poll() is None:
            if cancel.is_set():
                state = "INTERRUPTED"
                break
            if monotonic() - started >= check.timeout:
                state = "TIMEOUT"
                break
            try:
                data = chunks.get(timeout=0.05)
            except queue.Empty:
                continue
            if data is None:
                ended = True
            elif len(output) + len(data) > 8_388_608:
                state = "OUTPUT_LIMIT"
                break
            else:
                output.extend(data)
    finally:
        cleanup = managed.finish()
        stop.set()
        if cleanup:
            process.stdout.close()
        reader.join(timeout=0.2)
    artifact = write_artifact(
        store,
        attempt_id,
        "check-" + sha256(check.check_id.encode()).hexdigest()[:16] + ".log",
        bytes(output),
    )
    return {
        "check_id": check.check_id,
        "plan_item": check.plan_item,
        "state": state or ("PASSED" if process.returncode == 0 else "FAILED"),
        "exit_code": process.returncode,
        "cleanup_confirmed": cleanup,
        "duration_seconds": monotonic() - started,
        "evidence": artifact,
    }


class ValidationGateConsumer:
    """Consume exact published results, retaining missing formal gates as unverified."""

    def __init__(self, store):
        self.store = store

    def _history(self, kind, project_id, *, exclude=None):
        return [
            self.store.get(
                ContractRef(
                    row["contract_id"], row["revision_id"], row["contract_type"], row["project_id"]
                )
            )
            for row in self.store.list_events()
            if row["contract_type"] == kind
            and row["project_id"] == project_id
            and row["revision_id"] != exclude
        ]

    def applicable(self, workflow_ref, checkpoint_id):
        references = {}
        for document in self._history("VALIDATION", workflow_ref.project_id):
            active = self.store.resolve_active(document["metadata"]["contract_id"])
            if active is None:
                continue
            payload = active["payload"]
            scope = payload["validation_scope"]
            if (
                payload["gate_policy"]["gate"] == "CHECKPOINT"
                and scope["level"] == "CHECKPOINT"
                and scope["target_contract_ref"] == workflow_ref.to_json()
                and checkpoint_id in scope["target_ids"]
            ):
                reference = ContractRef.from_document(active)
                references[reference] = RequiredGate(
                    reference, None, "CHECKPOINT", tuple(scope["target_ids"]), workflow_ref
                )
        return list(references.values())

    def consume(self, required, artifact_identity):
        observation = {
            "validation_plan_ref": required.validation_plan_ref.to_json(),
            "gate": required.gate,
            "scope": list(required.scope),
            "state": "NOT_VERIFIED",
            "result_ref": None,
        }
        try:
            plan = self.store.get(required.validation_plan_ref)
            if plan is None:
                observation["reason"] = "The exact required Validation plan has not been published."
                return observation
            if self.store.resolve_active(required.validation_plan_ref.contract_id) != plan:
                raise IntegrityError("The exact Validation plan is unavailable or stale.")
            scope = plan["payload"]["validation_scope"]
            if (
                scope["target_contract_ref"] != required.target_ref.to_json()
                or set(scope["target_ids"]) != set(required.scope)
                or plan["payload"]["gate_policy"]["gate"] != required.gate
            ):
                raise IntegrityError("The Validation plan has a different target, gate or scope.")
            result = (
                self.store.get(required.result_ref) if required.result_ref is not None else None
            )
            if required.result_ref is None:
                candidates = [
                    document
                    for document in self._history(
                        "VALIDATION_RESULT", required.target_ref.project_id
                    )
                    if document["payload"]["validation_plan_ref"]
                    == required.validation_plan_ref.to_json()
                    and document["payload"]["target_and_execution"]["artifact_identity"]
                    == artifact_identity
                ]
                result = candidates[-1] if candidates else None
            if result is None:
                observation["reason"] = (
                    "A real result for this exact current artifact is unavailable."
                )
                return observation
            reference = ContractRef.from_document(result)
            observation["result_ref"] = reference.to_json()
            if (
                reference.contract_type != "VALIDATION_RESULT"
                or reference.project_id != required.target_ref.project_id
            ):
                raise IntegrityError("The supplied result has another project or type.")
            payload = result["payload"]
            execution = payload["target_and_execution"]
            if (
                payload["validation_plan_ref"] != required.validation_plan_ref.to_json()
                or execution["artifact_identity"] != artifact_identity
            ):
                raise IntegrityError("The result is bound to another plan or artifact.")
            if (
                result["metadata"]["provenance"]["engine"] != "VALIDATION"
                or execution["status"] != "COMPLETED"
            ):
                raise IntegrityError("The result is incomplete or has no Validation provenance.")
            if datetime.fromisoformat(result["metadata"]["created_at"]) > datetime.now(UTC):
                raise IntegrityError("The result is dated after the current observation.")
            for document in (plan, result):
                validate_schema(document)
                validate_semantics(
                    document,
                    self.store.get,
                    self.store.resolve_active,
                    history=lambda kind, project: self._history(
                        kind, project, exclude=reference.revision_id
                    ),
                    verify_artifact=self.store.verify_artifact,
                )
            gate = payload["gate_assessment"]
            if (
                gate["state"] != "SATISFIED"
                or gate["gate"] != required.gate
                or gate["scope"] != scope["level"]
            ):
                raise IntegrityError("The published Validation gate remains blocked.")
            observation.update(
                state="SATISFIED",
                reason="The exact published result and retained evidence satisfy this gate.",
            )
        except (ValueError, KeyError, TypeError, OSError, RecursionError):
            observation.update(
                state="BLOCKED",
                reason="Published Validation evidence is missing, stale, incomplete or inadmissible.",
            )
        return observation
