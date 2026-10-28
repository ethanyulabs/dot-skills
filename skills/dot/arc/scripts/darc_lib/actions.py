"""Page actions over one cdp_ws.Session (or anything with the same send/enable/wait_event interface)."""
from __future__ import annotations

import base64
import fnmatch
import json
import struct
import time

from . import DotArcError

STATE_JS = "/*__darc_state__*/({url: location.href, title: document.title, ready: document.readyState})"

EXTRACT_JS = {
    "text": "root.innerText",
    "links": 'Array.from(root.querySelectorAll("a[href]")).map(a => ({text: (a.innerText || a.getAttribute("aria-label") || "").replace(/\\s+/g, " ").trim(), href: a.href}))',
    "html": "root.outerHTML",
    "title": "document.title",
}

# name → (key, code, windowsVirtualKeyCode, text)
KEYS = {
    "Enter": ("Enter", "Enter", 13, "\r"), "Tab": ("Tab", "Tab", 9, None), "Escape": ("Escape", "Escape", 27, None),
    "Backspace": ("Backspace", "Backspace", 8, None), "Delete": ("Delete", "Delete", 46, None),
    "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37, None), "ArrowUp": ("ArrowUp", "ArrowUp", 38, None),
    "ArrowRight": ("ArrowRight", "ArrowRight", 39, None), "ArrowDown": ("ArrowDown", "ArrowDown", 40, None),
    "Home": ("Home", "Home", 36, None), "End": ("End", "End", 35, None),
    "PageUp": ("PageUp", "PageUp", 33, None), "PageDown": ("PageDown", "PageDown", 34, None),
    "Space": (" ", "Space", 32, " "), "F5": ("F5", "F5", 116, None),
}
MODIFIERS = {"alt": 1, "option": 1, "control": 2, "ctrl": 2, "meta": 4, "cmd": 4, "command": 4, "shift": 8}
# macOS Chromium runs Cmd shortcuts in the native layer, which CDP key events do not reach: name the editing command
EDIT_COMMANDS = {"a": "selectAll", "c": "copy", "v": "paste", "x": "cut", "z": "undo"}


def page_state(cdp) -> dict:
    try:
        r = cdp.send("Runtime.evaluate", {"expression": STATE_JS, "returnByValue": True})
    except DotArcError as e:
        if e.code == "CDP_ERROR" and "context" in e.message.lower():  # the page is navigating right now
            cdp.wait_event("Page.loadEventFired", 5.0)
            r = cdp.send("Runtime.evaluate", {"expression": STATE_JS, "returnByValue": True})
        else:
            raise
    return dict(r.get("result", {}).get("value") or {"url": "", "title": "", "ready": ""})


def node_center(cdp, bid: int) -> tuple[float, float]:
    cdp.enable("DOM")
    try:
        cdp.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": bid})
        quads = cdp.send("DOM.getContentQuads", {"backendNodeId": bid}).get("quads") or []
    except DotArcError as e:
        if e.code == "CDP_ERROR":
            raise DotArcError("NOT_VISIBLE", f"element is not rendered: {e.message}", "it may be hidden or detached; take a new snapshot", 5)
        raise
    if not quads:
        raise DotArcError("NOT_VISIBLE", "element has no visible box", "it may be hidden; take a new snapshot or scroll", 5)
    q = quads[0]
    xs, ys = q[0::2], q[1::2]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def click(cdp, bid: int, button: str = "left", count: int = 1) -> dict:
    cdp.enable("Page")
    x, y = node_center(cdp, bid)
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    for i in range(1, count + 1):
        cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": button, "clickCount": i})
        cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": button, "clickCount": i})
    return {"x": x, "y": y}


