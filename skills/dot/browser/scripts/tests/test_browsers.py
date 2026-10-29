"""The adapter layer: registry, system default, the Arc adapter over osa, the chromium adapter over CDP."""
import os
import plistlib

import pytest

from conftest import FakeBrowserWS
from dbrowser_lib import DotBrowserError, cdp_http
from dbrowser_lib.browsers import registry
from dbrowser_lib.home import profile_dir


# ---------------------------------------------------------------- registry

def test_registry_keys_and_isolation():
    assert list(registry.BROWSERS) == ["arc", "chrome", "edge"]
    assert registry.make("arc").isolation == "space" and registry.make("chrome").isolation == "instance"
    assert registry.make("edge", port=9300).port == 9300 and registry.make("edge").port == 9224
    assert registry.make("chrome").port == 9223 and registry.make("arc").port == 9222
    with pytest.raises(DotBrowserError) as e:
        registry.make("safari")
    assert e.value.code == "BROWSER_UNSUPPORTED" and e.value.exit_code == 2


def test_by_bundle_id_is_case_insensitive():
    assert registry.by_bundle_id("company.thebrowser.browser") == "arc"
    assert registry.by_bundle_id("COMPANY.thebrowser.Browser") == "arc"
    assert registry.by_bundle_id("com.google.chrome") == "chrome" and registry.by_bundle_id("com.microsoft.edgemac") == "edge"
    assert registry.by_bundle_id("com.apple.safari") is None


def _write_plist(path, https_handler):
    data = {"LSHandlers": [{"LSHandlerURLScheme": "mailto", "LSHandlerRoleAll": "com.apple.mail"},
                           {"LSHandlerURLScheme": "https", "LSHandlerRoleAll": https_handler}]}
    with open(path, "wb") as fh:
        plistlib.dump(data, fh)


def test_system_default_reads_launch_services(tmp_path, monkeypatch):
    p = str(tmp_path / "ls.plist")
    monkeypatch.setattr(registry, "plist_path", lambda: p)
    assert registry.system_default() == (None, None)  # no plist: unknown
    _write_plist(p, "com.google.chrome")
    assert registry.system_default() == ("com.google.chrome", "chrome")
    _write_plist(p, "com.apple.safari")
    assert registry.system_default() == ("com.apple.safari", None)


# ---------------------------------------------------------------- arc adapter

def test_arc_adapter_delegates_to_osa(arc_env):
    arc, http = arc_env
    b = registry.make("arc")
    assert b.running() is True and b.version() == "1.152.0" and b.list_spaces()["spaces"][0]["title"] == "agent"
    info = b.navigate("T-b2", "goto", "https://cloud.example/y", wait=True, timeout_s=1.0)
    assert ("set_url", "T-b2", "https://cloud.example/y") in arc.calls and info["url"] == "https://cloud.example/y" and info["loading"] is False
    b.navigate("T-b2", "back", wait=False, timeout_s=1.0)
    assert ("go_back", "T-b2") in arc.calls
    with pytest.raises(DotBrowserError) as e:
        b.launch(timeout_s=1.0)
    assert e.value.code == "BAD_ARGS"
    with pytest.raises(DotBrowserError) as e:
        b.quit()
    assert e.value.code == "BAD_ARGS"
    assert "--remote-debugging-port=9222" in b.launch_instruction()["shell"] and "Arc" in b.launch_instruction()["zh"]


# ---------------------------------------------------------------- chromium adapter

def test_chrome_launch_command_and_running(chrome_env):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    cmd = b.launch_command()
    assert cmd[:3] == ["open", "-gna", "Google Chrome"] and "--args" in cmd
    assert f"--user-data-dir={profile_dir('chrome')}" in cmd and "--remote-debugging-port=9223" in cmd
    for flag in ("--no-first-run", "--no-default-browser-check", "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding"):
        assert flag in cmd
    assert b.running() is False
    state["running"] = True
    assert b.running() is True
    e = registry.make("edge")
    assert e.launch_command()[2] == "Microsoft Edge" and f"--user-data-dir={profile_dir('edge')}" in e.launch_command()
    assert "Microsoft Edge" in e.launch_instruction()["shell"]


