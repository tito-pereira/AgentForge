# SPDX-License-Identifier: MPL-2.0
"""Bounded observations of an existing owner-held delivery record and package."""

import json
import os
import subprocess
from datetime import UTC, datetime
from email.parser import Parser
from hashlib import sha256
from pathlib import Path
from time import monotonic
from zipfile import BadZipFile, ZipFile

from corinthos.contracts import ContractRef, IntegrityError
from corinthos.contracts.artifacts import is_link
from corinthos.validation.procedures import file_hash
from corinthos.workflow.verification import workspace_snapshot


def _ordinary_path(value):
    raw = Path(value).absolute()
    current = Path(raw.anchor)
    try:
        for part in raw.parts[1:]:
            current = current.parent if part == ".." else current / part
            if is_link(current.lstat()):
                raise IntegrityError("Delivery sources cannot follow redirected paths.")
        return Path(os.path.abspath(current))
    except OSError:
        raise IntegrityError("The delivery source path is unavailable.") from None


def _require_delivered_source(candidate, inventory, commit, wheel):
    started = monotonic()

    def git(*args):
        remaining = 10 - (monotonic() - started)
        if remaining <= 0:
            raise IntegrityError("The delivery source verification budget was exceeded.")
        return subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=" + str(candidate),
                "--no-optional-locks",
                "-C",
                str(candidate),
                *args,
            ],
            stderr=subprocess.DEVNULL,
            timeout=remaining,
        )

    try:
        listing = git("ls-tree", "-r", "-l", "-z", commit)
        if len(listing) > 4 * 1024 * 1024:
            raise IntegrityError("The delivered source tree exceeds its bounded inventory.")
        entries = [entry for entry in listing.split(b"\0") if entry]
        if len(entries) > 8192:
            raise IntegrityError("The delivered source tree has too many files.")
        names = set()
        total = 0
        for entry in entries:
            raw, encoded_name = entry.split(b"\t", 1)
            mode, kind, identity, size = raw.split()
            name = encoded_name.decode("utf-8")
            total += int(size)
            if mode not in (b"100644", b"100755") or kind != b"blob" or total > 256 * 1024 * 1024:
                raise IntegrityError("The delivered source contains an unsupported tree entry.")
            source = inventory["files"].get(name)
            canonical = git("cat-file", "blob", identity.decode("ascii"))
            if (
                source is None
                or source["size"] != len(canonical)
                or source["sha256"] != sha256(canonical).hexdigest()
            ):
                raise IntegrityError(
                    "The report candidate differs from its delivered source revision."
                )
            names.add(name)
        if set(inventory["files"]) != names | {wheel.name}:
            raise IntegrityError(
                "Unrecorded candidate files do not belong to this delivered package."
            )
    except IntegrityError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError):
        raise IntegrityError(
            "The delivered source revision could not be verified safely."
        ) from None


def _require_wheel_sources(archive, inventory):
    for item in archive.infolist():
        if not item.filename.endswith((".py", ".pyi")):
            continue
        source = inventory["files"].get(item.filename) or inventory["files"].get(
            "src/" + item.filename
        )
        if source is None or item.file_size != source["size"]:
            raise IntegrityError("A packaged source file does not match the delivered candidate.")
        if sha256(archive.read(item)).hexdigest() != source["sha256"]:
            raise IntegrityError("The wheel source bytes differ from the delivered candidate.")


def _observe_file(path, limit):
    path = _ordinary_path(path)
    try:
        if path.stat().st_size > limit:
            raise IntegrityError("The delivery source exceeds its supported size.")
        digest = file_hash(path)
        return {"path": str(path), "sha256": digest, "limit": limit}
    except OSError:
        raise IntegrityError("The delivery source is unavailable.") from None


