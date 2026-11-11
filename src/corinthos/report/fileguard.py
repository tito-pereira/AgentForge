# SPDX-License-Identifier: MPL-2.0
"""Bounded file preflight and metadata-only guards for report publication."""

import os
import re
import stat
import subprocess
from hashlib import sha256
from pathlib import Path

from corinthos.contracts import ConflictError, IntegrityError
from corinthos.contracts.artifacts import _COMPONENT, is_link
from corinthos.workflow.verification import _SNAPSHOT_IGNORED_DIRECTORIES

_EXTRA_LIMIT = 21 * 1024 * 1024


def _path(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise IntegrityError("Report guards require exact absolute source paths.")
    return path


def _metadata(path):
    records = []
    for current in (*reversed(path.parents), path):
        try:
            info = current.lstat()
        except FileNotFoundError:
            records.append({"path": str(current), "missing": True})
            break
        item = {
            "path": str(current),
            "dev": info.st_dev,
            "ino": info.st_ino,
            "mode": info.st_mode,
            "redirected": is_link(info),
        }
        if current == path or not stat.S_ISDIR(info.st_mode) or is_link(info):
            item.update(
                size=info.st_size,
                mtime_ns=info.st_mtime_ns,
                ctime_ns=info.st_ctime_ns,
                nlink=info.st_nlink,
            )
        records.append(item)
        if current != path and (not stat.S_ISDIR(info.st_mode) or is_link(info)):
            break
    return records


def _ordinary_file(path):
    records = _metadata(path)
    for parent in records[:-1]:
        if parent.get("missing") or parent["redirected"] or not stat.S_ISDIR(parent["mode"]):
            raise IntegrityError("A report source parent is unavailable or redirected.")
    leaf = records[-1]
    if (
        leaf["path"] != str(path)
        or leaf.get("missing")
        or leaf["redirected"]
        or not stat.S_ISREG(leaf["mode"])
        or leaf["nlink"] != 1
    ):
        raise IntegrityError("A report source must be an ordinary unlinked file.")
    return path.lstat()


def _extras(values):
    result, limit = [], 0
    for value in values:
        path = _path(value["path"])
        bound, digest = value["limit"], value["sha256"]
        if (
            type(bound) is not int
            or bound < 0
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise IntegrityError("An extra report source requires a bounded exact digest.")
        limit += bound
        if limit > _EXTRA_LIMIT or len(result) >= 32:
            raise IntegrityError("Additional report sources exceed their verification budget.")
        result.append({"path": str(path), "limit": bound, "sha256": digest})
    return result


def _verify_extra(item):
    path = _path(item["path"])
    info = _ordinary_file(path)
    if info.st_size > item["limit"]:
        raise IntegrityError("An additional report source exceeds its declared bound.")
    with path.open("rb") as stream:
        if not os.path.samestat(info, os.fstat(stream.fileno())):
            raise IntegrityError("An additional report source changed while being opened.")
        data = stream.read(info.st_size + 1)
        if len(data) != info.st_size or os.fstat(stream.fileno()).st_mtime_ns != info.st_mtime_ns:
            raise IntegrityError("An additional report source changed during inspection.")
    if sha256(data).hexdigest() != item["sha256"]:
        raise IntegrityError("An additional report source no longer has its recorded digest.")


def _tree(root, *, include_ignored=False):
    result, count = [], 0
    for parent, directories, filenames in os.walk(root, followlinks=False):
        current = Path(parent)
        kept = [
            name
            for name in sorted(directories)
            if include_ignored
            or (
                name not in _SNAPSHOT_IGNORED_DIRECTORIES
                and not name.startswith(".venv")
                and not name.endswith(".egg-info")
            )
        ]
        for name in kept:
            if is_link((current / name).lstat()):
                raise IntegrityError("A report candidate directory is redirected.")
        directories[:] = kept
        files = [
            name
            for name in sorted(filenames)
            if include_ignored
            or (not name.endswith((".pyc", ".pyo")) and not (current == root and name == ".git"))
        ]
        count += len(files)
        if count > 8192:
            raise IntegrityError("The report candidate exceeds its metadata inventory bound.")
        info = current.lstat()
        if is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise IntegrityError("A report candidate directory is unsafe.")
        result.append(
            {
                "path": str(current),
                "dev": info.st_dev,
                "ino": info.st_ino,
                "mode": info.st_mode,
                "directories": kept,
                "files": files,
            }
        )
    return result


def _git_paths(candidate):
    root = Path(candidate["root"])
    if "commit" not in candidate["inventory"]["artifact_identity"]:
        return [root / ".git"]
    try:
        process = subprocess.run(
            [
                "git",
                "-c",
                "safe.directory=" + str(root),
                "--no-optional-locks",
                "-C",
                str(root),
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
                "--git-path",
                "HEAD",
                "--git-path",
                "packed-refs",
                "--git-path",
                "config",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=5,
        )
        lines = process.stdout.decode("utf-8").splitlines()
        if len(lines) != 4:
            raise ValueError
        gitdir, head, packed, config = map(_path, lines)
        paths = [
            root / ".git",
            head,
            packed,
            config,
            gitdir / "commondir",
            gitdir / "gitdir",
            gitdir / "config.worktree",
        ]
        if _ordinary_file(head).st_size > 4096:
            raise IntegrityError("Git HEAD exceeds its supported metadata size.")
        raw = head.read_text("utf-8")
        if raw.startswith("ref: "):
            reference = raw.removeprefix("ref: ").strip()
            if (
                not reference.startswith("refs/")
                or any(part in {"", ".", ".."} for part in reference.split("/"))
                or any(character in reference for character in "\\:\x00")
            ):
                raise IntegrityError("The candidate Git reference is unsafe.")
            process = subprocess.run(
                [
                    "git",
                    "-c",
                    "safe.directory=" + str(root),
                    "--no-optional-locks",
                    "-C",
                    str(root),
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    reference,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=5,
            )
            paths.append(_path(process.stdout.decode("utf-8").strip()))
        return paths
    except (OSError, ValueError, subprocess.SubprocessError):
        raise IntegrityError("The exact Git metadata cannot be guarded safely.") from None


def _observe(paths, candidate_root, *, include_ignored=False):
    return {
        "files": [{"path": str(path), "metadata": _metadata(path)} for path in paths],
        "tree": _tree(candidate_root, include_ignored=include_ignored)
        if candidate_root is not None
        else [],
        "include_ignored": include_ignored,
    }


def prepare(store, manifest, verify_inputs, *, extra_files=()):
    """Bind bounded outside-writer hashes to stable file metadata for the writer guard."""
    extras = _extras(extra_files)
    paths = [Path(item["path"]) for item in extras]
    for item in manifest["evidence"]:
        relative = item["ref"]["path"]
        if any(not _COMPONENT.fullmatch(part) for part in relative.split("/")):
            raise IntegrityError("Report evidence has an unsafe private path.")
        paths.append(store.database_path.parent / "artifacts" / relative)
    candidate = manifest.get("candidate")
    root = _path(candidate["root"]) if candidate is not None else None
    git_paths = []
    if candidate is not None:
        paths.extend(root / name for name in candidate["inventory"]["files"])
        git_paths = _git_paths(candidate)
        paths.extend(git_paths)
    paths = sorted(set(paths), key=str)
    sealed = candidate is not None and "build_id" in candidate["inventory"]["artifact_identity"]
    before = _observe(paths, root, include_ignored=sealed)
    verify_inputs()
    for item in extras:
        _verify_extra(item)
    if candidate is not None and _git_paths(candidate) != git_paths:
        raise ConflictError("Git metadata indirection changed during report preflight.")
    after = _observe(paths, root, include_ignored=sealed)
    if after != before:
        raise ConflictError("Report file identities changed during publication preflight.")
    return after


def require_file_guard(guard):
    """Check only recorded paths and directory entries, with no hashing or subprocess."""
    try:
        files = [
            {"path": item["path"], "metadata": _metadata(_path(item["path"]))}
            for item in guard["files"]
        ]
        root = Path(guard["tree"][0]["path"]) if guard["tree"] else None
        sealed = guard.get("include_ignored", False)
        actual = {
            "files": files,
            "tree": _tree(root, include_ignored=sealed) if root is not None else [],
        }
        if "include_ignored" in guard:
            actual["include_ignored"] = sealed
        if actual != guard:
            raise ConflictError("Report source file metadata changed before publication.")
    except (OSError, KeyError, TypeError):
        raise ConflictError("Report source files became unavailable before publication.") from None