def test_chrome_launch_spawns_and_waits_for_the_port(chrome_env, fake_http):
    chromium, ws, state = chrome_env
    fake_http.down = True
    b = registry.make("chrome")
    b.launch(timeout_s=2.0)
    assert len(state["spawned"]) == 1 and state["running"] is True and b.cdp_reachable() is True
    # already up: launching again is a no-op
    b.launch(timeout_s=2.0)
    assert len(state["spawned"]) == 1


def test_chrome_launch_restores_the_frontmost_app(chrome_env, fake_http, monkeypatch):
    chromium, ws, state = chrome_env
    fake_http.down = True

    def spawn(cmd):  # a fresh profile opens a window and dot's Chrome comes to the front
        state["spawned"].append(cmd)
        state["running"] = True
        fake_http.down = False
        state["frontmost"] = "dot Chrome"
    monkeypatch.setattr(chromium, "_spawn", spawn)
    b = registry.make("chrome")
    assert b.launch(timeout_s=2.0) is True  # restored
    assert state["activated"] == ["Terminal"] and state["frontmost"] == "Terminal"
    assert b.launch(timeout_s=2.0) is False  # already up: nothing to restore


def test_chrome_launch_profile_locked_when_instance_runs_without_the_port(chrome_env, fake_http):
    chromium, ws, state = chrome_env
    fake_http.down = True
    state["running"] = True
    b = registry.make("chrome")
    with pytest.raises(DotBrowserError) as e:
        b.launch(timeout_s=0.2)
    assert e.value.code == "PROFILE_LOCKED" and e.value.exit_code == 4 and "quit" in e.value.hint
    assert state["spawned"] == []


def test_chrome_launch_waits_for_an_instance_another_agent_just_started(chrome_env, fake_http, monkeypatch):
    """Process present, port not yet open (another agent's `open -gna` a second ago): wait, do not report PROFILE_LOCKED."""
    chromium, ws, state = chrome_env
    fake_http.down = True
    state["running"] = True
    polls = {"n": 0}
    real_version = cdp_http.version

    def version(port, hint=""):
        polls["n"] += 1
        if polls["n"] >= 3:
            fake_http.down = False
        return real_version(port, hint)
    monkeypatch.setattr(chromium.cdp_http, "version", version)
    b = registry.make("chrome")
    assert b.launch(timeout_s=2.0) is False
    assert state["spawned"] == [] and b.cdp_reachable()


def test_chrome_launch_takes_the_open_lock(chrome_env, fake_http, monkeypatch):
    chromium, ws, state = chrome_env
    fake_http.down = True
    seen = []
    import contextlib

    @contextlib.contextmanager
    def locked(path, timeout_s=10.0, poll_s=0.05):
        seen.append(path)
        yield
    monkeypatch.setattr(chromium, "locked", locked)
    registry.make("chrome").launch(timeout_s=1.0)
    assert seen and seen[0].endswith("/browser/lock")


def test_chrome_launch_failed_when_port_never_answers(chrome_env, fake_http, monkeypatch):
    chromium, ws, state = chrome_env
    fake_http.down = True
    monkeypatch.setattr(chromium, "_spawn", lambda cmd: state["spawned"].append(cmd))  # spawns, port stays closed
    b = registry.make("chrome")
    with pytest.raises(DotBrowserError) as e:
        b.launch(timeout_s=0.3)
    assert e.value.code == "LAUNCH_FAILED" and e.value.exit_code == 4


def test_chrome_new_tab_opens_a_window_and_restores_the_frontmost_app(chrome_env):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    # creating the window brings Chrome to the front; the adapter puts the user's app back
    state["running"] = True

    def send(method, params=None, timeout_s=None):
        if method == "Target.createTarget" and ws._n == 0:  # only the first window raises dot's instance
            state["frontmost"] = "dot Chrome"
        return FakeBrowserWS.send(ws, method, params, timeout_s)
    ws.send = send
    r = b.new_tab("", "https://example.com/", restore=True)
    assert r["id"] == "P-new1" and r["new_ids"] == ["P-new1"] and r["switched"] is True
    assert ws.calls[0] == ("Target.createTarget", {"url": "https://example.com/", "newWindow": True, "background": True})
    assert state["activated"] == ["Terminal"] and state["frontmost"] == "Terminal"
    # a second window when the front app did not change: nothing restored
    r2 = b.new_tab("", "https://example.com/2", restore=True)
    assert r2["switched"] is False and state["activated"] == ["Terminal"]


