# SPDX-License-Identifier: MPL-2.0
"""Typed independent procedures and bounded process observations."""

import os
import re
import stat
import subprocess
import threading
from hashlib import file_digest, sha256
from pathlib import Path, PurePosixPath
from time import monotonic

from corinthos.adapters.process_control import start_process
from corinthos.contracts import IntegrityError
from corinthos.contracts.artifacts import is_link
from corinthos.contracts.model import canonical_json

_SHA256 = re.compile(r"[a-f0-9]{64}")
_SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{20,})"
)
_OUTPUT_LIMIT = 1_048_576
_COMMAND_KEYS = {"argv", "timeout", "inputs", "success_line", "failure_line"}
_BINDING_KEYS = {"method", "required_evidence", "description", "command", "review_paths"}
COMPOUND_EVIDENCE = (
    "Observed check results and a technical review tied to the implementation commit."
)
_EVIDENCE_MODES = {
    "Independent check observation": (False, False),
    "Independent review record": (False, True),
    COMPOUND_EVIDENCE: (True, True),
}


def digest(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text(value, *, size=4096):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > size
        or "\x00" in value
        or _SECRET.search(value)
    ):
        raise IntegrityError("Use bounded nonempty procedure text without credentials.")
    return value


def _relative_file(value):
    _text(value)
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {".", ".."} for part in path.parts)
        or not path.parts
        or "\\" in value
        or ":" in value
    ):
        raise IntegrityError("Review paths must be portable candidate-relative file paths.")
    return value


def file_hash(path):
    """Hash a pinned, unlinked ordinary input, verifying the open file identity."""
    path = Path(path)
    try:
        info = path.lstat()
        if is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise IntegrityError("An evaluator input must be an unlinked ordinary file.")
        if path.resolve(strict=True) != path:
            raise IntegrityError("An evaluator input cannot traverse a redirected path.")
        with path.open("rb") as stream:
            if not os.path.samestat(info, os.fstat(stream.fileno())):
                raise IntegrityError("An evaluator input changed while being opened.")
            return file_digest(stream, "sha256").hexdigest()
    except (OSError, ValueError, RuntimeError):
        raise IntegrityError("An evaluator input cannot be read safely.") from None


def validate_binding(value):
    """Check the closed binding shape without requiring currently available tools."""
    if not isinstance(value, dict) or set(value) != _BINDING_KEYS:
        raise IntegrityError("A check needs one typed command, review, or both.")
    _text(value["method"])
    _text(value["description"])
    evidence = value["required_evidence"]
    paths = value["review_paths"]
    if not isinstance(evidence, list) or not evidence or not isinstance(paths, list):
        raise IntegrityError("Bind evidence kinds and review paths explicitly.")
    for item in evidence:
        _text(item)
    for path in paths:
        _relative_file(path)
    if len(set(evidence)) != len(evidence) or len(set(paths)) != len(paths):
        raise IntegrityError("Evidence kinds and review paths must be unique.")
    command = value["command"]
    for kind in evidence:
        modes = _EVIDENCE_MODES.get(kind)
        if modes is None:
            raise IntegrityError(
                "The required evidence kind has no supported observation procedure."
            )
        requires_command, requires_review = modes
        if (requires_command and command is None) or (requires_review and not paths):
            raise IntegrityError("The binding cannot produce the declared evidence kind.")
    if command is None:
        if not paths:
            raise IntegrityError("A review procedure needs exact inspected candidate paths.")
        return value
    if not isinstance(command, dict) or set(command) != _COMMAND_KEYS:
        raise IntegrityError("Invalid command observation binding.")
    argv, inputs = command["argv"], command["inputs"]
    if not isinstance(argv, list) or not argv or len(argv) > 64 or not isinstance(inputs, dict):
        raise IntegrityError("Bind a bounded executable argument list and pinned inputs.")
    for arg in argv:
        _text(arg, size=8192)
    if not Path(argv[0]).is_absolute() or argv[0] not in inputs:
        raise IntegrityError("The command executable must be absolute and pinned by its digest.")
    executable = Path(argv[0])
    if executable.suffix.casefold() in {
        ".bat",
        ".cmd",
        ".ps1",
        ".sh",
    } or executable.stem.casefold() in {
        "cmd",
        "powershell",
        "pwsh",
        "sh",
        "bash",
        "zsh",
        "fish",
    }:
        raise IntegrityError("Use a reviewed direct executable procedure without a shell wrapper.")
    if any(Path(arg).is_absolute() and arg not in inputs for arg in argv):
        raise IntegrityError("Bind every absolute command input by its digest.")
    for path, sha in inputs.items():
        _text(path)
        if not Path(path).is_absolute() or not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            raise IntegrityError("Evaluator inputs need absolute paths and exact SHA-256 digests.")
    if type(command["timeout"]) is not int or not 1 <= command["timeout"] <= 600:
        raise IntegrityError("Use a command timeout from 1 to 600 seconds.")
    for name in ("success_line", "failure_line"):
        line = command[name]
        if name == "failure_line" and line is None:
            continue
        _text(line, size=512)
        if any(char in line for char in "\r\n"):
            raise IntegrityError("Expected observations are exact single output lines.")
    if command["success_line"] == command["failure_line"]:
        raise IntegrityError("Success and failure observations must be different.")
    return value


