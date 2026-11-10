# SPDX-License-Identifier: MPL-2.0
"""Real bounded child processes test lifecycle ownership without agent calls."""

import os
import subprocess
import sys
import time

import pytest

from corinthos.adapters import process_control
from corinthos.adapters.process_control import ProcessStartError, start_process


def test_normal_exit_cleanup_is_confirmed_and_idempotent():
    managed = start_process(
        [sys.executable, "-c", "print('ordinary child')"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = managed.process.communicate(timeout=10)
    assert managed.process.returncode == 0 and stdout.strip() == b"ordinary child" and not stderr
    assert managed.finish() is True and managed.finish() is True


def test_remaining_child_cannot_write_after_parent_success(tmp_path):
    marker = tmp_path / "late.txt"
    release = tmp_path / "release.txt"
    child = (
        "import time; from pathlib import Path; release=Path("
        + repr(str(release))
        + "); deadline=time.monotonic()+5\n"
        "while not release.exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "if release.exists(): Path(" + repr(str(marker)) + ").write_text('late')"
    )
    parent = (
        "import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
        + repr(child)
        + "],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); print('parent success')"
    )
    managed = start_process(
        [sys.executable, "-c", parent], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = managed.process.communicate(timeout=10)
    assert managed.process.returncode == 0 and stdout.strip() == b"parent success" and not stderr
    cleaned = managed.finish()
    if os.name == "nt":
        assert cleaned is True
    release.write_text("Attempt a late write only after cleanup.", encoding="utf-8")
    time.sleep(0.2)
    assert not marker.exists()


def test_finish_stops_live_parent_and_descendants(tmp_path):
    marker = tmp_path / "late.txt"
    managed = start_process(
        [
            sys.executable,
            "-c",
            "import time; from pathlib import Path; time.sleep(2); Path("
            + repr(str(marker))
            + ").write_text('late')",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert managed.finish() is True
    assert managed.process.poll() is not None and not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended job assignment boundary.")
@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_assignment_failure_never_runs_suspended_user_code(tmp_path, monkeypatch, error):
    marker = tmp_path / "must-not-run.txt"

    def fail(self, process):
        raise error("Synthetic job assignment failure")

    monkeypatch.setattr(process_control._WindowsJob, "assign_and_resume", fail)
    with pytest.raises(ProcessStartError if error is OSError else KeyboardInterrupt) as failure:
        start_process(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('unsafe')",
            ]
        )
    if error is OSError:
        assert failure.value.cleanup_confirmed is True
    time.sleep(0.1)
    assert not marker.exists()