def test_chrome_restore_is_by_pid_and_only_when_dot_instance_took_the_front(chrome_env):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    state["running"] = True
    # the user's own Chrome is in front: dot's window raising itself is detected by pid, and the user's Chrome is put back
    state["frontmost"] = "Google Chrome"
    ws.send = lambda m, p=None, t=None: (state.__setitem__("frontmost", "dot Chrome") if m == "Target.createTarget" else None) or FakeBrowserWS.send(ws, m, p, t)
    r = b.new_tab("", "https://example.com/", restore=True)
    assert r["switched"] is True and state["frontmost"] == "Google Chrome" and state["activated"] == ["Google Chrome"]
    # the user switched to another app meanwhile: not dot's instance in front, so nothing is touched
    state["activated"].clear()
    ws.send = lambda m, p=None, t=None: (state.__setitem__("frontmost", "Terminal") if m == "Target.createTarget" else None) or FakeBrowserWS.send(ws, m, p, t)
    r = b.new_tab("", "https://example.com/2", restore=True)
    assert r["switched"] is False and state["activated"] == [] and state["frontmost"] == "Terminal"


def test_chrome_tab_info_list_tabs_spaces_and_missing_tab(chrome_env):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    b.new_tab("", "https://example.com/", restore=False)
    info = b.tab_info("P-new1")
    assert info == {"id": "P-new1", "url": "https://example.com/", "title": "https://example.com/", "loading": False}
    assert [t["id"] for t in b.list_tabs("")] == ["P-home", "P-new1"] and b.list_tabs("")[0]["location"] == "window"
    assert b.list_spaces() == {"spaces": [], "active": "", "windows": None, "isolation": "instance"}
    assert b.active_ids() == {"space": "", "tab": ""}
    with pytest.raises(DotBrowserError) as e:
        b.tab_info("P-nope")
    assert e.value.code == "TAB_NOT_FOUND" and e.value.exit_code == 2


def test_chrome_navigate_waits_for_load_events(chrome_env):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    b.new_tab("", "https://example.com/", restore=False)
    ws.events.extend([{"method": "Page.frameNavigated", "params": {"frame": {"id": "F1", "url": "https://example.com/next"}}},
                      {"method": "Page.loadEventFired", "params": {}}])
    info = b.navigate("P-new1", "goto", "https://example.com/next", wait=True, timeout_s=1.0)
    assert ("Page.navigate", {"url": "https://example.com/next"}) in ws.calls
    assert info["url"] == "https://example.com/next" and info["loading"] is False and "Page" in ws.enabled
    # no load event in time: loading stays true, the caller warns
    info = b.navigate("P-new1", "reload", wait=True, timeout_s=0.01)
    assert ("Page.reload", {}) in ws.calls and info["loading"] is True
    # wait=False returns right after the command
    info = b.navigate("P-new1", "goto", "https://example.com/3", wait=False, timeout_s=1.0)
    assert info["loading"] is True and info["url"] == "https://example.com/3"


def test_chrome_navigate_same_document_and_bfcache_count_as_loaded(chrome_env):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    b.new_tab("", "https://example.com/", restore=False)
    # a fragment / pushState navigation: only navigatedWithinDocument, no load event
    ws.events.append({"method": "Page.navigatedWithinDocument", "params": {"frameId": "F1", "url": "https://example.com/#a"}})
    info = b.navigate("P-new1", "goto", "https://example.com/#a", wait=True, timeout_s=0.05)
    assert info["loading"] is False
    # Page.navigate answering without a loaderId is a same-document navigation too
    ws.same_document = True
    info = b.navigate("P-new1", "goto", "https://example.com/#b", wait=True, timeout_s=0.05)
    assert info["loading"] is False
    ws.same_document = False
    # back from the bfcache: frameNavigated with type BackForwardCacheRestore and no loadEventFired
    ws.history = {"currentIndex": 1, "entries": [{"id": 1, "url": "https://example.com/"}, {"id": 2, "url": "https://example.com/#b"}]}
    ws.events.append({"method": "Page.frameNavigated", "params": {"frame": {"id": "F1", "url": "https://example.com/"}, "type": "BackForwardCacheRestore"}})
    info = b.navigate("P-new1", "back", wait=True, timeout_s=0.05)
    assert info["loading"] is False


