"""Test fixtures. Nothing here touches the real ~/.dot, the real Arc or a real CDP port."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


@pytest.fixture(autouse=True)
def isolated_dot_home(tmp_path, monkeypatch):
    """Every test gets its own DOT_HOME and no inherited session name."""
    monkeypatch.setenv("DOT_HOME", str(tmp_path / "dot"))
    monkeypatch.delenv("DOT_ARC_SESSION", raising=False)


@pytest.fixture
def dot_home(tmp_path):
    """The subcommand's home under the isolated DOT_HOME: <tmp>/dot/arc."""
    return str(tmp_path / "dot" / "arc")


# ---------------------------------------------------------------- fakes shared by the CLI tests

import urllib.error  # noqa: E402

from darc_lib import DotArcError, cdp_http, osa  # noqa: E402


def page(tid, url, typ="page", port=9222):
    return {"id": tid, "type": typ, "url": url, "title": url,
            "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/{tid}"}


class FakeHTTP:
    """Serves /json/version, /json/list and /json/activate/<id>; new targets appear after N list calls."""

    def __init__(self, port=9222, pages=None, down=False):
        self.port = port
        self.pages = list(pages or [])
        self.down = down
        self.list_calls = 0
        self.activated = []
        self.pending = []

    def add_later(self, page_, after):
        self.pending.append((after, page_))

    def fetch(self, url, timeout):
        if self.down or f"127.0.0.1:{self.port}" not in url:
            raise urllib.error.URLError("connection refused")
        if url.endswith("/json/version"):
            return {"Browser": "Chrome/130", "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/browser/x"}
        if url.endswith("/json/list"):
            self.list_calls += 1
            for after, p in list(self.pending):
                if self.list_calls >= after:
                    self.pages.append(p)
                    self.pending.remove((after, p))
            return [dict(p) for p in self.pages]
        if "/json/activate/" in url:
            self.activated.append(url.rsplit("/", 1)[1])
            return "Target activated"
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)


