# SPDX-License-Identifier: MPL-2.0
"""Operational adapter choices preserve initialized project authority and bytes."""

import json
import os
from argparse import Namespace
from pathlib import Path

import pytest

from corinthos.adapters.model import Capabilities
from corinthos.bootstrap import adapter_manager, configure_adapter, initialize, show_adapters
from corinthos.cli import main
from corinthos.contracts import ConflictError, ContractError, ContractStore, IntegrityError
from corinthos.contracts.model import canonical_json


@pytest.fixture(autouse=True)
def isolated_provider_registry(tmp_path, monkeypatch):
    monkeypatch.setattr("corinthos.user_state.state_root", lambda: tmp_path / "user-state")


@pytest.fixture
def native(tmp_path):
    path = tmp_path / "synthetic-native.exe"
    path.write_bytes(b"synthetic executable; never execute this fixture")
    path.chmod(0o700)
    return path


@pytest.fixture
def probes(monkeypatch):
    observed = []

    def discover(self, provider):
        observed.append((provider, dict(self._commands)))
        return Capabilities(provider, True, "1.0.0", True, True, True, True)

    monkeypatch.setattr("corinthos.adapters.service.AdapterManager.discover", discover)
    return observed


def _preserved(root):
    paths = [".corinthos/bootstrap.json", "AGENTS.md", "CLAUDE.md"]
    if (root / ".corinthos/state.db").exists():
        paths.append(".corinthos/state.db")
    return {name: (root / name).read_bytes() for name in paths}


def test_configure_after_initialization_persists_on_restart_and_preserves_project_bytes(
    tmp_path, native, probes
):
    root = tmp_path / "project"
    initialize(root)
    before = _preserved(root)
    result = configure_adapter(root, "codex", native)
    assert result == {
        "provider": "codex",
        "executable": str(native),
        "configuration": "operational",
        "selection": "explicit",
    }
    assert probes == [("codex", {"codex": (str(native),)})]
    assert adapter_manager(root)._commands == {"codex": (str(native),)}
    assert show_adapters(root, provider="codex") == [result]
    assert _preserved(root) == before
    assert not (root / ".corinthos/state.db").exists()
    assert json.loads((root / ".corinthos/adapter-codex.json").read_bytes()) == {
        "version": 1,
        "provider": "codex",
        "executable": str(native),
    }


def test_configure_replaces_only_one_provider_and_reset_overrides_old_initial_choice(
    tmp_path, native, probes
):
    root = tmp_path / "project"
    initial = tmp_path / "initial-native.exe"
    initial.write_bytes(b"initial fixture")
    initialize(root, commands={"codex": [str(initial)], "claude": [str(native)]})
    (root / ".corinthos/state.db").write_bytes(b"existing private state; preserve exactly")
    before = _preserved(root)
    assert show_adapters(root, provider="codex")[0]["executable"] == str(initial)
    configure_adapter(root, "claude", native)
    claude_before = (root / ".corinthos/adapter-claude.json").read_bytes()
    configure_adapter(root, "codex", native)
    assert adapter_manager(root)._commands == {
        "codex": (str(native),),
        "claude": (str(native),),
    }
    count = len(probes)
    reset = configure_adapter(root, "codex")
    assert len(probes) == count
    assert reset["executable"] is None and reset["selection"] == "autodiscovery"
    assert adapter_manager(root)._commands == {"claude": (str(native),)}
    assert json.loads((root / ".corinthos/adapter-codex.json").read_bytes())["executable"] is None
    assert (root / ".corinthos/adapter-claude.json").read_bytes() == claude_before
    assert _preserved(root) == before


