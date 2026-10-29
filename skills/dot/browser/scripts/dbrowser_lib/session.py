"""Sessions: one JSON file per agent task under ~/.dot/browser/sessions/<name>.json.

There is no implicit default session. `open` names a new one (6 base32 characters) unless --session
was given; later commands take --session or the DOT_BROWSER_SESSION environment variable, so several agents
can work side by side without touching each other's files.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets

from . import DotBrowserError
from .home import session_path, sessions_dir

SCHEMA = "dot-browser/session/1"
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def check_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name in (".", ".."):
        raise DotBrowserError("SESSION_INVALID", f"invalid session name {name!r}",
                          "use 1-40 letters, digits, '.', '_' or '-'", 2)
    return name


def new_name() -> str:
    while True:
        name = "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not os.path.exists(session_path(name)):
            return name


def resolve_name(flag: str | None, env: dict) -> str:
    name = flag or env.get("DOT_BROWSER_SESSION")
    if not name:
        existing = ", ".join(s["name"] for s in list_sessions()[:8]) or "none"
        raise DotBrowserError("NO_SESSION", "no session given",
                          f"pass --session NAME or export DOT_BROWSER_SESSION=NAME (the value `open` printed); existing: {existing}", 2)
    return check_name(name)


def create(name: str, port: int, space: dict, tab: dict, browser: str = "arc") -> dict:
    now = _now()
    return {"schema": SCHEMA, "name": check_name(name), "browser": browser, "port": int(port), "space": dict(space), "tab": dict(tab),
            "created": now, "last_used": now, "snapshot": None}


def save(sess: dict) -> str:
    path = session_path(check_name(sess["name"]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sess, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def load(name: str) -> dict:
    path = session_path(check_name(name))
    if not os.path.isfile(path):
        existing = ", ".join(s["name"] for s in list_sessions()[:8]) or "none"
        raise DotBrowserError("NO_SESSION", f"session '{name}' does not exist", f"run `dbrowser open` first; existing: {existing}", 2)
    try:
        with open(path, encoding="utf-8") as fh:
            sess = json.load(fh)
    except (OSError, ValueError) as e:
        raise DotBrowserError("SESSION_INVALID", f"session file unreadable: {e}", f"delete {path} and open again", 2)
    if not isinstance(sess, dict) or sess.get("schema") != SCHEMA or "tab" not in sess:
        raise DotBrowserError("SESSION_INVALID", f"session file has an unexpected shape: {path}", "delete it and open again", 2)
    return sess


def delete(name: str) -> bool:
    path = session_path(check_name(name))
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def touch(sess: dict) -> None:
    sess["last_used"] = _now()


def set_refs(sess: dict, *, url: str, root: str, loader_id: str, refs: dict) -> None:
    sess["snapshot"] = {"taken": _now(), "url": url, "root": root, "loader_id": loader_id, "refs": refs}


def list_sessions() -> list[dict]:
    d = sessions_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as fh:
                s = json.load(fh)
            if isinstance(s, dict) and s.get("schema") == SCHEMA:
                out.append(s)
        except (OSError, ValueError):
            continue
    out.sort(key=lambda s: s.get("last_used", ""), reverse=True)
    return out
