# SPDX-License-Identifier: MPL-2.0
"""Resolve Windows PATH entries without executing npm command wrappers."""

import json
import os
import stat
from pathlib import Path

from corinthos.contracts.artifacts import is_link

_LIMIT = 65_536
_TARGETS = {
    "amd64": ("x64", "x86_64-pc-windows-msvc"),
    "x86_64": ("x64", "x86_64-pc-windows-msvc"),
    "arm64": ("arm64", "aarch64-pc-windows-msvc"),
    "aarch64": ("arm64", "aarch64-pc-windows-msvc"),
}


def _ordinary(path):
    info = path.lstat()
    if is_link(info) or not stat.S_ISREG(info.st_mode) or path.resolve(strict=True) != path:
        raise ValueError("Executable/package paths must not redirect.")
    return info


def _read(path):
    info = _ordinary(path)
    if info.st_size > _LIMIT:
        raise ValueError("Package metadata or shim exceeds the discovery bound.")
    with path.open("rb") as stream:
        if not os.path.samestat(info, os.fstat(stream.fileno())):
            raise ValueError("The discovery input changed while opening it.")
        value = stream.read(_LIMIT + 1)
    if len(value) > _LIMIT:
        raise ValueError("Discovery input grew beyond its bound.")
    return value


def _npm_candidates(directory, machine):
    architecture, triple = _TARGETS[machine.lower()]
    package = directory / "node_modules/@openai/codex"
    metadata = json.loads(_read(package / "package.json"))
    if metadata.get("name") != "@openai/codex" or metadata.get("bin") != {"codex": "bin/codex.js"}:
        raise ValueError("The shim does not identify the expected npm package.")
    _ordinary(package / "bin/codex.js")
    version = metadata.get("version")
    if not isinstance(version, str) or not version or len(version) > 128:
        raise ValueError("The npm package has no bounded version identity.")
    name = "codex-win32-" + architecture
    declaration = metadata.get("optionalDependencies", {}).get("@openai/" + name)
    for platform in (
        package / "node_modules/@openai" / name,
        directory / "node_modules/@openai" / name,
    ):
        try:
            value = json.loads(_read(platform / "package.json"))
            if (
                declaration != "npm:@openai/codex@" + version + "-win32-" + architecture
                or value.get("name") != "@openai/codex"
                or value.get("version") != version + "-win32-" + architecture
                or value.get("os") != ["win32"]
                or value.get("cpu") != [architecture]
            ):
                continue
            binary = platform / "vendor" / triple / "bin/codex.exe"
            _ordinary(binary)
            yield binary, version
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            continue
    # The npm entry point also supports its older in-package vendor layout.
    binary = package / "vendor" / triple / "bin/codex.exe"
    try:
        _ordinary(binary)
    except (OSError, ValueError):
        return
    yield binary, version


def windows_codex_command(path_entries, machine):
    """Return one native command, source, npm version and diagnostic from PATH roots."""
    if len(path_entries) > 256:
        return None, "none", None, "PATH has too many entries; configure an explicit executable."
    candidates, saw_shim = {}, False
    for entry in path_entries:
        directory = Path(entry.strip('"'))
        if not directory.is_absolute():
            continue
        native = directory / "codex.exe"
        try:
            _ordinary(native)
            candidates.setdefault(native, ("path", None))
        except (OSError, ValueError):
            pass
        recognized = False
        for name in ("codex.cmd", "codex.ps1", "codex"):
            shim = directory / name
            try:
                content = _read(shim).decode("utf-8-sig").replace("\\", "/")
                saw_shim = True
                recognized |= "node_modules/@openai/codex/bin/codex.js" in content and any(
                    marker in content for marker in ("%dp0%", "$basedir", "basedir=")
                )
            except (OSError, ValueError, UnicodeError):
                continue
        if not recognized or machine.lower() not in _TARGETS:
            continue
        try:
            for binary, version in _npm_candidates(directory, machine):
                previous = candidates.get(binary)
                if previous and previous[1] not in (None, version):
                    return (
                        None,
                        "ambiguous",
                        None,
                        "Conflicting npm identities; configure an explicit executable.",
                    )
                candidates[binary] = ("npm", version)
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            continue
    if len(candidates) > 1:
        return (
            None,
            "ambiguous",
            None,
            "Multiple Codex native executables were found; configure an explicit executable.",
        )
    if candidates:
        binary, (source, version) = next(iter(candidates.items()))
        return (str(binary),), source, version, None
    if saw_shim:
        return (
            None,
            "npm-unresolved",
            None,
            "A Codex command shim was found, but its npm native binary could not be resolved safely. Configure an explicit native executable.",
        )
    return (
        None,
        "none",
        None,
        "No native executable was discovered in PATH. This does not prove Codex is not installed; configure its explicit native path.",
    )
