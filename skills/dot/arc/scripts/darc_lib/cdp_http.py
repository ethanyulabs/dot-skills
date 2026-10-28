"""Chromium's HTTP endpoints on the remote-debugging port: /json/version, /json/list, /json/activate.

Only urllib: no websocket here, so the AppleScript-only commands never import websockets.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import DotArcError

DEFAULT_PORT = 9222


def relaunch_instruction(port: int) -> dict:
    shell = ("osascript -e 'quit app \"Arc\"'; sleep 3; "
             f"open -a Arc --args --remote-debugging-port={port}")
    zh = (f"Arc 需要以调试端口 {port} 重新启动一次：先退出 Arc（会保留所有标签和空间），再运行 "
          f"`open -a Arc --args --remote-debugging-port={port}`。完成后再跑一次 selftest。"
          "注意：端口只对本机进程开放，但本机任何进程都能借此操作已登录的 Arc；任务结束后正常重启 Arc 即可关闭。")
    return {"shell": shell, "zh": zh}


def _fetch(url: str, timeout: float):
    """GET url and parse JSON (or return the text for non-JSON answers). Patched in tests."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - loopback only
        body = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except ValueError:
        return body


def _get(port: int, path: str, timeout: float = 2.0):
    url = f"http://127.0.0.1:{port}{path}"
    try:
        return _fetch(url, timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        r = relaunch_instruction(port)
        raise DotArcError("CDP_UNREACHABLE", f"no DevTools endpoint on 127.0.0.1:{port} ({e})", r["zh"], 4)


def version(port: int) -> dict:
    v = _get(port, "/json/version")
    return v if isinstance(v, dict) else {}


def list_pages(port: int) -> list[dict]:
    items = _get(port, "/json/list")
    return [t for t in items if isinstance(t, dict) and t.get("type") == "page"] if isinstance(items, list) else []


def find_target(port: int, target_id: str) -> dict | None:
    for t in list_pages(port):
        if t.get("id") == target_id:
            return t
    return None


def activate(port: int, target_id: str) -> bool:
    try:
        _get(port, f"/json/activate/{target_id}")
        return True
    except DotArcError:
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
