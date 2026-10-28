"""An advisory file lock (flock) with a timeout, for the few steps that must not run concurrently."""
from __future__ import annotations

import contextlib
import fcntl
import os
import time

from . import DotArcError


@contextlib.contextmanager
def locked(path: str, timeout_s: float = 10.0, poll_s: float = 0.05):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise DotArcError("LOCK_TIMEOUT", f"another darc open is holding {path} for more than {timeout_s:g}s",
                                      "wait and retry; delete the lock file only if no darc process is running", 5)
                time.sleep(poll_s)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
