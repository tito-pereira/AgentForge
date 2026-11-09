# SPDX-License-Identifier: MPL-2.0
"""Load and validate the packaged contract wire format offline."""

import json
import re
from copy import deepcopy
from datetime import datetime
from functools import cache
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError as InvalidSchema
from referencing import Registry, Resource

from .model import ContractRef, ContractType, SchemaError, canonical_json

SCHEMA_VERSION = "1.0"
_FORMATS = FormatChecker()
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


@_FORMATS.checks("date-time")
def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not _TIMESTAMP.fullmatch(value):
        return False
    if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _schema_name(contract_type: ContractType) -> str:
    return contract_type.value.lower().replace("_", "-")


@cache
def _validators() -> dict[ContractType, Draft202012Validator]:
    directory = files("nukytera.contracts").joinpath("schemas")
    names = ["common", *map(_schema_name, ContractType)]
    schemas = {}
    try:
        for name in names:
            schema = json.loads(directory.joinpath(f"{name}.schema.json").read_text("utf-8"))
            Draft202012Validator.check_schema(schema)
            if schema["$id"] != f"urn:nukytera:contracts:{SCHEMA_VERSION}:{name}":
                raise SchemaError("Packaged schema identity does not match its file.")
            schemas[name] = schema
    except (OSError, ValueError, KeyError, InvalidSchema) as exc:
        raise SchemaError("Packaged contract schemas could not be loaded.") from exc
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return {
        kind: Draft202012Validator(
            schemas[_schema_name(kind)], registry=registry, format_checker=_FORMATS
        )
        for kind in ContractType
    }


def _validator(contract_type: ContractType | str, schema_version: str) -> Draft202012Validator:
    if schema_version != SCHEMA_VERSION:
        raise SchemaError("Unsupported contract schema version.")
    try:
        kind = ContractType(contract_type)
    except (ValueError, TypeError):
        raise SchemaError("Unknown contract type.") from None
    return _validators()[kind]


def load_schema(contract_type: ContractType | str, schema_version: str = SCHEMA_VERSION) -> dict:
    """Return a detached schema for the requested type and wire version."""
    return deepcopy(_validator(contract_type, schema_version).schema)


def validate_schema(document: dict) -> None:
    """Check JSON shape without resolving references or authorizing publication."""
    canonical_json(document)
    ref = ContractRef.from_document(document)
    validator = _validator(ref.contract_type, document["metadata"].get("schema_version"))
    error = next(validator.iter_errors(document), None)
    if error is not None:
        rule = "/".join(map(str, error.absolute_schema_path))
        raise SchemaError(f"{ref.contract_type} schema rejected the document at {rule}.")
