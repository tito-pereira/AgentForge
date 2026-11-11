# SPDX-License-Identifier: MPL-2.0
"""Frozen report captures and completion receipts over existing private artifacts."""

import json
import os
import re
import stat
from hashlib import sha256
from uuid import uuid4

from corinthos.contracts import (
    ConflictError,
    ContractRef,
    ContractStore,
    IntegrityError,
    SchemaError,
    StoreError,
)
from corinthos.contracts.artifacts import is_link, private_directory
from corinthos.contracts.model import canonical_json
from corinthos.contracts.schema import validate_schema

_DRAFT = re.compile(r"report-draft-[0-9a-f]{32}")
_LIMIT = 8 * 1024 * 1024


def content_digest(value):
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bytes(value):
    data = canonical_json(value).encode("utf-8")
    if len(data) > _LIMIT:
        raise IntegrityError("Report capture exceeds the bounded private manifest size.")
    return data


def _read(path):
    try:
        info = path.lstat()
        if is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise IntegrityError("Report-owned files must be ordinary unlinked files.")
        if info.st_size > _LIMIT:
            raise IntegrityError("Report-owned file exceeds the supported size.")
        with path.open("rb") as stream:
            if not os.path.samestat(info, os.fstat(stream.fileno())):
                raise IntegrityError("The report-owned file changed while opening.")
            data = stream.read(_LIMIT + 1)
        value = json.loads(data)
        if not isinstance(value, dict) or _bytes(value) != data:
            raise ValueError
        return value
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise IntegrityError(
            "Report-owned state is incomplete or unreadable. Preserve it for inspection."
        ) from None


def _write(path, value):
    data = _bytes(value)
    if path.exists() or path.is_symlink():
        if _read(path) != value:
            raise ConflictError("A report-owned completion file already has different content.")
        return
    temporary = path.with_name("staging-" + uuid4().hex + ".json")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if _read(path) != value:
            raise IntegrityError("Report-owned write verification failed.")
    except OSError:
        raise StoreError("Cannot complete the report-owned artifact write.") from None


