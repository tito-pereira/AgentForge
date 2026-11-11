# SPDX-License-Identifier: MPL-2.0
"""Synthetic npm layouts exercise discovery without executing command wrappers."""

import json
from pathlib import Path

import pytest

from corinthos.adapters import AdapterManager
from corinthos.adapters.discovery import windows_codex_command
from corinthos.adapters.model import AgentResult

ROOT = Path(__file__).resolve().parents[1]


def npm(prefix, *, arch="x64", shim="codex.cmd", legacy=False):
    package = prefix / "node_modules/@openai/codex"
    (package / "bin").mkdir(parents=True)
    (package / "bin/codex.js").write_text("// Synthetic npm entry point; never executed.")
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "@openai/codex",
                "version": "0.167.0",
                "bin": {"codex": "bin/codex.js"},
                "optionalDependencies": {
                    "@openai/codex-win32-" + arch: "npm:@openai/codex@0.167.0-win32-" + arch
                },
            }
        )
    )
    target = package if legacy else package / ("node_modules/@openai/codex-win32-" + arch)
    triple = "x86_64-pc-windows-msvc" if arch == "x64" else "aarch64-pc-windows-msvc"
    binary = target / "vendor" / triple / "bin/codex.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"Synthetic executable; probes are mocked.")
    if not legacy:
        (target / "package.json").write_text(
            json.dumps(
                {
                    "name": "@openai/codex",
                    "version": "0.167.0-win32-" + arch,
                    "os": ["win32"],
                    "cpu": [arch],
                }
            )
        )
    (prefix / shim).write_text("%dp0%/node_modules/@openai/codex/bin/codex.js")
    return package, binary


@pytest.mark.parametrize("shim", ["codex.cmd", "codex.ps1", "codex"])
@pytest.mark.parametrize("arch,machine", [("x64", "AMD64"), ("arm64", "ARM64")])
def test_resolves_only_known_platform_layout_from_npm_shim(tmp_path, arch, machine, shim):
    _, binary = npm(tmp_path / "npm", arch=arch, shim=shim)
    assert windows_codex_command([str(tmp_path)], machine)[0] is None
    assert windows_codex_command([str(tmp_path / "npm")], machine) == (
        (str(binary),),
        "npm",
        "0.167.0",
        None,
    )


def test_legacy_vendor_and_duplicate_path_entries(tmp_path):
    _, binary = npm(tmp_path / "npm", legacy=True)
    result = windows_codex_command([str(tmp_path / "npm")] * 2, "AMD64")
    assert result == ((str(binary),), "npm", "0.167.0", None)


def test_resolves_platform_dependency_hoisted_to_global_node_modules(tmp_path):
    prefix = tmp_path / "npm"
    _, binary = npm(prefix)
    nested = binary.parents[3]
    hoisted = prefix / "node_modules/@openai/codex-win32-x64"
    nested.rename(hoisted)
    expected = hoisted / binary.relative_to(nested)
    assert windows_codex_command([str(prefix)], "AMD64") == (
        (str(expected),),
        "npm",
        "0.167.0",
        None,
    )


@pytest.mark.parametrize(
    "broken", ["missing", "wrong-name", "wrong-bin", "wrong-platform", "large"]
)
def test_unresolved_or_untrusted_layout_never_becomes_native_command(tmp_path, broken):
    package, binary = npm(tmp_path / "npm")
    if broken == "missing":
        binary.unlink()
    elif broken == "wrong-platform":
        native_metadata = binary.parents[3] / "package.json"
        value = json.loads(native_metadata.read_text())
        value["cpu"] = ["arm64"]
        native_metadata.write_text(json.dumps(value))
    else:
        path = package / "package.json"
        value = json.loads(path.read_text())
        if broken == "wrong-name":
            value["name"] = "untrusted"
        elif broken == "wrong-bin":
            value["bin"]["codex"] = "../../outside.js"
        path.write_text(" " * 65_537 if broken == "large" else json.dumps(value))
    command, source, _, reason = windows_codex_command([str(tmp_path / "npm")], "AMD64")
    assert command is None and source == "npm-unresolved" and "shim" in reason


