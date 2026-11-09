# SPDX-License-Identifier: MPL-2.0
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("path", [".nukytera/private.json", ".agentforge/private.json"])
def test_private_state_is_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", path],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr or f"Private state is not ignored: {path}"