def test_chrome_wait_loaded_reads_the_page_after_open(chrome_env):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    b.new_tab("", "https://example.com/", restore=False)
    ws.ready = "loading"
    ws.events.append({"method": "Page.loadEventFired", "params": {}})
    info = b.wait_loaded("P-new1", timeout_s=1.0)
    assert info["loading"] is False and info["title"] == "Example Domain" and "Page" in ws.enabled
    ws.ready = "loading"
    info = b.wait_loaded("P-new1", timeout_s=0.01)
    assert info["loading"] is True


def test_chrome_navigate_back_forward_use_history(chrome_env):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    b.new_tab("", "https://example.com/", restore=False)
    ws.history = {"currentIndex": 1, "entries": [{"id": 1, "url": "https://example.com/"}, {"id": 2, "url": "https://example.com/next"}]}
    ws.url = "https://example.com/next"
    info = b.navigate("P-new1", "back", wait=False, timeout_s=1.0)
    assert ("Page.navigateToHistoryEntry", {"entryId": 1}) in ws.calls and info["url"] == "https://example.com/"
    ws.history["currentIndex"] = 0
    n = len(ws.calls)
    b.navigate("P-new1", "back", wait=False, timeout_s=1.0)  # nothing to go back to: no-op, like Arc's "if possible"
    assert not any(c[0] == "Page.navigateToHistoryEntry" for c in ws.calls[n:])
    b.navigate("P-new1", "forward", wait=False, timeout_s=1.0)
    assert ("Page.navigateToHistoryEntry", {"entryId": 2}) in ws.calls


def test_chrome_close_select_and_quit(chrome_env, fake_http):
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    b.new_tab("", "https://example.com/", restore=False)
    b.select_tab("P-new1")
    assert fake_http.activated == ["P-new1"]
    b.close_tab("P-new1")
    assert ("Target.closeTarget", {"targetId": "P-new1"}) in ws.calls and [p["id"] for p in fake_http.pages] == ["P-home"]
    with pytest.raises(DotBrowserError) as e:
        b.close_tab("P-new1")
    assert e.value.code == "TAB_NOT_FOUND"
    state["running"] = True
    assert b.quit(timeout_s=1.0) is True
    assert ("Browser.close", {}) in ws.calls and state["killed"] == []
    # port closed but the instance is still there: kill it
    state["running"] = True
    fake_http.down = True
    assert b.quit(timeout_s=1.0) is True
    assert len(state["killed"]) == 1 and f"--user-data-dir={profile_dir('chrome')}" in state["killed"][0]


def test_chrome_quit_gives_browser_close_time_before_killing(chrome_env, fake_http):
    """Browser.close succeeded but the process lingers (writing its profile): no SIGTERM inside the grace period."""
    chromium, ws, state = chrome_env
    b = registry.make("chrome")
    state["running"] = True
    ws.on_close = lambda: fake_http.__setattr__("down", True)  # port closes, process stays
    assert b.quit(timeout_s=0.2) is False  # gave up without killing inside the grace period
    assert state["killed"] == [] and state["running"] is True
    chromium.QUIT_GRACE_S = 0.0
    assert b.quit(timeout_s=0.2) is True
    assert len(state["killed"]) == 1


def test_config_browsers_match_registry():
    from dbrowser_lib import config as cfgmod
    assert cfgmod.BROWSERS == {k: c.isolation == "space" for k, c in registry.BROWSERS.items()}


def test_profile_dir_under_browser_home(dot_home):
    assert profile_dir("chrome") == os.path.join(dot_home, "profiles", "chrome")
