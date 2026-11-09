# SPDX-License-Identifier: MPL-2.0
import subprocess
import sys
import sysconfig
from importlib.metadata import distribution
from pathlib import Path

import pytest

from agentforge import __version__


@pytest.mark.parametrize("command", [[], ["--help"], ["--version"]])
def test_module_cli_from_another_directory(command, tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "agentforge", *command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "agentforge" in result.stdout
    assert (__version__ if command == ["--version"] else "--help") in result.stdout


def test_unknown_command_is_rejected(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "agentforge", "run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "run" in result.stderr


def test_installed_entry_point_and_metadata(tmp_path):
    scripts = Path(sysconfig.get_path("scripts"))
    executable = scripts / ("agentforge.exe" if sys.platform == "win32" else "agentforge")
    result = subprocess.run(
        [str(executable), "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"agentforge {__version__}"
    installed = distribution("agentforge-core")
    assert installed.version == __version__
    assert installed.metadata["License-Expression"] == "MPL-2.0"
    assert installed.metadata.get_all("License-File") == ["LICENSE"]
    license_text = (Path(__file__).resolve().parents[1] / "LICENSE").read_text(encoding="utf-8")
    assert installed.read_text("licenses/LICENSE") == license_text