def settle(cdp, nav_wait_s: float = 2.0) -> dict:
    """After an action: did the main frame navigate (within nav_wait_s; a cold cross-site load can take
    over a second)? Then the current url and title."""
    nav = cdp.wait_event("Page.frameNavigated", nav_wait_s, predicate=lambda p: not p.get("frame", {}).get("parentId"))
    if nav is not None:
        cdp.wait_event("Page.loadEventFired", 5.0)
    state = page_state(cdp)
    return {"url": state.get("url", ""), "title": state.get("title", ""), "navigated": nav is not None}


def fill(cdp, bid: int, text: str) -> None:
    cdp.enable("Page")
    cdp.enable("DOM")
    cdp.send("DOM.focus", {"backendNodeId": bid})
    obj = cdp.send("DOM.resolveNode", {"backendNodeId": bid})["object"]["objectId"]
    cdp.send("Runtime.callFunctionOn", {"objectId": obj, "functionDeclaration": (
        "function() { if (typeof this.select === 'function') { this.select(); return; }"
        " const r = document.createRange(); r.selectNodeContents(this);"
        " const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); }")})
    if text:
        cdp.send("Input.insertText", {"text": text})
    else:
        press(cdp, "Backspace")


def parse_key(spec: str) -> dict:
    parts = spec.split("+") if spec != "+" else ["+"]
    *mods, key = parts
    modifiers = 0
    for m in mods:
        if m.lower() not in MODIFIERS:
            raise DotArcError("BAD_ARGS", f"unknown modifier {m!r} in {spec!r}", "use Meta, Ctrl, Alt, Shift", 2)
        modifiers |= MODIFIERS[m.lower()]
    if key in KEYS:
        k, code, vk, text = KEYS[key]
    elif len(key) == 1:
        k, text = key, key
        if key.isalpha():
            code, vk = f"Key{key.upper()}", ord(key.upper())
        elif key.isdigit():
            code, vk = f"Digit{key}", ord(key)
        else:
            code, vk = "", 0
    else:
        raise DotArcError("BAD_ARGS", f"unknown key {key!r}", f"one character or one of: {', '.join(KEYS)}", 2)
    commands = []
    if modifiers & ~8:  # with Meta/Ctrl/Alt no character is typed
        text = None
        if modifiers & 4 and key.lower() in EDIT_COMMANDS:
            commands = [EDIT_COMMANDS[key.lower()]]
    return {"modifiers": modifiers, "key": k, "code": code, "windowsVirtualKeyCode": vk, "text": text, "commands": commands}


def press(cdp, spec: str, bid: int | None = None) -> dict:
    cdp.enable("Page")
    if bid is not None:
        cdp.enable("DOM")
        cdp.send("DOM.focus", {"backendNodeId": bid})
    k = parse_key(spec)
    base = {"modifiers": k["modifiers"], "key": k["key"], "code": k["code"], "windowsVirtualKeyCode": k["windowsVirtualKeyCode"],
            "nativeVirtualKeyCode": k["windowsVirtualKeyCode"]}
    down = {"type": "keyDown" if k["text"] else "rawKeyDown", **base}
    if k["text"]:
        down["text"] = k["text"]
        down["unmodifiedText"] = k["text"]
    if k["commands"]:
        down["commands"] = k["commands"]
    cdp.send("Input.dispatchKeyEvent", down)
    cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", **base})
    return k


def evaluate(cdp, expression: str):
    r = cdp.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": True})
    exc = r.get("exceptionDetails")
    if exc:
        desc = (exc.get("exception") or {}).get("description") or exc.get("text") or "exception"
        raise DotArcError("ACTION_FAILED", f"JavaScript threw: {desc.splitlines()[0]}", "", 5)
    return r.get("result", {}).get("value")


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    return 0, 0


