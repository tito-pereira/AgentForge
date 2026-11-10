# SPDX-License-Identifier: MPL-2.0
"""Copy a quiescent legacy private store without rewriting its records."""

import ctypes
import errno
import os
import shutil
import sqlite3
import stat
import sys
from contextlib import closing
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory

from .artifacts import is_link
from .model import ConflictError, ContractRef, IntegrityError, StoreError, iter_references
from .schema import validate_schema
from .store import (
    _APPLICATION_ID,
    _REVISIONS,
    _SCHEMA_VERSION,
    ContractStore,
    _markers,
    _stored_document,
)


def _exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _directory(path: Path) -> None:
    info = path.lstat()
    if is_link(info) or not stat.S_ISDIR(info.st_mode):
        raise StoreError("Private migration directories must be unlinked directories.")


def _inventory(directory: Path) -> dict[str, str | None]:
    _directory(directory)
    entries = {}
    folded = set()
    pending = [directory]
    while pending:
        for path in pending.pop().iterdir():
            info = path.lstat()
            relative = path.relative_to(directory).as_posix()
            if relative.casefold() in folded or is_link(info):
                raise StoreError("Private migration contains a link or case-insensitive collision.")
            folded.add(relative.casefold())
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
                entries[relative] = None
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                with path.open("rb") as source:
                    if not os.path.samestat(info, os.fstat(source.fileno())):
                        raise ConflictError("A private file changed during migration.")
                    entries[relative] = file_digest(source, "sha256").hexdigest()
            else:
                raise StoreError("Private migration requires unlinked regular files.")
    return entries


def _check_database(database: Path) -> None:
    info = database.lstat()
    if is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise StoreError("The legacy state database must be an unlinked regular file.")
    if not info.st_mode & stat.S_IWUSR:
        raise StoreError("The legacy state database is read-only.")
    if any(
        _exists(database.with_name(database.name + suffix))
        for suffix in ("-wal", "-shm", "-journal")
    ):
        raise ConflictError(
            "Close the legacy store cleanly before migration. SQLite sidecars remain."
        )
    with database.open("rb") as source:
        header = source.read(20)
    if not header.startswith(b"SQLite format 3\x00"):
        raise StoreError("The legacy state database is not a valid SQLite file.")
    if header[18:20] != b"\x01\x01":
        raise StoreError("Migration requires a closed rollback-journal SQLite database.")


def _verify_snapshot(root: Path) -> None:
    store = ContractStore(root)
    with store._connection() as connection:
        documents = {}
        for row in connection.execute(_REVISIONS):
            document = _stored_document(row)
            validate_schema(document)
            documents[ContractRef.from_document(document)] = document
        expected_edges = set()
        for source, document in documents.items():
            for target in iter_references(document):
                if target.project_id != source.project_id or target not in documents:
                    raise IntegrityError("A migrated document has an unresolved exact reference.")
                expected_edges.add((source.revision_id, target.revision_id))
            payload = document["payload"]
            if source.contract_type == "VALIDATION_RESULT":
                evidence = payload["evidence_refs"]
            elif source.contract_type == "EVIDENCE_REPORT":
                evidence = payload["artifact_and_evidence_index"]
            else:
                evidence = ()
            for item in evidence:
                store.verify_artifact(item["path"], item["sha256"])
        if expected_edges != {
            tuple(row) for row in connection.execute("SELECT * FROM contract_references")
        }:
            raise IntegrityError("The migrated reference index disagrees with its documents.")
        if {ref.revision_id for ref in documents} != {
            row[0] for row in connection.execute("SELECT revision_id FROM audit_events")
        }:
            raise IntegrityError("The migrated audit events disagree with published revisions.")


def _promote(staged: Path, target: Path) -> None:
    if os.name == "nt":
        try:
            staged.rename(target)
        except FileExistsError:
            raise ConflictError(
                "The target .corinthos directory appeared during migration."
            ) from None
        return
    # A POSIX rename can replace an existing empty directory.
    rename = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if rename is None:
        raise StoreError("The platform does not support an atomic no-replace directory move.")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    at_fdcwd, rename_noreplace = -100, 1
    if rename(at_fdcwd, os.fsencode(staged), at_fdcwd, os.fsencode(target), rename_noreplace) != 0:
        if ctypes.get_errno() == errno.EEXIST:
            raise ConflictError("The target .corinthos directory appeared during migration.")
        raise StoreError("The filesystem refused the atomic no-replace directory move.")


def migrate_legacy_state(project_root: str | Path) -> bool:
    """Verify and copy .nukytera to .corinthos while preserving the original.

    The caller authorizes the project root and stops all users of both private
    directories, including artifact writers. An identical verified copy is a no-op.
    """
    try:
        root = Path(project_root).resolve(strict=True)
        _directory(root)
        legacy, target = root / ".nukytera", root / ".corinthos"
        if not _exists(legacy):
            return False
        _directory(legacy)
        database = legacy / "state.db"
        _check_database(database)
        uri = f"{database.as_uri()}?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=0, autocommit=True)) as connection:
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN EXCLUSIVE")
            _check_database(database)
            if _markers(connection) != (_APPLICATION_ID, _SCHEMA_VERSION):
                raise StoreError(
                    "The legacy state database application or schema version is unsupported."
                )
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise StoreError("The legacy state database failed its integrity check.")
            original = _inventory(legacy)
            if _exists(target):
                if _inventory(target) != original:
                    raise ConflictError(
                        "The existing .corinthos directory differs from the legacy store."
                    )
                _verify_snapshot(root)
                return False
            if os.name == "nt" and sys.version_info < (3, 12, 4):
                raise StoreError(
                    "Private Windows migration staging requires Python 3.12.4 or later."
                )
            with TemporaryDirectory(prefix=".corinthos-migration-", dir=root) as scratch:
                stage_root = Path(scratch)
                staged = stage_root / ".corinthos"
                shutil.copytree(legacy, staged, symlinks=True)
                if os.name != "nt":
                    staged.chmod(0o700)
                if _inventory(staged) != original:
                    raise IntegrityError("The private state copy does not match the original.")
                _verify_snapshot(stage_root)
                if _inventory(staged) != original or _inventory(legacy) != original:
                    raise ConflictError("Private state changed during migration.")
                if _exists(target):
                    raise ConflictError(
                        "The target .corinthos directory appeared during migration."
                    )
                _promote(staged, target)
                return True
    except sqlite3.Error as error:
        if getattr(error, "sqlite_errorcode", 0) & 255 in (
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        ):
            raise ConflictError("The legacy store is busy. Close it before migration.") from None
        raise StoreError("The legacy SQLite database cannot be verified safely.") from None
    except OSError:
        raise StoreError(
            "Private migration could not access or publish its files safely."
        ) from None