@pytest.mark.parametrize("kind", ["relative", "missing", "directory", "shim"])
def test_invalid_native_path_preserves_previous_choice(tmp_path, native, probes, kind):
    root = tmp_path / "project"
    initialize(root)
    configure_adapter(root, "codex", native)
    sidecar = root / ".corinthos/adapter-codex.json"
    before = sidecar.read_bytes()
    choices = {
        "relative": "relative-native.exe",
        "missing": tmp_path / "missing.exe",
        "directory": tmp_path,
        "shim": tmp_path / "codex.cmd",
    }
    if kind == "shim":
        choices[kind].write_bytes(b"must not execute this shim")
        if os.name != "nt":
            pytest.skip("The configured native .exe requirement is Windows-specific.")
    with pytest.raises(IntegrityError):
        configure_adapter(root, "codex", choices[kind])
    assert len(probes) == 1
    assert sidecar.read_bytes() == before
    assert adapter_manager(root)._commands["codex"] == (str(native),)


@pytest.mark.parametrize(
    "available,json_events,stdin_prompt",
    [(False, True, True), (True, False, True), (True, True, False)],
)
def test_failed_or_unsupported_probe_preserves_previous_choice(
    tmp_path, native, probes, monkeypatch, available, json_events, stdin_prompt
):
    root = tmp_path / "project"
    initialize(root)
    configure_adapter(root, "codex", native)
    sidecar = root / ".corinthos/adapter-codex.json"
    before = sidecar.read_bytes()
    monkeypatch.setattr(
        "corinthos.adapters.service.AdapterManager.discover",
        lambda self, provider: Capabilities(
            provider, available, "1.0.0", json_events, stdin_prompt
        ),
    )
    with pytest.raises(IntegrityError, match="JSON/stdin"):
        configure_adapter(root, "codex", native)
    assert sidecar.read_bytes() == before


def test_one_off_explicit_command_overrides_sidecar_without_rewriting_it(tmp_path, native, probes):
    root = tmp_path / "project"
    initialize(root)
    configure_adapter(root, "codex", native)
    sidecar = root / ".corinthos/adapter-codex.json"
    before = sidecar.read_bytes()
    other = tmp_path / "one-off.exe"
    other.write_bytes(b"one-off fixture")
    assert adapter_manager(root, commands={"codex": [str(other)]})._commands == {
        "codex": (str(other),)
    }
    assert sidecar.read_bytes() == before
    assert adapter_manager(root)._commands["codex"] == (str(native),)
    with pytest.raises(ConflictError, match="Initialization conflicts"):
        initialize(root, commands={"codex": [str(other)]})


def test_failed_atomic_replace_preserves_configuration_and_removes_temporary_file(
    tmp_path, native, probes, monkeypatch
):
    root = tmp_path / "project"
    initialize(root)
    configure_adapter(root, "codex", native)
    sidecar = root / ".corinthos/adapter-codex.json"
    before = sidecar.read_bytes()

    def failed_replace(*args):
        raise PermissionError("Synthetic publication failure")

    monkeypatch.setattr("corinthos.bootstrap.os.replace", failed_replace)
    with pytest.raises(PermissionError, match="Synthetic"):
        configure_adapter(root, "codex")
    assert sidecar.read_bytes() == before
    assert list(sidecar.parent.glob(".adapter-codex-*")) == []


def test_configuration_checks_required_interfaces_without_claiming_optional_support(
    tmp_path, native, monkeypatch
):
    root = tmp_path / "project"
    initialize(root)
    monkeypatch.setattr(
        "corinthos.adapters.service.AdapterManager.discover",
        lambda self, provider: Capabilities(provider, True, "1.0.0", True, True),
    )
    assert configure_adapter(root, "codex", native)["executable"] == str(native)


