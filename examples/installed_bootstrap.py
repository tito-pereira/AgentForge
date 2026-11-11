# SPDX-License-Identifier: MPL-2.0
"""Verify installed resources and terminal journeys outside the source checkout."""

import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import corinthos
import corinthos.lifecycle.builds
import corinthos.lifecycle.playtest
import corinthos.lifecycle.versions
import corinthos.project_manager.product_review
from corinthos.bootstrap import adapter_manager

for module in (
    corinthos,
    corinthos.lifecycle.builds,
    corinthos.lifecycle.playtest,
    corinthos.lifecycle.versions,
    corinthos.project_manager.product_review,
):
    assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert files("corinthos.resources").joinpath("standard.yaml").is_file()
assert files("corinthos.resources").joinpath("standard.schema.json").is_file()

with TemporaryDirectory(prefix="corinthos-installed-check-") as directory:
    root = Path(directory)
    original = b"Owner's existing project instructions.\n"
    (root / "AGENTS.md").write_bytes(original)
    commands = (
        ("init", "."),
        ("init", "."),
        ("project", "advise", "--help"),
        ("project", "product-review", "--help"),
        ("build", "--help"),
        ("version", "--help"),
        ("playtest", "--help"),
    )
    for command in commands:
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-m", "corinthos", *command],
            cwd=root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, (command, result.stdout, result.stderr)
    assert (root / "AGENTS.md").read_bytes().startswith(original)
    assert (root / "CLAUDE.md").is_file()
    manager = adapter_manager(root)
    assert set(manager._standard["commandments"]) == {"M1", "M2", "M3", "M4", "M5"}
    assert all(item["required"] is True for item in manager._standard["commandments"].values())
    assert not (root / ".corinthos/state.db").exists()
print(
    "Installed resources, repeated init, preserved instructions and lifecycle help passed outside checkout."
)
