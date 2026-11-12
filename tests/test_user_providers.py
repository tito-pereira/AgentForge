# SPDX-License-Identifier: MPL-2.0
"""Verify provider registry precedence, observational data, and safe fallback."""

import os
from argparse import Namespace
from importlib.resources import files

import pytest
import yaml

from corinthos.adapters.discovery import windows_path_executable
from corinthos.adapters.model import Capabilities
from corinthos.bootstrap import adapter_manager, configure_adapter, initialize, show_adapters
from corinthos.cli import main
from corinthos.contracts import ConflictError, ContractStore, IntegrityError
from corinthos.providers import (
    configure_provider,
    configured_executables,
    refresh_providers,
    show_providers,
)
from corinthos.user_state import update_state
from corinthos.workflow.runtime_cli import _runner


@pytest.fixture(autouse=True)
def user_root(tmp_path, monkeypatch):
    path = tmp_path / "user-state"
    monkeypatch.setattr("corinthos.user_state.state_root", lambda: path)
    return path


@pytest.fixture
def native(tmp_path, monkeypatch):
    def discover(manager, provider):
        command = manager._commands.get(provider)
        if command is None:
            return Capabilities(provider, False, discovery="none")
        return Capabilities(
            provider, True, "1.2.3", True, True, executable=command[0], discovery="explicit"
        )

    monkeypatch.setattr("corinthos.adapters.service.AdapterManager.discover", discover)

    def make(name):
        path = tmp_path / f"{name}.exe"
        path.write_bytes(b"Synthetic fixture; do not execute.")
        return path

    return make


def test_provider_refresh_is_generic_and_succeeds_without_any_native_provider(
    tmp_path, monkeypatch, user_root, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert all(row["observed"] is None for row in show_providers())
    assert not user_root.exists()
    future = {"executable": str(tmp_path / "future-native.exe"), "observed": None}
    update_state(
        "providers.json",
        {"version": 1},
        lambda _current: {
            "version": 1,
            "providers": {"future-agent": future},
        },
    )
    assert main(["adapters", "refresh"]) == 0
    rows = {row["provider"]: row for row in show_providers()}
    assert rows["future-agent"] == {"provider": "future-agent", "supported": False, **future}
    for name in ("codex", "claude"):
        assert rows[name]["observed"]["available"] is False
        assert rows[name]["observed"]["discovery"] == "none"
    assert "future-agent" in capsys.readouterr().out
    assert configured_executables() == {}
    assert sorted(item.name for item in tmp_path.iterdir()) == [user_root.name]


def test_registry_observation_never_becomes_an_implicit_executable(tmp_path, monkeypatch):
    candidate = tmp_path / "discovered.exe"
    monkeypatch.setattr(
        "corinthos.adapters.service.AdapterManager.discover",
        lambda _manager, name: Capabilities(
            name, True, "1.2.3", True, True, executable=str(candidate), discovery="path"
        ),
    )
    rows = refresh_providers()
    assert all(row["observed"]["executable"] == str(candidate) for row in rows)
    assert configured_executables() == {}
    assert adapter_manager(tmp_path)._commands == {}


def test_command_precedence_and_explicit_project_reset(tmp_path, user_root, native):
    global_executable = native("global")
    initial = native("initial")
    project_override = native("project")
    one_shot = native("one-shot")
    assert configure_provider("codex", global_executable)["executable"] == str(global_executable)
    configure_provider("claude", global_executable)
    before = (user_root / "providers.json").read_bytes()

    root = tmp_path / "project"
    initialize(root, commands={"codex": [str(initial)]})
    assert show_adapters(root) == [
        {
            "provider": "codex",
            "executable": str(initial),
            "configuration": "initial",
            "selection": "explicit",
        },
        {
            "provider": "claude",
            "executable": str(global_executable),
            "configuration": "global",
            "selection": "explicit",
        },
    ]
    assert adapter_manager(root)._commands["codex"] == (str(initial),)
    configure_adapter(root, "codex", project_override)
    assert adapter_manager(root)._commands["codex"] == (str(project_override),)
    explicit = adapter_manager(root, commands={"codex": [str(one_shot)]})
    assert explicit._commands["codex"] == (str(one_shot),)

    reset = configure_adapter(root, "codex")
    assert reset["configuration"] == "operational" and reset["selection"] == "autodiscovery"
    assert adapter_manager(root)._commands == {"claude": (str(global_executable),)}
    assert (user_root / "providers.json").read_bytes() == before

    other = tmp_path / "other"
    initialize(other)
    assert adapter_manager(other)._commands["codex"] == (str(global_executable),)
    assert configure_provider("codex")["observed"] is None
    assert adapter_manager(other)._commands == {"claude": (str(global_executable),)}


def test_failed_or_concurrent_global_configuration_preserves_current_choice(
    monkeypatch, user_root, native
):
    first = native("first")
    other = native("other")
    configure_provider("codex", first)
    path = user_root / "providers.json"
    original = path.read_bytes()
    with pytest.raises(IntegrityError, match="absolute native executable"):
        configure_provider("codex", "relative.exe")
    monkeypatch.setattr(
        "corinthos.adapters.service.AdapterManager.discover",
        lambda _manager, name: Capabilities(name, True, "1.2.3"),
    )
    with pytest.raises(IntegrityError, match="JSON/stdin"):
        configure_provider("codex", other)
    assert path.read_bytes() == original

    def concurrent_reset(_manager, name):
        if name == "codex":
            configure_provider("codex")
        return Capabilities(name, True, "1.2.3", True, True)

    monkeypatch.setattr("corinthos.adapters.service.AdapterManager.discover", concurrent_reset)
    with pytest.raises(ConflictError, match="changed during discovery"):
        refresh_providers()
    assert configured_executables() == {}
    assert show_providers()[0]["observed"] is None


def test_windows_path_search_ignores_implicit_cwd_and_relative_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "claude.exe").touch()
    (tmp_path / "relative").mkdir()
    (tmp_path / "relative" / "claude.exe").touch()
    assert windows_path_executable(["", ".", "relative"], "claude") is None
    assert windows_path_executable([str(tmp_path)], "claude") == str(tmp_path / "claude.exe")