@pytest.mark.parametrize("action", ["show", "configure", "reset", "manager"])
@pytest.mark.parametrize("unsafe", ["corrupt", "hardlink", "oversized", "directory"])
def test_unsafe_sidecar_is_never_ignored_or_overwritten(tmp_path, native, probes, action, unsafe):
    root = tmp_path / "project"
    initialize(root)
    sidecar = root / ".corinthos/adapter-codex.json"
    owner = tmp_path / "owner-data.json"
    owner.write_bytes(b"preserve owner data")
    if unsafe == "hardlink":
        os.link(owner, sidecar)
    elif unsafe == "directory":
        sidecar.mkdir()
    else:
        sidecar.write_bytes(b"invalid" if unsafe == "corrupt" else b"x" * (128 * 1024 + 1))
    before = None if sidecar.is_dir() else sidecar.read_bytes()
    operations = {
        "show": lambda: show_adapters(root, provider="codex"),
        "configure": lambda: configure_adapter(root, "codex", native),
        "reset": lambda: configure_adapter(root, "codex"),
        "manager": lambda: adapter_manager(root),
    }
    with pytest.raises(IntegrityError):
        operations[action]()
    assert probes == []
    assert owner.read_bytes() == b"preserve owner data"
    assert sidecar.is_dir() if before is None else sidecar.read_bytes() == before


def test_cli_configure_show_and_reset_have_separate_probe_behavior(
    tmp_path, native, probes, capsys
):
    root = tmp_path / "project"
    initialize(root)
    args = ["--root", str(root)]
    assert main(["adapters", "configure", "codex", *args, "--executable", str(native)]) == 0
    assert len(probes) == 1
    assert main(["adapters", "show", *args, "--provider", "codex"]) == 0
    assert len(probes) == 1
    assert str(native) in capsys.readouterr().out
    assert main(["adapters", "reset", "codex", *args]) == 0
    assert len(probes) == 1
    assert "autodiscovery" in capsys.readouterr().out
    assert main(["adapters", "capabilities", *args, "--provider", "codex"]) == 0
    assert len(probes) == 2


def test_configuration_requires_initialization_and_preserves_standard_validation(
    tmp_path, native, probes
):
    root = tmp_path / "uninitialized"
    root.mkdir()
    with pytest.raises(ContractError):
        configure_adapter(root, "codex", native)
    assert list(root.iterdir()) == []
    private = tmp_path / ".corinthos"
    private.mkdir()
    with pytest.raises(IntegrityError, match="Initialize"):
        configure_adapter(tmp_path, "codex", native)
    assert list(private.iterdir()) == []
    initialize(tmp_path)
    before = _preserved(tmp_path)
    standard = json.loads(before[".corinthos/bootstrap.json"])["standard"]
    standard["commandments"]["M1"]["description"] = "Different Standard instructions."
    policy = tmp_path / "different.json"
    policy.write_text(canonical_json(standard), encoding="utf-8")
    with pytest.raises(ConflictError, match="Standard settings conflict"):
        adapter_manager(tmp_path, policy_path=policy, commands={"codex": [str(native)]})
    assert _preserved(tmp_path) == before
    assert probes == []


def test_workflow_cli_consumes_saved_choices_and_retains_explicit_prefix_override(
    tmp_path, native, probes
):
    from corinthos.workflow.runtime_cli import _runner

    initialize(tmp_path)
    configure_adapter(tmp_path, "codex", native)
    configure_adapter(tmp_path, "claude", native)
    source = Path(__file__).resolve().parents[1]
    arguments = Namespace(
        root=tmp_path,
        provider="codex",
        provider_executable=None,
        provider_arg=[],
        policy=source / "policies/standard.yaml",
        policy_schema=source / "schemas/standard.schema.json",
    )
    store = ContractStore(tmp_path)
    assert _runner(arguments, store).adapters._commands == {
        "codex": (str(native),),
        "claude": (str(native),),
    }
    alternative = tmp_path / "other-native.exe"
    alternative.write_bytes(b"Synthetic host; no invocation in this test.")
    arguments.provider_executable = alternative
    arguments.provider_arg = ["--synthetic-argument"]
    assert _runner(arguments, store).adapters._commands == {
        "codex": (str(alternative), "--synthetic-argument"),
        "claude": (str(native),),
    }
    configure_adapter(tmp_path, "codex")
    arguments.provider_executable = None
    arguments.provider_arg = []
    assert _runner(arguments, store).adapters._commands == {"claude": (str(native),)}
    assert len(probes) == 2
