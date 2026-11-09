# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import SchemaError, ValidationError

from agentforge.standard import load_standard

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policies" / "standard.yaml"
SCHEMA = ROOT / "schemas" / "standard.schema.json"
MANDATES = ["M1", "M2", "M3", "M4", "M5"]


@pytest.fixture
def policy():
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def test_repository_standard():
    policy = load_standard(POLICY, SCHEMA)
    assert policy["standard_version"] == "0.1"
    assert set(policy["commandments"]) == set(MANDATES)
    assert all(item["required"] is True for item in policy["commandments"].values())


@pytest.mark.parametrize("mandate", MANDATES)
@pytest.mark.parametrize("change", ["remove", "disable", "omit_flag"])
def test_missing_or_disabled_mandate_is_rejected(policy, mandate, change, tmp_path):
    if change == "remove":
        del policy["commandments"][mandate]
    elif change == "disable":
        policy["commandments"][mandate]["required"] = False
    else:
        del policy["commandments"][mandate]["required"]
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_standard(path, SCHEMA)


@pytest.mark.parametrize("value", [None, [], {}, {"standard_version": "other"}])
def test_invalid_structure_is_rejected(value, tmp_path):
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(value), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_standard(path, SCHEMA)


@pytest.mark.parametrize("value", ["true", 1, None])
def test_required_must_be_a_boolean(policy, value, tmp_path):
    policy["commandments"]["M1"]["required"] = value
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_standard(path, SCHEMA)


def test_extra_commandment_is_rejected(policy, tmp_path):
    policy["commandments"]["M6"] = {"required": True, "description": "Extra"}
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_standard(path, SCHEMA)


def test_blank_description_is_rejected(policy, tmp_path):
    policy["commandments"]["M1"]["description"] = "  "
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_standard(path, SCHEMA)


@pytest.mark.parametrize("content", ["[broken", "!!python/object:builtins.object {}"])
def test_malformed_or_unsafe_yaml_is_rejected(content, tmp_path):
    path = tmp_path / "invalid.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_standard(path, SCHEMA)


def test_invalid_schema_is_rejected(tmp_path):
    path = tmp_path / "invalid.schema.json"
    path.write_text(json.dumps({"type": "invalid"}), encoding="utf-8")
    with pytest.raises(SchemaError):
        load_standard(POLICY, path)
