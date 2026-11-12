# SPDX-License-Identifier: MPL-2.0
"""Per-user provider choices and advisory observations, independent of projects."""

import os
import re
from dataclasses import asdict
from importlib.resources import as_file, files
from pathlib import Path

from corinthos.adapters.discovery import ordinary_windows_executable
from corinthos.adapters.providers import PROVIDERS
from corinthos.adapters.service import AdapterManager
from corinthos.contracts import ConflictError, IntegrityError
from corinthos.user_state import read_state, update_state

SUPPORTED_PROVIDERS = tuple(PROVIDERS)
_FILE = "providers.json"
_DEFAULT = {"version": 1, "providers": {}}
_ID = re.compile(r"[a-z][a-z0-9-]{0,31}")
_FLAGS = {"available", "json_events", "stdin_prompt", "native_resume", "read_only"}
_TEXTS = {"version", "reason", "executable", "discovery"}
_OBSERVATION_LIMIT = 4096


def _executable(value):
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= _OBSERVATION_LIMIT
        or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise IntegrityError("Choose an absolute native executable.")
    path = Path(value)
    if not path.is_absolute() or (os.name == "nt" and path.suffix.lower() != ".exe"):
        raise IntegrityError("Choose an absolute native executable.")
    return path


def _registry(value):
    entries = value.get("providers")
    if (
        value.keys() != {"version", "providers"}
        or not isinstance(entries, dict)
        or len(entries) > 32
    ):
        raise IntegrityError("The saved provider registry has an unsupported shape.")
    for provider, entry in entries.items():
        if (
            _ID.fullmatch(provider) is None
            or not isinstance(entry, dict)
            or entry.keys() != {"executable", "observed"}
        ):
            raise IntegrityError("The saved provider registry has an invalid entry.")
        if entry["executable"] is not None:
            _executable(entry["executable"])
        observed = entry["observed"]
        if observed is not None and (
            not isinstance(observed, dict)
            or observed.keys() != _FLAGS | _TEXTS
            or any(type(observed[key]) is not bool for key in _FLAGS)
            or any(
                observed[key] is not None
                and not (
                    isinstance(observed[key], str) and len(observed[key]) <= _OBSERVATION_LIMIT
                )
                for key in _TEXTS
            )
        ):
            raise IntegrityError("The saved provider observation is invalid.")
    return entries


def _read():
    return _registry(read_state(_FILE, _DEFAULT))


def _configured(entries, provider):
    return entries.get(provider, {}).get("executable")


def _manager(commands):
    resources = files("corinthos.resources")
    with (
        as_file(resources.joinpath("standard.yaml")) as policy,
        as_file(resources.joinpath("standard.schema.json")) as schema,
    ):
        return AdapterManager(policy, schema, commands=commands)


def _observation(capabilities):
    values = asdict(capabilities)
    return {
        **{key: values[key] for key in _FLAGS},
        **{key: (values[key] or "")[:_OBSERVATION_LIMIT] or None for key in _TEXTS},
    }


def _row(entries, provider):
    return {
        "provider": provider,
        "supported": provider in SUPPORTED_PROVIDERS,
        "executable": _configured(entries, provider),
        "observed": entries.get(provider, {}).get("observed"),
    }


def _rows(entries):
    names = (*SUPPORTED_PROVIDERS, *sorted(entries.keys() - set(SUPPORTED_PROVIDERS)))
    return [_row(entries, provider) for provider in names]


def configured_executables():
    """Read explicit supported choices only, never use cached detection as a command."""
    return {
        provider: entry["executable"]
        for provider, entry in _read().items()
        if provider in SUPPORTED_PROVIDERS and entry["executable"] is not None
    }


def show_providers():
    """Inspect saved choices and last observations without native work or writes."""
    return _rows(_read())


def _save(entries, expected):
    def transform(current):
        saved = _registry(current)
        if any(_configured(saved, name) != _configured(expected, name) for name in entries):
            raise ConflictError("A provider choice changed during discovery. Reload and retry.")
        result = {"version": 1, "providers": {**saved, **entries}}
        _registry(result)
        return result

    return _registry(update_state(_FILE, _DEFAULT, transform))


def refresh_providers():
    """Refresh bounded native version/help observations; missing providers are normal."""
    previous = _read()
    commands = {
        provider: [executable]
        for provider in SUPPORTED_PROVIDERS
        if (executable := _configured(previous, provider)) is not None
    }
    manager = _manager(commands)
    entries = {
        provider: {
            "executable": _configured(previous, provider),
            "observed": _observation(manager.discover(provider)),
        }
        for provider in SUPPORTED_PROVIDERS
    }
    return _rows(_save(entries, previous))


def configure_provider(provider, executable=None):
    """Set an explicit native executable after checking it, or reset to discovery."""
    if provider not in SUPPORTED_PROVIDERS:
        raise IntegrityError("Select a supported native provider.")
    previous = _read()
    observed = None
    if executable is not None:
        path = _executable(str(executable))
        if not (ordinary_windows_executable(path) if os.name == "nt" else path.is_file()):
            raise IntegrityError("Choose an existing native executable.")
        executable = str(path)
        capabilities = _manager({provider: [executable]}).discover(provider)
        if not (capabilities.available and capabilities.json_events and capabilities.stdin_prompt):
            raise IntegrityError(
                "The native executable did not verify the required JSON/stdin interface."
            )
        observed = _observation(capabilities)
    entries = _save({provider: {"executable": executable, "observed": observed}}, previous)
    return _row(entries, provider)
