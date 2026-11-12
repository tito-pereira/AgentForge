# SPDX-License-Identifier: MPL-2.0
import subprocess
import sys
import sysconfig
from importlib.metadata import PackageNotFoundError, distribution
from importlib.util import find_spec
from pathlib import Path

import pytest

from corinthos import __version__
from corinthos.contracts import ContractType


@pytest.mark.parametrize("command", [["--help"], ["--version"]])
def test_module_cli_from_another_directory(command, tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "corinthos", *command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "corinthos" in result.stdout
    assert (__version__ if command == ["--version"] else "--help") in result.stdout


def test_module_without_arguments_opens_home(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "corinthos"],
        cwd=tmp_path,
        input="0\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    for label in (
        "CORINTHOS",
        "Create new project",
        "Open existing project",
        "Recent projects",
        "Providers",
        "Settings",
        "Help",
        "0. Exit",
    ):
        assert label in result.stdout


def test_unknown_command_is_rejected(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "corinthos", "run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "run" in result.stderr


def test_installed_entry_point_and_metadata(tmp_path):
    scripts = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if sys.platform == "win32" else ""
    executable = scripts / f"corinthos{suffix}"
    result = subprocess.run(
        [str(executable), "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"corinthos {__version__}"
    installed = distribution("corinthos-core")
    assert installed.metadata["Name"] == "corinthos-core"
    assert installed.version == __version__
    entry_points = installed.entry_points.select(group="console_scripts")
    assert [(entry.name, entry.value) for entry in entry_points] == [
        ("corinthos", "corinthos.cli:main")
    ]
    assert installed.metadata["License-Expression"] == "MPL-2.0"
    assert installed.metadata.get_all("License-File") == ["LICENSE"]
    license_text = (Path(__file__).resolve().parents[1] / "LICENSE").read_text(encoding="utf-8")
    assert installed.read_text("licenses/LICENSE") == license_text
    installed_files = {str(path).replace("\\", "/") for path in installed.files}
    expected_files = {
        "corinthos/__init__.py",
        "corinthos/__main__.py",
        "corinthos/cli.py",
        "corinthos/standard.py",
        "corinthos/contracts/__init__.py",
        "corinthos/contracts/schemas/common.schema.json",
    }
    expected_files.update(
        f"corinthos/contracts/schemas/{kind.value.lower().replace('_', '-')}.schema.json"
        for kind in ContractType
    )
    is_editable = any(path.startswith("__editable__.corinthos_core-") for path in installed_files)
    assert expected_files.issubset(installed_files) or is_editable
    for legacy in ("agentforge", "nukytera"):
        assert not any(legacy in path.lower() for path in installed_files)
        assert find_spec(legacy) is None
        with pytest.raises(PackageNotFoundError):
            distribution(f"{legacy}-core")
        assert not (scripts / f"{legacy}{suffix}").exists()