class FakeArc:
    """An in-memory Arc: spaces with tabs, one front window, an active space and tab.

    `auto_switch=True` imitates Arc raising a newly created tab (the behaviour `open` must undo).
    `on_new_tab(tab)` lets a test register the matching CDP target.
    """

    def __init__(self, auto_switch=False):
        self.spaces = [
            {"id": "S-agent", "title": "agent", "tabs": [{"id": "T-a1", "title": "Agent home", "url": "https://agent.example/", "location": "unpinned"}]},
            {"id": "S-byted", "title": "byted", "tabs": [{"id": "T-b1", "title": "ByteTech", "url": "https://bytetech.example/", "location": "pinned"},
                                                         {"id": "T-b2", "title": "Cloud", "url": "https://cloud.example/x", "location": "unpinned"}]},
        ]
        self.windows = 1
        self.active_space = "S-byted"
        self.active_tab = "T-b2"
        self.auto_switch = auto_switch
        self.calls = []
        self.on_new_tab = None
        self._n = 0
        self.running = True

    # -- lookups
    def _space(self, spec):
        key, val = ("id", spec[3:]) if spec.startswith("id:") else ("title", spec)
        for s in self.spaces:
            if s[key] == val:
                return s
        raise DotArcError("SPACE_NOT_FOUND", f"no space {spec}", "", 2)

    def _tab(self, tab_id):
        for s in self.spaces:
            for t in s["tabs"]:
                if t["id"] == tab_id:
                    return s, t
        raise DotArcError("TAB_NOT_FOUND", f"no tab {tab_id}", "", 2)

    def _guard(self):
        if self.windows == 0:
            raise DotArcError("NO_WINDOW", "Arc has no window open", "", 2)

    # -- builders (same signatures as darc_lib.osa)
    def arc_version(self):
        self.calls.append(("arc_version",))
        return "1.152.0"

    def list_spaces(self):
        self._guard()
        self.calls.append(("list_spaces",))
        return {"spaces": [{"id": s["id"], "title": s["title"], "active": s["id"] == self.active_space, "tabs": len(s["tabs"])}
                           for s in self.spaces], "active": self.active_space, "windows": self.windows}

    def list_tabs(self, space):
        self._guard()
        self.calls.append(("list_tabs", space))
        return [{**t, "active": t["id"] == self.active_tab} for t in self._space(space)["tabs"]]

    def active_ids(self):
        self._guard()
        self.calls.append(("active_ids",))
        return {"space": self.active_space, "tab": self.active_tab}

    def new_tab(self, space, url, restore=False):
        """One AppleScript on a real Arc: read the active tab, create, diff the ids, select the user's tab back if Arc moved."""
        self._guard()
        self.calls.append(("new_tab", space, url))
        keep = self.active_tab
        s = self._space(space)
        self._n += 1
        tab = {"id": f"T-new{self._n}", "title": "", "url": url, "location": "unpinned"}
        s["tabs"].append(tab)
        if self.auto_switch:
            self.active_space, self.active_tab = s["id"], tab["id"]
        switched = False
        if restore and keep and self.active_tab != keep:
            self.select_tab(keep)
            switched = True
        if self.on_new_tab:
            self.on_new_tab(tab)
        return {"id": tab["id"], "switched": switched, "new_ids": [tab["id"]]}

    def focus_space(self, space):
        self.calls.append(("focus_space", space))
        self.active_space = self._space(space)["id"]

    def select_tab(self, tab_id):
        self.calls.append(("select_tab", tab_id))
        s, _t = self._tab(tab_id)
        self.active_space, self.active_tab = s["id"], tab_id

    def tab_info(self, tab_id):
        self.calls.append(("tab_info", tab_id))
        _s, t = self._tab(tab_id)
        return {"id": t["id"], "title": t["title"], "url": t["url"], "loading": False}

    def set_url(self, tab_id, url):
        self.calls.append(("set_url", tab_id, url))
        self._tab(tab_id)[1]["url"] = url

    def go_back(self, tab_id):
        self.calls.append(("go_back", tab_id)); self._tab(tab_id)

    def go_forward(self, tab_id):
        self.calls.append(("go_forward", tab_id)); self._tab(tab_id)

    def reload(self, tab_id):
        self.calls.append(("reload", tab_id)); self._tab(tab_id)

    def close_tab(self, tab_id):
        self.calls.append(("close_tab", tab_id))
        s, t = self._tab(tab_id)
        s["tabs"].remove(t)
        if self.active_tab == tab_id:
            self.active_tab = s["tabs"][-1]["id"] if s["tabs"] else ""

    def is_arc_running(self):
        return self.running


BUILDERS = ["arc_version", "list_spaces", "list_tabs", "active_ids", "new_tab", "focus_space", "select_tab",
            "tab_info", "set_url", "go_back", "go_forward", "reload", "close_tab", "is_arc_running"]


@pytest.fixture
def fake_arc(monkeypatch):
    arc = FakeArc()
    for name in BUILDERS:
        monkeypatch.setattr(osa, name, getattr(arc, name))
    monkeypatch.setattr(osa, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("raw osascript must not run in tests")))
    monkeypatch.setattr(osa, "arc_app_path", lambda: "/Applications/Arc.app")
    monkeypatch.setattr(osa, "osascript_path", lambda: "/usr/bin/osascript")
    return arc


@pytest.fixture
def fake_http(monkeypatch):
    http = FakeHTTP(pages=[page("P-b1", "https://bytetech.example/"), page("P-b2", "https://cloud.example/x"),
                           page("P-a1", "https://agent.example/")])
    monkeypatch.setattr(cdp_http, "_fetch", http.fetch)
    return http


@pytest.fixture
def arc_env(fake_arc, fake_http, monkeypatch):
    """Arc and CDP together: a tab created in Arc shows up as a CDP target three polls later."""
    def on_new_tab(tab):
        fake_http.add_later(page(f"P-{tab['id']}", tab["url"]), after=fake_http.list_calls + 3)
    fake_arc.on_new_tab = on_new_tab
    monkeypatch.setattr(cdp_http.time, "sleep", lambda s: None)
    return fake_arc, fake_http


# ---------------------------------------------------------------- fake CDP page session

import base64  # noqa: E402
import json as _json  # noqa: E402
from collections import deque  # noqa: E402

from darc_lib import cdp_ws  # noqa: E402

PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def load_ax_fixture():
    with open(os.path.join(HERE, "fixtures", "ax_example.json"), encoding="utf-8") as fh:
        return _json.load(fh)["nodes"]


