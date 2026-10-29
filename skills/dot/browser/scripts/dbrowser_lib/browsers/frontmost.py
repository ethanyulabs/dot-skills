"""The frontmost application, through System Events, tracked by process id (never by name: the user's
own Chrome and dot's Chrome share a name). Used to put the user's app back after a browser raised a
window. System Events needs the Automation permission once; without it every call returns None and
callers skip the restore (selftest reports it)."""
from __future__ import annotations

import subprocess


def _osascript(script: str, timeout: float = 5.0) -> str:
    try:
        cp = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return cp.stdout.strip() if cp.returncode == 0 else ""


def current_pid() -> int | None:
    """Unix pid of the frontmost process, or None when it cannot be read (no permission, not macOS)."""
    out = _osascript('tell application "System Events" to get unix id of first process whose frontmost is true')
    return int(out) if out.isdigit() else None


def activate_pid(pid: int) -> None:
    if pid:
        _osascript(f'tell application "System Events" to set frontmost of (first process whose unix id is {int(pid)}) to true')