def screenshot(cdp, path: str, full: bool = False, clip_bid: int | None = None, timeout_s: float = 3.0) -> dict:
    cdp.enable("Page")
    params: dict = {"format": "png"}
    if clip_bid is not None:
        cdp.enable("DOM")
        cdp.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": clip_bid})
        q = cdp.send("DOM.getBoxModel", {"backendNodeId": clip_bid})["model"]["border"]
        metrics = cdp.send("Page.getLayoutMetrics")
        vv = metrics.get("cssVisualViewport") or metrics.get("visualViewport") or {}
        xs, ys = q[0::2], q[1::2]  # viewport coordinates; the clip wants page coordinates
        params["clip"] = {"x": min(xs) + vv.get("pageX", 0), "y": min(ys) + vv.get("pageY", 0),
                          "width": max(xs) - min(xs), "height": max(ys) - min(ys), "scale": 1}
        params["captureBeyondViewport"] = True
    elif full:
        metrics = cdp.send("Page.getLayoutMetrics")
        size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
        params["clip"] = {"x": 0, "y": 0, "width": size.get("width", 0), "height": size.get("height", 0), "scale": 1}
        params["captureBeyondViewport"] = True
    try:
        data = base64.b64decode(cdp.send("Page.captureScreenshot", params, timeout_s=timeout_s)["data"])
    except DotArcError as e:
        if e.code == "CDP_TIMEOUT" or (e.code == "CDP_ERROR" and "screenshot" in e.message.lower()):
            raise DotArcError("SCREENSHOT_NEEDS_FOREGROUND", f"the tab is in the background and Chromium did not render it ({e.message})",
                              "用 `darc extract` / `darc eval` 读内容不需要前台；确实要截图时加 --activate（会短暂切到该标签再切回来）", 5)
        raise
    import os
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    w, h = _png_size(data)
    return {"path": path, "width": w, "height": h}


def extract(cdp, what: str, root_bid: int | None = None):
    """Text / links / html / title of the page, or of the element with backendNodeId `root_bid`."""
    if what not in EXTRACT_JS:
        raise DotArcError("BAD_ARGS", f"unknown --what {what!r}", "text, links, html or title", 2)
    if root_bid is None:
        js = f"/*__darc_extract__:{what}:*/(() => {{ const root = document.body; return {EXTRACT_JS[what]}; }})()"
        return evaluate(cdp, js)
    cdp.enable("DOM")
    obj = cdp.send("DOM.resolveNode", {"backendNodeId": root_bid})["object"]["objectId"]
    r = cdp.send("Runtime.callFunctionOn", {"objectId": obj, "returnByValue": True,
                                            "functionDeclaration": f"/*__darc_extract__:{what}:*/function() {{ const root = this; return {EXTRACT_JS[what]}; }}"})
    exc = r.get("exceptionDetails")
    if exc:
        desc = (exc.get("exception") or {}).get("description") or exc.get("text") or "exception"
        raise DotArcError("ACTION_FAILED", f"JavaScript threw: {desc.splitlines()[0]}", "", 5)
    return r.get("result", {}).get("value")


def wait(cdp, url: str | None = None, selector: str | None = None, text: str | None = None, ms: int | None = None,
         load: str | None = None, timeout_s: float = 10.0, sleep=None, clock=None) -> dict:
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    if ms is not None:
        sleep(ms / 1000.0)
    deadline = clock() + timeout_s
    while True:
        state = page_state(cdp)
        ok = True
        if url is not None and not fnmatch.fnmatchcase(state.get("url", ""), url):
            ok = False
        if ok and load is not None:
            ready = state.get("ready", "")
            ok = ready == "complete" if load == "load" else ready in ("interactive", "complete")
        if ok and selector is not None:
            ok = bool(evaluate(cdp, f"!!document.querySelector({json.dumps(selector)})"))
        if ok and text is not None:
            ok = bool(evaluate(cdp, f"document.body.innerText.includes({json.dumps(text)})"))
        if ok:
            return {"url": state.get("url", ""), "title": state.get("title", "")}
        if clock() >= deadline:
            what = {k: v for k, v in (("url", url), ("selector", selector), ("text", text), ("load", load)) if v is not None}
            raise DotArcError("WAIT_TIMEOUT", f"condition not met within {timeout_s:g}s: {what}", f"page is at {state.get('url')!r}", 5)
        sleep(0.1)