def test_ambiguity_requires_explicit_choice_and_does_not_probe(tmp_path):
    npm(tmp_path / "one")
    npm(tmp_path / "two")
    command, source, _, reason = windows_codex_command(
        [str(tmp_path / "one"), str(tmp_path / "two")], "AMD64"
    )
    assert command is None and source == "ambiguous" and "Multiple" in reason


def test_arbitrary_wrappers_or_unrelated_disk_executable_are_not_searched(tmp_path):
    prefix = tmp_path / "path"
    prefix.mkdir()
    (prefix / "codex.cmd").write_text("@echo arbitrary wrapper")
    other = tmp_path / "unrelated/codex.exe"
    other.parent.mkdir()
    other.write_bytes(b"Never inspect this outside PATH/package candidate roots.")
    assert windows_codex_command([str(prefix)], "AMD64")[0] is None
    assert windows_codex_command([], "AMD64")[1] == "none"
    assert "does not prove" in windows_codex_command([], "AMD64")[3]


def test_redirected_native_is_not_accepted(tmp_path):
    prefix = tmp_path / "npm"
    _, binary = npm(prefix)
    outside = tmp_path / "outside.exe"
    outside.write_bytes(binary.read_bytes())
    binary.unlink()
    try:
        binary.symlink_to(outside)
    except OSError:
        pytest.skip("Symbolic links unavailable to this account.")
    assert windows_codex_command([str(prefix)], "AMD64")[0] is None


def manager(monkeypatch, prefix, *, reported="codex-cli 0.167.0", supported=True):
    value = AdapterManager(ROOT / "policies/standard.yaml", ROOT / "schemas/standard.schema.json")
    monkeypatch.setattr(
        value, "_selection", lambda provider: windows_codex_command([str(prefix)], "AMD64")
    )
    seen = []

    def help_command(command, args):
        assert Path(command[0]).suffix == ".exe"
        seen.append((command, args))
        if args == ("--version",):
            return reported
        if not supported:
            return "unsupported interface"
        return "--json stdin --sandbox read-only SESSION_ID"

    monkeypatch.setattr(value, "_help", help_command)
    return value, seen


def test_npm_binary_identifies_matching_codex_and_required_interfaces(tmp_path, monkeypatch):
    _, binary = npm(tmp_path / "npm")
    value, seen = manager(monkeypatch, tmp_path / "npm")
    result = value.discover("codex")
    assert result.available and result.version == "0.167.0"
    assert result.executable == str(binary) and result.discovery == "npm"
    assert result.json_events and result.stdin_prompt and result.native_resume and result.read_only
    assert len(seen) == 4 and all(command == (str(binary),) for command, _ in seen)


@pytest.mark.parametrize("reported", ["Python 3.12.10", "codex-cli 9.9.9", "unrelated 0.167.0"])
def test_npm_package_identity_must_match_native_version(tmp_path, monkeypatch, reported):
    npm(tmp_path / "npm")
    value, _ = manager(monkeypatch, tmp_path / "npm", reported=reported)
    result = value.discover("codex")
    assert not result.available and "declared Codex CLI version" in result.reason


def test_npm_unsupported_and_ambiguous_results_are_unavailable(tmp_path, monkeypatch):
    npm(tmp_path / "npm")
    value, _ = manager(monkeypatch, tmp_path / "npm", supported=False)
    assert not value.discover("codex").available
    assert "unsupported" in value.discover("codex").reason
    value, seen = manager(monkeypatch, tmp_path / "absent")
    assert not value.discover("codex").available and not seen


def test_invocation_uses_the_same_native_command_that_was_probed(tmp_path, monkeypatch):
    _, binary = npm(tmp_path / "npm")
    value, _ = manager(monkeypatch, tmp_path / "npm")
    selections = []
    selection = value._selection

    def select(provider):
        selections.append(provider)
        assert len(selections) == 1
        return selection(provider)

    monkeypatch.setattr(value, "_selection", select)

    def run(implementation, prefix, prompt, workspace, **kwargs):
        assert prefix == (str(binary),) and workspace == tmp_path
        return AgentResult("codex", "COMPLETED", kwargs["task_id"], kwargs["attempt_id"])

    monkeypatch.setattr("corinthos.adapters.service.run_process", run)
    assert value.probe("codex", tmp_path, "Synthetic read-only diagnostic.").status == "COMPLETED"
