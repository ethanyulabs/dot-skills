"""A minimal synchronous CDP client over one page's websocket (the only module that imports websockets).

One Session per command: connect, enable the domains the command needs, send a handful of methods,
close. Events arriving in between are queued on `events` so `wait_event` can look at them.
"""
from __future__ import annotations

import json
import socket
import time
from collections import deque

from . import DotBrowserError


class Session:
    def __init__(self, ws, timeout_s: float = 10.0):
        self._ws = ws
        self._id = 0
        self.timeout_s = timeout_s
        self.events: deque[dict] = deque(maxlen=500)
        self._enabled: set[str] = set()

    # -- lifecycle
    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- protocol
    def send(self, method: str, params: dict | None = None, timeout_s: float | None = None) -> dict:
        """Sends one method and returns its `result`. Protocol errors raise CDP_ERROR, silence raises CDP_TIMEOUT."""
        self._id += 1
        mid = self._id
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.monotonic() + (timeout_s if timeout_s is not None else self.timeout_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DotBrowserError("CDP_TIMEOUT", f"{method} did not answer within {timeout_s if timeout_s is not None else self.timeout_s:g}s",
                                  "the tab may be in the background or asleep; try again, reload it, or pass --activate for screenshots", 5)
            try:
                raw = self._ws.recv(timeout=remaining)
            except TimeoutError:
                continue
            except Exception as e:
                raise DotBrowserError("CDP_CONNECT_FAILED", f"connection to the tab dropped during {method}: {e}",
                                  "the tab was closed or Arc restarted; run `dbrowser sessions` and attach again", 5)
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    err = msg["error"]
                    raise DotBrowserError("CDP_ERROR", f"{method}: {err.get('message', err)}", "", 5,
                                      payload={"cdp_error": err})
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def enable(self, domain: str) -> None:
        if domain not in self._enabled:
            self.send(f"{domain}.enable")
            self._enabled.add(domain)

    def wait_event(self, method: str, timeout_s: float, predicate=None) -> dict | None:
        """Returns the params of the first matching event (queued or arriving before the timeout), else None."""
        deadline = time.monotonic() + timeout_s
        while True:
            for ev in list(self.events):
                if ev.get("method") == method and (predicate is None or predicate(ev.get("params", {}))):
                    self.events.remove(ev)
                    return ev.get("params", {})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                raw = self._ws.recv(timeout=remaining)
            except TimeoutError:
                return None
            except Exception:
                return None
            msg = json.loads(raw)
            if "method" in msg:
                self.events.append(msg)


def connect(ws_url: str, timeout_s: float = 10.0) -> Session:
    from websockets.sync.client import connect as ws_connect
    kwargs = dict(open_timeout=min(timeout_s, 10.0), max_size=None, close_timeout=1.0)
    try:
        try:
            ws = ws_connect(ws_url, legacy=True, **kwargs)  # websockets >= 17.1: direct use needs legacy=True
        except TypeError:
            ws = ws_connect(ws_url, **kwargs)  # older websockets: no legacy flag
    except (OSError, socket.error, TimeoutError) as e:
        raise DotBrowserError("CDP_CONNECT_FAILED", f"cannot open {ws_url}: {e}",
                          "the target may be gone; run `dbrowser sessions`, reload the tab or attach again", 5)
    except Exception as e:  # handshake refused (403 origin, bad path)
        raise DotBrowserError("CDP_CONNECT_FAILED", f"websocket handshake failed for {ws_url}: {e}",
                          "if Arc answers 403, relaunch it with --remote-allow-origins=* added to --remote-debugging-port", 5)
    return Session(ws, timeout_s=timeout_s)