def _environment(scratch):
    retained = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR"}
    return {
        **{k: v for k, v in os.environ.items() if k.upper() in retained},
        **{name: str(scratch) for name in ("TEMP", "TMP", "TMPDIR", "LOCALAPPDATA", "APPDATA")},
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def observe_command(command, candidate, scratch, cancel):
    """Execute a trusted reviewed procedure and report only admitted observations."""
    argv = [
        {"{candidate}": str(candidate), "{scratch}": str(scratch)}.get(arg, arg)
        for arg in command["argv"]
    ]
    record = {
        "argv": argv,
        "input_sha256": command["inputs"],
        "cwd": str(scratch),
        "timeout_seconds": command["timeout"],
        "environment": "Windows or POSIX launcher variables and isolated scratch paths",
    }
    try:
        if any(file_hash(path) != sha for path, sha in command["inputs"].items()):
            return {**record, "state": "INPUT_CHANGED", "cleanup_confirmed": True}
        managed = start_process(
            argv,
            cwd=scratch,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_environment(scratch),
            shell=False,
        )
    except (OSError, IntegrityError) as error:
        return {
            **record,
            "state": "UNAVAILABLE",
            "cleanup_confirmed": getattr(error, "cleanup_confirmed", True),
        }
    process = managed.process
    started = monotonic()
    output = bytearray()
    drained = threading.Event()
    error = []

    def drain():
        try:
            while chunk := process.stdout.read(65_536):
                if len(output) + len(chunk) > _OUTPUT_LIMIT:
                    error.append("OUTPUT_LIMIT")
                    return
                output.extend(chunk)
        except (OSError, ValueError):
            error.append("OUTPUT_ERROR")
        finally:
            drained.set()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    state = None
    try:
        while not drained.is_set() or process.poll() is None:
            if cancel.wait(0.05):
                state = "INTERRUPTED"
                break
            if error or monotonic() - started >= command["timeout"]:
                state = error[0] if error else "TIMEOUT"
                break
    finally:
        cleanup = managed.finish()
        if cleanup:
            process.stdout.close()
        reader.join(timeout=0.2)
    raw = bytes(output)
    record.update(
        cleanup_confirmed=cleanup,
        exit_code=process.returncode,
        output_sha256=sha256(raw).hexdigest(),
        observed_output_bytes=len(raw),
        elapsed_seconds=round(monotonic() - started, 6),
    )
    if state or error or not cleanup or reader.is_alive():
        return {**record, "state": state or (error[0] if error else "CLEANUP_UNCONFIRMED")}
    try:
        lines = raw.decode("utf-8").splitlines()
        if any(file_hash(path) != sha for path, sha in command["inputs"].items()):
            return {**record, "state": "INPUT_CHANGED"}
    except (UnicodeError, IntegrityError):
        return {**record, "state": "OUTPUT_OR_INPUT_UNVERIFIED"}
    success, failure = command["success_line"], command["failure_line"]
    record["observed_details"] = [
        _SECRET.sub("[redacted]", line[:512])
        for line in lines
        if line.startswith(("Observed: ", "Observed contradiction: "))
    ][:8]
    if process.returncode == 0 and lines.count(success) == 1 and failure not in lines:
        return {**record, "state": "CONFORMANT", "observed_line": success}
    if process.returncode == 1 and failure and lines.count(failure) == 1 and success not in lines:
        return {**record, "state": "NONCONFORMANT", "observed_line": failure}
    return {**record, "state": "ASSERTION_NOT_OBSERVED"}
