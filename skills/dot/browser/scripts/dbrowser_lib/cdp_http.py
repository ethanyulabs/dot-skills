"""Chromium's HTTP endpoints on the remote-debugging port: /json/version, /json/list, /json/activate.

Only urllib: no websocket here, so the AppleScript-only commands never import websockets.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import DotBrowserError

DEFAULT_PORT = 9222


GENERIC_HINT = "the browser is not listening on this port; run `dbrowser selftest` for the launch instruction"


def _fetch(url: str, timeout: float):
    """GET url and parse JSON (or return the text for non-JSON answers). Patched in tests."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - loopback only
        body = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except ValueError:
        return body


def _get(port: int, path: str, timeout: float = 2.0, hint: str = ""):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        return _fetch(url, timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise DotBrowserError("CDP_UNREACHABLE", f"no DevTools endpoint on 127.0.0.1:{port} ({e})", hint or GENERIC_HINT, 4)


def version(port: int, hint: str = "") -> dict:
    v = _get(port, "/json/version", hint=hint)
    return v if isinstance(v, dict) else {}


def list_pages(port: int, hint: str = "") -> list[dict]:
    items = _get(port, "/json/list", hint=hint)
    return [t for t in items if isinstance(t, dict) and t.get("type") == "page"] if isinstance(items, list) else []


def find_target(port: int, target_id: str, hint: str = "") -> dict | None:
    for t in list_pages(port, hint=hint):
        if t.get("id") == target_id:
            return t
    return None


def activate(port: int, target_id: str) -> bool:
    try:
        _get(port, f"/json/activate/{target_id}")
        return True
    except DotBrowserError:
        return False


def _norm(url: str) -> tuple[str, str, str]:
    u = urlsplit(url)
    host = (u.hostname or "").lower()
    return u.scheme.lower(), host, u.path or "/"


def _url_prefix_match(cand: str, hint: str) -> bool:
    cs, ch, cp = _norm(cand)
    hs, hh, hp = _norm(hint)
    return cs == hs and ch == hh and cp.startswith(hp)


def _host_match(cand: str, hint: str) -> bool:
    ch, hh = _norm(cand)[1], _norm(hint)[1]
    if not ch or not hh:
        return False
    base = hh.split(".")[-2:]
    return ch == hh or ch.split(".")[-2:] == base


def wait_new_page(port: int, before: set, url_hint: str, timeout_s: float = 5.0, poll_s: float = 0.1,
                  sleep=None, clock=None) -> dict:
    """Polls /json/list for page targets that were not in `before` and match `url_hint`.

    Returns {"target": the one to bind or None, "candidates": the unmatched new targets}. A new target
    binds only when its URL matches the hint (prefix first, then host, so redirects to a login host still
    bind); a tab the user opened meanwhile, or one still at about:blank, never does. Several matches at
    once are returned as candidates.
    """
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    deadline = clock() + timeout_s
    while True:
        new = [t for t in list_pages(port) if t.get("id") not in before]
        for matcher in (_url_prefix_match, _host_match):
            hits = [t for t in new if matcher(t.get("url", ""), url_hint)]
            if len(hits) == 1:
                return {"target": hits[0], "candidates": []}
            if len(hits) > 1:
                return {"target": None, "candidates": hits}
        if clock() >= deadline:
            return {"target": None, "candidates": new}
        sleep(poll_s)