class ReportRepository:
    """Store immutable capture packages without changing the shared database schema."""

    def __init__(self, store):
        if not isinstance(store, ContractStore):
            raise TypeError("ReportRepository requires a ContractStore.")
        self.store = store

    def _base(self, *, create=False):
        root = self.store.database_path.parent.parent
        private = private_directory(root)
        if not create and not os.path.lexists(private / "artifacts"):
            return None
        base = private_directory(root, "artifacts", create=create)
        directory = base / "runtime"
        try:
            if create:
                directory.mkdir(mode=0o700, exist_ok=True)
            info = directory.lstat()
            if is_link(info) or not stat.S_ISDIR(info.st_mode):
                raise IntegrityError("Report storage requires an ordinary private directory.")
            return directory
        except FileNotFoundError:
            return None
        except OSError:
            raise StoreError("Cannot open report-owned artifact storage.") from None

    def _directory(self, draft_id):
        if not isinstance(draft_id, str) or not _DRAFT.fullmatch(draft_id):
            raise IntegrityError("An exact report draft identity is required.")
        base = self._base()
        if base is None:
            raise IntegrityError("The report draft was not found.")
        path = base / draft_id
        try:
            info = path.lstat()
            if is_link(info) or not stat.S_ISDIR(info.st_mode):
                raise IntegrityError("The report draft directory is unsafe.")
            return path
        except OSError:
            raise IntegrityError("The report draft was not found.") from None

    def freeze(self, document, manifest, *, draft_id=None):
        validate_schema(document)
        ref = ContractRef.from_document(document)
        if ref.contract_type != "EVIDENCE_REPORT":
            raise IntegrityError("Only an Evidence & Report Contract can be frozen here.")
        draft_id = draft_id or "report-draft-" + uuid4().hex
        if not _DRAFT.fullmatch(draft_id):
            raise IntegrityError("Invalid report draft identity.")
        manifest = json.loads(_bytes(manifest))
        if manifest.get("report_ref") != ref.to_json() or manifest.get(
            "content_sha256"
        ) != content_digest(document["payload"]):
            raise IntegrityError("The generation manifest differs from the report content.")
        manifest_hash = content_digest(manifest)
        if (
            document["metadata"]["provenance"]["source"]
            != "report-manifest-sha256:" + manifest_hash
        ):
            raise IntegrityError("The report does not bind its generation manifest.")
        package = {
            "draft_id": draft_id,
            "document": document,
            "document_sha256": content_digest(document),
            "manifest": manifest,
            "manifest_sha256": manifest_hash,
        }
        base = self._base(create=True)
        path = base / draft_id
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            raise ConflictError("The report draft identity already exists.") from None
        _write(path / "frozen.json", package)
        return self.get(draft_id)

    def get(self, draft_id):
        path = self._directory(draft_id)
        package = _read(path / "frozen.json")
        if set(package) != {
            "draft_id",
            "document",
            "document_sha256",
            "manifest",
            "manifest_sha256",
        }:
            raise IntegrityError("The frozen report package is inconsistent.")
        document, manifest = package["document"], package["manifest"]
        if not isinstance(manifest, dict) or not isinstance(document, dict):
            raise IntegrityError("The frozen report or generation manifest has an invalid shape.")
        try:
            validate_schema(document)
        except SchemaError:
            raise IntegrityError("The frozen report document is not schema-valid.") from None
        if (
            set(manifest)
            != {
                "version",
                "report_ref",
                "content_sha256",
                "source_watermark",
                "source_manifest",
                "delivery_provenance",
                "request",
                "reason",
            }
            or type(manifest["version"]) is not int
            or manifest["version"] != 1
            or not isinstance(manifest["source_manifest"], dict)
            or not isinstance(manifest["delivery_provenance"], dict)
            or not isinstance(manifest["request"], dict)
            or not isinstance(manifest["reason"], str)
            or not isinstance(manifest["source_watermark"], dict)
        ):
            raise IntegrityError("The generation manifest has an invalid shape.")
        ref = ContractRef.from_document(document)
        if (
            package["draft_id"] != draft_id
            or ref.contract_type != "EVIDENCE_REPORT"
            or package["document_sha256"] != content_digest(document)
            or package["manifest_sha256"] != content_digest(manifest)
            or manifest.get("report_ref") != ref.to_json()
            or manifest.get("content_sha256") != content_digest(document["payload"])
            or document["metadata"]["provenance"]["source"]
            != "report-manifest-sha256:" + content_digest(manifest)
        ):
            raise IntegrityError("The frozen report or generation manifest digest differs.")
        return package

    def list_drafts(self):
        base = self._base()
        if base is None:
            return []
        drafts = []
        for path in sorted(base.iterdir()):
            if not _DRAFT.fullmatch(path.name):
                continue
            try:
                package = self.get(path.name)
            except IntegrityError as error:
                drafts.append({"draft_id": path.name, "state": "INCOMPLETE", "reason": str(error)})
                continue
            drafts.append(
                {
                    "draft_id": path.name,
                    "report_ref": ContractRef.from_document(package["document"]).to_json(),
                    "document_sha256": package["document_sha256"],
                }
            )
        return drafts

    def complete(self, draft_id, reference):
        package = self.get(draft_id)
        expected = ContractRef.from_document(package["document"])
        if reference != expected or self.store.get(reference) != package["document"]:
            raise IntegrityError("Completion requires the exact Kernel-published report.")
        receipt = {
            "report_ref": reference.to_json(),
            "document_sha256": package["document_sha256"],
            "manifest_sha256": package["manifest_sha256"],
        }
        _write(self._directory(draft_id) / "publication.json", receipt)
        return reference

    def find(self, reference):
        for item in self.list_drafts():
            if item.get("report_ref") == reference.to_json():
                package = self.get(item["draft_id"])
                published = self.store.get(reference)
                if published is not None and (
                    package["document"] != published
                    or published["metadata"]["provenance"]["source"]
                    != "report-manifest-sha256:" + content_digest(package["manifest"])
                ):
                    raise IntegrityError(
                        "The private generation manifest does not match its Kernel-published report."
                    )
                return package
        return None