class FakeSession:
    """Answers the slice of CDP that darc uses, over the example AX tree.

    backend ids: 3 heading, 8 link (click navigates to /more), 11 textbox, 12 checkbox, 13 button, 14 iframe, 15 img.
    """

    def __init__(self, loader_id="L1"):
        self.ax_nodes = load_ax_fixture()
        self.known = {n["backendDOMNodeId"] for n in self.ax_nodes if "backendDOMNodeId" in n}
        self.loader_id = loader_id
        self.url, self.title = "https://example.com/", "Example Domain"
        self.selectors = {"button#go": 13, "input[name=q]": 11, "body": 2, "main": 2, "a": 8}
        self.xpaths = {"//a": 8, "//h1": 3}
        self.texts = {"More information...": 8, "Go": 13}
        self.hidden = set()
        self.background = False
        self.navigate_on_click = {8: "https://example.com/more"}
        self.calls = []
        self.events = deque()
        self.enabled = set()
        self.closed = False
        self.focused = None
        self.inserted = []
        self.keys = []
        self.mouse = []
        self.eval_hook = None
        self.screenshot_params = []
        self.last_target = None
        self.scroll = (0, 0)
        self.body_text = "Example Domain\nThis domain is for use in illustrative examples.\nMore information..."
        self.links = [{"text": "More information...", "href": "https://www.iana.org/domains/example"}]

    # -- helpers
    def quad(self, bid):
        return [10.0, 10.0, 110.0, 10.0, 110.0, 40.0, 10.0, 40.0]

    def _bid_at(self, x, y):
        """Every fake quad is the same box, so the click target is the node last scrolled into view."""
        q = self.quad(self.last_target)
        if abs(x - (q[0] + q[2]) / 2) < 0.01 and abs(y - (q[1] + q[5]) / 2) < 0.01:
            return self.last_target
        return None

    def _err(self, msg):
        raise DotArcError("CDP_ERROR", msg, "", 5)

    # -- Session interface
    def enable(self, domain):
        self.enabled.add(domain)
        self.calls.append((f"{domain}.enable", {}))

    def drain(self):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def wait_event(self, method, timeout_s, predicate=None):
        for ev in list(self.events):
            if ev["method"] == method and (predicate is None or predicate(ev.get("params", {}))):
                self.events.remove(ev)
                return ev.get("params", {})
        return None

    def send(self, method, params=None, timeout_s=None):
        params = params or {}
        self.calls.append((method, params))
        bid = params.get("backendNodeId")
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "F1", "loaderId": self.loader_id, "url": self.url}}}
        if method == "Accessibility.getFullAXTree":
            return {"nodes": self.ax_nodes}
        if method == "DOM.getDocument":
            return {"root": {"nodeId": 1, "backendNodeId": 1}}
        if method == "DOM.describeNode":
            nid = params.get("nodeId")
            if nid is not None:
                return {"node": {"nodeId": nid, "backendNodeId": nid - 1000}}
            if bid in self.known:
                return {"node": {"nodeId": 1000 + bid, "backendNodeId": bid}}
            self._err("No node with given id found")
        if method == "DOM.querySelector":
            b = self.selectors.get(params["selector"])
            return {"nodeId": 1000 + b if b else 0}
        if method == "DOM.performSearch":
            b = self.xpaths.get(params["query"])
            self._search = b
            return {"searchId": "s1", "resultCount": 1 if b else 0}
        if method == "DOM.getSearchResults":
            return {"nodeIds": [1000 + self._search]}
        if method == "DOM.discardSearchResults":
            return {}
        if method == "DOM.requestNode":
            return {"nodeId": 1000 + int(params["objectId"].split("-")[1])}
        if method == "DOM.resolveNode":
            return {"object": {"objectId": f"obj-{bid}"}}
        if method == "Runtime.callFunctionOn":
            decl = params.get("functionDeclaration", "")
            if "__darc_extract__" in decl:
                what = decl.split("__darc_extract__:")[1].split(":")[0]
                bid = int(params["objectId"].split("-")[1])
                node = next(n for n in self.ax_nodes if n.get("backendDOMNodeId") == bid)
                name = node.get("name", {}).get("value", "")
                data = {"text": name, "links": [], "html": f"<x>{name}</x>", "title": self.title}[what]
                return {"result": {"type": "object", "value": data}}
            return {"result": {"type": "undefined"}}
        if method == "DOM.focus":
            self.focused = bid
            return {}
        if method == "DOM.scrollIntoViewIfNeeded":
            if bid in self.hidden:
                self._err("Node is either not visible or not an HTMLElement")
            self.last_target = bid
            return {}
        if method == "DOM.getContentQuads":
            return {"quads": [] if bid in self.hidden else [self.quad(bid)]}
        if method == "DOM.getBoxModel":
            q = self.quad(bid)
            return {"model": {"border": q, "width": 100, "height": 30}}
        if method == "Input.dispatchMouseEvent":
            self.mouse.append(params)
            if params["type"] == "mouseReleased":
                b = self._bid_at(params["x"], params["y"])
                if b in self.navigate_on_click:
                    self.url = self.navigate_on_click[b]
                    self.loader_id = "L2"
                    self.events.append({"method": "Page.frameNavigated", "params": {"frame": {"id": "F1", "url": self.url, "loaderId": "L2"}}})
                    self.events.append({"method": "Page.loadEventFired", "params": {"timestamp": 2.0}})
            return {}
        if method == "Input.insertText":
            self.inserted.append(params["text"])
            return {}
        if method == "Input.dispatchKeyEvent":
            self.keys.append(params)
            return {}
        if method == "Page.captureScreenshot":
            self.screenshot_params.append(params)
            if self.background == "error":
                raise DotArcError("CDP_ERROR", "Page.captureScreenshot: Unable to capture screenshot", "", 5)
            if self.background:
                raise DotArcError("CDP_TIMEOUT", "Page.captureScreenshot did not answer", "", 5)
            return {"data": base64.b64encode(PNG_1x1).decode()}
        if method == "Page.getLayoutMetrics":
            return {"cssContentSize": {"x": 0, "y": 0, "width": 1280, "height": 3000},
                    "cssLayoutViewport": {"pageX": self.scroll[0], "pageY": self.scroll[1], "clientWidth": 1280, "clientHeight": 800},
                    "cssVisualViewport": {"pageX": self.scroll[0], "pageY": self.scroll[1], "clientWidth": 1280, "clientHeight": 800, "scale": 1}}
        if method == "Runtime.evaluate":
            expr = params["expression"]
            if self.eval_hook:
                hooked = self.eval_hook(expr)  # may raise, to imitate a navigating page
                if hooked is not None:
                    return hooked
            if "__darc_find_text__" in expr:
                needle = _json.loads(expr.split("__darc_find_text__(")[1].split(")*/")[0])
                b = self.texts.get(needle)
                return {"result": {"type": "object", "objectId": f"obj-{b}"} if b else {"type": "object", "subtype": "null", "value": None}}
            if "__darc_state__" in expr:
                return {"result": {"type": "object", "value": {"url": self.url, "title": self.title, "ready": "complete"}}}
            if "__darc_extract__" in expr:
                what = expr.split("__darc_extract__:")[1].split(":")[0]
                data = {"text": self.body_text, "links": self.links, "html": "<html><body>x</body></html>", "title": self.title}[what]
                return {"result": {"type": "object", "value": data}}
            if "Execution context" in expr:
                raise DotArcError("CDP_ERROR", "Execution context was destroyed", "", 5)
            if expr.startswith("throw"):
                return {"result": {"type": "object"}, "exceptionDetails": {"text": "Uncaught", "exception": {"description": "Error: boom"}}}
            if expr == "1+1":
                return {"result": {"type": "number", "value": 2}}
            if expr == "undefined":
                return {"result": {"type": "undefined"}}
            if expr.startswith("big"):
                return {"result": {"type": "string", "value": "x" * 5000}}
            return {"result": {"type": "string", "value": "ok"}}
        raise AssertionError(f"FakeSession: unexpected {method}")


@pytest.fixture
def fake_cdp(monkeypatch):
    session = FakeSession()
    session.connected = []

    def connect(ws_url, timeout_s=10.0):
        session.connected.append(ws_url)
        return session
    monkeypatch.setattr(cdp_ws, "connect", connect)
    return session
