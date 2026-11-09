# SPDX-License-Identifier: MPL-2.0
"""Exact contract identities and the kernel's public errors."""

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
REFERENCE_FIELDS = ("contract_id", "revision_id", "contract_type", "project_id")


class ContractError(ValueError):
    """Base error for contract kernel operations."""


class SchemaError(ContractError):
    """Invalid document shape or unsupported schema version."""


class IntegrityError(ContractError):
    """Invalid contract relationship or inconsistent persisted data."""


class AuthorityError(IntegrityError):
    """Publication lacks the applicable verified authority."""


class ConflictError(IntegrityError):
    """Conflicting identity, lineage, or concurrent store operation."""


class StoreError(ContractError):
    """The local store cannot be opened, used, or migrated safely."""


class ContractType(StrEnum):
    PROJECT = "PROJECT"
    WORKFLOW = "WORKFLOW"
    MODULE = "MODULE"
    TECHNOLOGY_DECISION = "TECHNOLOGY_DECISION"
    VALIDATION = "VALIDATION"
    VALIDATION_RESULT = "VALIDATION_RESULT"
    EVIDENCE_REPORT = "EVIDENCE_REPORT"
    PROJECT_REVISION_REQUEST = "PROJECT_REVISION_REQUEST"


@dataclass(frozen=True, slots=True)
class ContractRef:
    contract_id: str
    revision_id: str
    contract_type: ContractType
    project_id: str

    def __post_init__(self) -> None:
        for value in (self.contract_id, self.revision_id, self.project_id):
            if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
                raise SchemaError("Invalid contract reference identifier.")
        try:
            contract_type = ContractType(self.contract_type)
        except (ValueError, TypeError):
            raise SchemaError("Unknown contract reference type.") from None
        object.__setattr__(self, "contract_type", contract_type)

    @classmethod
    def from_json(cls, value: Mapping) -> "ContractRef":
        if not isinstance(value, Mapping) or set(value) != set(REFERENCE_FIELDS):
            raise SchemaError("An exact reference requires four identity fields.")
        return cls(*(value[key] for key in REFERENCE_FIELDS))

    @classmethod
    def from_document(cls, document: dict) -> "ContractRef":
        try:
            return cls(*(document["metadata"][key] for key in REFERENCE_FIELDS))
        except (KeyError, TypeError):
            raise SchemaError("Contract metadata has incomplete identity.") from None

    def to_json(self) -> dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "revision_id": self.revision_id,
            "contract_type": self.contract_type.value,
            "project_id": self.project_id,
        }


def canonical_json(value: object) -> str:
    """Serialize JSON without coercing keys or accepting non-finite numbers."""

    def check(node: object) -> None:
        if type(node) is dict:
            for key, item in node.items():
                if type(key) is not str:
                    raise SchemaError("JSON object keys must be strings.")
                check(item)
        elif type(node) is list:
            for item in node:
                check(item)
        elif type(node) not in (str, int, float, bool, type(None)):
            raise SchemaError("Contract data must contain JSON values.")

    try:
        check(value)
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except SchemaError:
        raise
    except (ValueError, RecursionError):
        raise SchemaError("Contract data is not finite, serializable JSON.") from None


def iter_references(value: object) -> Iterator[ContractRef]:
    if isinstance(value, dict):
        if set(value) == set(REFERENCE_FIELDS):
            yield ContractRef.from_json(value)
        else:
            for item in value.values():
                yield from iter_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_references(item)
