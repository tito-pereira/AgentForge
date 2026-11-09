# SPDX-License-Identifier: MPL-2.0
import subprocess
import sys
import sysconfig
from importlib.metadata import PackageNotFoundError, distribution
from importlib.util import find_spec
from pathlib import Path

import pytest

from nukytera import __version__


@pytest.mark.parametrize("command", [[], ["--help"], ["--version"]])
def test_module_cli_from_another_directory(command, tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "nukytera", *command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "nukytera" in result.stdout
    assert (__version__ if command == ["--version"] else "--help") in result.stdout


def test_unknown_command_is_rejected(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "nukytera", "run"],
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
    executable = scripts / f"nukytera{suffix}"
    result = subprocess.run(
        [str(executable), "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"nukytera {__version__}"
    installed = distribution("nukytera-core")
    assert installed.metadata["Name"] == "nukytera-core"
    assert installed.version == __version__
    entry_points = installed.entry_points.select(group="console_scripts")
    assert [(entry.name, entry.value) for entry in entry_points] == [
        ("nukytera", "nukytera.cli:main")
    ]
    assert installed.metadata["License-Expression"] == "MPL-2.0"
    assert installed.metadata.get_all("License-File") == ["LICENSE"]
    license_text = (Path(__file__).resolve().parents[1] / "LICENSE").read_text(encoding="utf-8")
    assert installed.read_text("licenses/LICENSE") == license_text
    installed_files = {str(path).replace("\\", "/") for path in installed.files}
    assert not any("agentforge" in path.lower() for path in installed_files)
    expected_modules = {
        "nukytera/__init__.py",
        "nukytera/__main__.py",
        "nukytera/cli.py",
        "nukytera/standard.py",
    }
    is_editable = any(path.startswith("__editable__.nukytera_core-") for path in installed_files)
    assert expected_modules.issubset(installed_files) or is_editable
    assert find_spec("agentforge") is None
    with pytest.raises(PackageNotFoundError):
        distribution("agentforge-core")
    assert not (scripts / f"agentforge{suffix}").exists()
