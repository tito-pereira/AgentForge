# SPDX-License-Identifier: MPL-2.0
"""Exclusive native execution ownership for one local project."""

import os
import stat
from contextlib import contextmanager

from corinthos.contracts import ConflictError, StoreError
from corinthos.contracts.artifacts import private_directory
from corinthos.user_state import _checked_file, _ordinary


class ProjectOwnerBusy(ConflictError):
    """A supervisor or its process guardian still owns this project."""


@contextmanager
def project_owner(root):
    path = private_directory(root) / "session-owner.lock"
    info = _ordinary(path, stat.S_ISREG)
    try:
        file = _checked_file(path, info, lock=True)
    except FileExistsError:
        info = _ordinary(path, stat.S_ISREG)
        if info is None:
            raise StoreError("Session ownership changed while being opened.") from None
        file = _checked_file(path, info, lock=True)
    with file:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ProjectOwnerBusy("Another supervisor owns this project.") from None
        # Close releases ownership only when the native guardian has closed
        # its inherited POSIX descriptor too.
        yield None if os.name == "nt" else file.fileno()
