import os

import pytest

from darc_lib import DotArcError, actions
from conftest import FakeSession, PNG_1x1, read_bytes


def test_click_dispatches_at_center_and_detects_navigation():
    cdp = FakeSession()
    r = actions.click(cdp, 8)
    assert [m["type"] for m in cdp.mouse] == ["mouseMoved", "mousePressed", "mouseReleased"]
    assert cdp.mouse[1]["x"] == 60 and cdp.mouse[1]["y"] == 25 and cdp.mouse[1]["button"] == "left" and cdp.mouse[1]["clickCount"] == 1
    assert r == {"x": 60.0, "y": 25.0}
    state = actions.settle(cdp, nav_wait_s=0.01)
    assert state == {"url": "https://example.com/more", "title": "Example Domain", "navigated": True}
    assert ("DOM.scrollIntoViewIfNeeded", {"backendNodeId": 8}) in cdp.calls


def test_click_options_and_not_visible():
    cdp = FakeSession()
    actions.click(cdp, 13, button="right", count=2)
    assert cdp.mouse[1]["button"] == "right" and [m["clickCount"] for m in cdp.mouse if m["type"] == "mousePressed"] == [1, 2]
    assert actions.settle(cdp, nav_wait_s=0.01)["navigated"] is False
    cdp.hidden.add(13)
    with pytest.raises(DotArcError) as e:
        actions.click(cdp, 13)
    assert e.value.code == "NOT_VISIBLE" and e.value.exit_code == 5


def test_fill_focuses_selects_and_inserts():
    cdp = FakeSession()
    actions.fill(cdp, 11, "hello")
    assert cdp.focused == 11 and cdp.inserted == ["hello"]
    methods = [c[0] for c in cdp.calls]
    assert methods.index("DOM.focus") < methods.index("Runtime.callFunctionOn") < methods.index("Input.insertText")
    actions.fill(cdp, 11, "")
    assert cdp.inserted == ["hello"] and cdp.keys[-1]["key"] == "Backspace"


def test_press_key_table_and_modifiers():
    cdp = FakeSession()
    actions.press(cdp, "Enter")
    assert [k["type"] for k in cdp.keys] == ["keyDown", "keyUp"]
    assert cdp.keys[0]["key"] == "Enter" and cdp.keys[0]["windowsVirtualKeyCode"] == 13 and cdp.keys[0]["text"] == "\r"
    cdp.keys.clear()
    actions.press(cdp, "Meta+a")
    assert cdp.keys[0]["modifiers"] == 4 and cdp.keys[0]["key"] == "a" and cdp.keys[0]["code"] == "KeyA" and cdp.keys[0]["windowsVirtualKeyCode"] == 65
    assert cdp.keys[0]["commands"] == ["selectAll"]  # macOS Chromium handles Cmd shortcuts natively; CDP needs the editing command
    cdp.keys.clear()
    actions.press(cdp, "Meta+c")
    assert cdp.keys[0]["commands"] == ["copy"]
    cdp.keys.clear()
    actions.press(cdp, "Shift+Tab")
    assert cdp.keys[0]["modifiers"] == 8 and cdp.keys[0]["key"] == "Tab"
    actions.press(cdp, "x", bid=11)
    assert cdp.focused == 11 and cdp.keys[-1]["key"] == "x"
    with pytest.raises(DotArcError) as e:
        actions.press(cdp, "NoSuchKey")
    assert e.value.code == "BAD_ARGS"


def test_evaluate_value_undefined_and_exception():
    cdp = FakeSession()
    assert actions.evaluate(cdp, "1+1") == 2
    assert actions.evaluate(cdp, "undefined") is None
    with pytest.raises(DotArcError) as e:
        actions.evaluate(cdp, "throw new Error('boom')")
    assert e.value.code == "ACTION_FAILED" and "boom" in e.value.message


def test_screenshot_writes_png_and_clips(tmp_path):
    cdp = FakeSession()
    p = str(tmp_path / "s.png")
    r = actions.screenshot(cdp, p)
    assert r == {"path": p, "width": 1, "height": 1} and read_bytes(p) == PNG_1x1
    actions.screenshot(cdp, p, full=True)
    assert cdp.screenshot_params[-1]["captureBeyondViewport"] is True and cdp.screenshot_params[-1]["clip"]["height"] == 3000
    cdp.scroll = (0, 500)  # the page is scrolled: box model is viewport-relative, clip must be page-relative
    actions.screenshot(cdp, p, clip_bid=8)
    assert cdp.screenshot_params[-1]["clip"] == {"x": 10.0, "y": 510.0, "width": 100.0, "height": 30.0, "scale": 1}
    assert cdp.screenshot_params[-1]["captureBeyondViewport"] is True
    cdp.background = "error"
    with pytest.raises(DotArcError) as e:
        actions.screenshot(cdp, p)
    assert e.value.code == "SCREENSHOT_NEEDS_FOREGROUND"
    cdp.background = True
    with pytest.raises(DotArcError) as e:
        actions.screenshot(cdp, p)
    assert e.value.code == "SCREENSHOT_NEEDS_FOREGROUND"


def test_extract_kinds():
    cdp = FakeSession()
    assert actions.extract(cdp, "text").startswith("Example Domain")
    assert actions.extract(cdp, "text", root_bid=13) == "Go"  # a subtree: resolved node → callFunctionOn with `this`
    assert ("DOM.resolveNode", {"backendNodeId": 13}) in cdp.calls
    assert actions.extract(cdp, "links")[0]["href"].startswith("https://www.iana.org")
    assert actions.extract(cdp, "html").startswith("<html>")
    assert actions.extract(cdp, "title") == "Example Domain"


def test_settle_survives_a_late_navigation():
    cdp = FakeSession()
    calls = {"n": 0}
    def hook(expr):
        if "__darc_state__" in expr and calls["n"] == 0:
            calls["n"] += 1
            raise DotArcError("CDP_ERROR", "Runtime.evaluate: Execution context was destroyed.", "", 5)
        return None
    cdp.eval_hook = hook
    assert actions.settle(cdp, nav_wait_s=0.01)["url"] == "https://example.com/"


def test_wait_conditions():
    cdp = FakeSession()
    ticks = iter(range(0, 1000))
    clock = lambda: next(ticks) * 0.1  # noqa: E731
    assert actions.wait(cdp, url="https://example.com/*", timeout_s=1, sleep=lambda s: None, clock=clock)["url"] == "https://example.com/"
    assert actions.wait(cdp, load="load", timeout_s=1, sleep=lambda s: None, clock=clock)["title"] == "Example Domain"
    assert actions.wait(cdp, ms=50, sleep=lambda s: None, clock=clock)["url"]
    with pytest.raises(DotArcError) as e:
        actions.wait(cdp, url="https://other/*", timeout_s=0.5, sleep=lambda s: None, clock=clock)
    assert e.value.code == "WAIT_TIMEOUT" and e.value.exit_code == 5
