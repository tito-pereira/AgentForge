"""Safe loading and structural validation of the Phase 0 Standard."""

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


def load_standard(policy_path: str | Path, schema_path: str | Path) -> dict:
    """Validate the supplied files and propagate I/O, syntax, and schema errors."""
    with Path(policy_path).open(encoding="utf-8") as policy_file:
        policy = yaml.safe_load(policy_file)
    with Path(schema_path).open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(policy)
    return policy