@pytest.mark.skipif(os.name != "nt", reason="The native Windows suffix is platform-specific.")
def test_windows_global_configuration_cannot_select_wrapper(native):
    wrapper = native("wrapper").with_suffix(".cmd")
    wrapper.write_bytes(b"must not execute")
    with pytest.raises(IntegrityError, match="absolute native executable"):
        configure_provider("codex", wrapper)
    assert configured_executables() == {}


def test_installed_workflow_uses_saved_standard_and_global_choice_outside_checkout(
    tmp_path, monkeypatch, native
):
    monkeypatch.chdir(tmp_path)
    default = native("global")
    override = native("override")
    configure_provider("codex", default)
    root = tmp_path / "project"
    standard = yaml.safe_load(
        files("corinthos.resources").joinpath("standard.yaml").read_text(encoding="utf-8")
    )
    standard["commandments"]["M1"]["description"] = "Owner's saved Standard wording."
    policy = tmp_path / "saved-policy.yaml"
    policy.write_text(yaml.safe_dump(standard), encoding="utf-8")
    bootstrap = initialize(root, policy_path=policy)
    store = ContractStore(root)
    arguments = Namespace(
        root=root,
        provider="codex",
        provider_executable=None,
        provider_arg=[],
        policy=None,
        policy_schema=None,
    )
    adapters = _runner(arguments, store).adapters
    assert adapters.standard_sha256 == bootstrap["standard_sha256"]
    assert adapters._commands == {"codex": (str(default),)}
    arguments.provider_executable = override
    arguments.provider_arg = ["--prefix"]
    assert _runner(arguments, store).adapters._commands == {"codex": (str(override), "--prefix")}

    arguments.policy = tmp_path / "missing-policy.json"
    with pytest.raises(IntegrityError, match="Select existing Standard"):
        _runner(arguments, store)
