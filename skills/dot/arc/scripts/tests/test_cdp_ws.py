"""cdp_ws.Session against an in-process websocket server that speaks a scripted slice of CDP."""
import json
import threading
import time

import pytest
from websockets.sync.server import serve

from darc_lib import DotArcError
from darc_lib import cdp_ws


class ScriptedCDP:
    """Answers methods from `replies`; `Slow.method` never answers; `Emit.event` sends an event before its reply."""

    def __init__(self):
        self.received = []
        self.replies = {"Runtime.evaluate": {"result": {"type": "string", "value": "ok"}},
                        "Page.enable": {}, "DOM.enable": {}, "Runtime.enable": {},
                        "Bad.method": {"__error__": {"code": -32601, "message": "'Bad.method' wasn't found"}}}

    def handler(self, ws):
        for raw in ws:
            msg = json.loads(raw)
            self.received.append(msg)
            m = msg["method"]
            if m == "Slow.method":
                continue
            if m == "Emit.event":
                ws.send(json.dumps({"method": "Page.loadEventFired", "params": {"timestamp": 1.0}}))
                ws.send(json.dumps({"method": "Other.event", "params": {}}))
            reply = self.replies.get(m, {})
            if "__error__" in reply:
                ws.send(json.dumps({"id": msg["id"], "error": reply["__error__"]}))
            else:
                ws.send(json.dumps({"id": msg["id"], "result": reply}))


@pytest.fixture
def server():
    scripted = ScriptedCDP()
    srv = serve(scripted.handler, "127.0.0.1", 0)
    port = srv.socket.getsockname()[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield scripted, f"ws://127.0.0.1:{port}/devtools/page/X"
    srv.shutdown()


def test_send_pairs_ids_and_returns_result(server):
    scripted, url = server
    with cdp_ws.connect(url, timeout_s=2) as s:
        r = s.send("Runtime.evaluate", {"expression": "1"})
        assert r == {"result": {"type": "string", "value": "ok"}}
        r2 = s.send("Runtime.evaluate")
        assert r2["result"]["value"] == "ok"
    ids = [m["id"] for m in scripted.received]
    assert ids == sorted(ids) and len(set(ids)) == 2 and scripted.received[0]["params"] == {"expression": "1"}


def test_enable_is_cached(server):
    scripted, url = server
    with cdp_ws.connect(url, timeout_s=2) as s:
        s.enable("Page"); s.enable("Page"); s.enable("DOM")
    assert [m["method"] for m in scripted.received] == ["Page.enable", "DOM.enable"]


def test_protocol_error_and_timeout(server):
    _, url = server
    with cdp_ws.connect(url, timeout_s=2) as s:
        with pytest.raises(DotArcError) as e:
            s.send("Bad.method")
        assert e.value.code == "CDP_ERROR" and "wasn't found" in e.value.message and e.value.exit_code == 5
        t0 = time.monotonic()
        with pytest.raises(DotArcError) as e:
            s.send("Slow.method", timeout_s=0.3)
        assert e.value.code == "CDP_TIMEOUT" and 0.25 < time.monotonic() - t0 < 2


def test_events_are_queued_and_waitable(server):
    _, url = server
    with cdp_ws.connect(url, timeout_s=2) as s:
        s.send("Emit.event")
        assert [e["method"] for e in s.events] == ["Page.loadEventFired", "Other.event"]
        ev = s.wait_event("Page.loadEventFired", timeout_s=0.2)
        assert ev == {"timestamp": 1.0}
        assert s.wait_event("Never.happens", timeout_s=0.2) is None


def test_connect_refused_is_an_error():
    with pytest.raises(DotArcError) as e:
        cdp_ws.connect("ws://127.0.0.1:1/devtools/page/X", timeout_s=1)
    assert e.value.code == "CDP_CONNECT_FAILED" and e.value.exit_code == 5