def observe_delivery(
    path,
    project_ref,
    artifact_identity,
    *,
    candidate_root=None,
    executions=(),
    observe_availability=True,
):
    """Import only verified package/version and observed local launcher availability."""
    empty = {
        "product_version": "UNRECORDED",
        "previous_version": None,
        "delivery": "NOT_DELIVERED",
        "availability": False,
        "provenance": {},
        "gaps": [
            "No verified delivery record establishes product version, delivery or availability."
        ],
    }
    if path is None:
        return empty
    source = _observe_file(path, 1_048_576)
    try:
        document = json.loads(Path(source["path"]).read_bytes())
        if not isinstance(document, dict):
            raise ValueError
        recorded_project = ContractRef.from_json(document["project_ref"])
        package = document["built_package"]
        if recorded_project != project_ref or package["commit"] != artifact_identity.get("commit"):
            raise IntegrityError("The delivery record belongs to another Project or candidate.")
        execution = next(
            (item for item in executions if item["execution_id"] == document.get("execution")),
            None,
        )
        if (
            document.get("state") != "COMPLETED"
            or execution is None
            or not (execution.get("completion_recorded") or execution["state"] == "COMPLETED")
        ):
            empty["gaps"] = [
                "The captured Workflow history does not corroborate the recorded delivery completion."
            ]
            return empty
        workflow_ref = execution.get("workflow_ref")
        if workflow_ref is not None and workflow_ref not in document.get("plan_refs", []):
            raise IntegrityError("The delivery record does not cite its exact completed Workflow.")
        wheel_path = Path(package["wheel"])
        if not wheel_path.is_absolute():
            wheel_path = Path(source["path"]).parent / wheel_path
        wheel = _observe_file(wheel_path, 16 * 1024 * 1024)
        if wheel["sha256"] != package["sha256"]:
            raise IntegrityError("The delivered package digest differs from its original record.")
        if candidate_root is None:
            empty["gaps"] = [
                "Delivery cannot be bound to the complete candidate without its inventory."
            ]
            return empty
        candidate = _ordinary_path(candidate_root)
        inventory = workspace_snapshot(candidate, max_bytes=256 * 1024 * 1024, max_files=8192)
        identity = inventory["artifact_identity"]
        if (
            identity != artifact_identity
            or file_hash(candidate / wheel_path.name) != wheel["sha256"]
        ):
            raise IntegrityError(
                "The delivered package does not match the complete report candidate."
            )
        _require_delivered_source(candidate, inventory, package["commit"], wheel_path)
        with ZipFile(wheel["path"]) as archive:
            _require_wheel_sources(archive, inventory)
            metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1 or archive.getinfo(metadata[0]).file_size > 65_536:
                raise IntegrityError(
                    "The delivered wheel has ambiguous or oversized version metadata."
                )
            fields = Parser().parsestr(archive.read(metadata[0]).decode("utf-8"))
            version = fields.get("Version")
            name = fields.get("Name")
            if not version or not name or len(version) > 128 or len(name) > 128:
                raise IntegrityError(
                    "The delivered wheel does not establish a bounded product identity."
                )
        if (
            file_hash(wheel["path"]) != wheel["sha256"]
            or file_hash(source["path"]) != source["sha256"]
        ):
            raise IntegrityError("A delivery source changed during collection.")
        observed = [source, wheel]
        available = False
        gaps = []
        launcher = document.get("installed", {}).get("launcher")
        if not observe_availability:
            gaps.append("Current launcher availability was deliberately not inspected.")
        elif launcher:
            try:
                observed.append(_observe_file(launcher, 4 * 1024 * 1024))
                available = True
                gaps.append(
                    "Availability records a local launcher file, without a new functional execution check."
                )
            except IntegrityError:
                gaps.append("The recorded local launcher is currently unavailable or unsafe.")
        else:
            gaps.append("The delivery source contains no observable local launcher.")
        return {
            "product_version": version,
            "previous_version": None,
            "delivery": "DELIVERED",
            "availability": available,
            "provenance": {
                "observed_at": datetime.now(UTC).isoformat(),
                "project_ref": project_ref.to_json(),
                "artifact_identity": artifact_identity,
                "package_name": name,
                "package_sha256": wheel["sha256"],
                "execution_id": execution["execution_id"],
                "files": observed,
            },
            "gaps": gaps,
        }
    except IntegrityError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, BadZipFile, OSError):
        raise IntegrityError(
            "The delivery record has unsupported or incomplete package provenance."
        ) from None


def require_delivery_unchanged(provenance):
    """Check the bounded external sources again before committing a current report."""
    for item in provenance.get("files", []):
        current = _observe_file(item["path"], item["limit"])
        if current != item:
            raise IntegrityError("Delivery provenance changed after report capture.")
