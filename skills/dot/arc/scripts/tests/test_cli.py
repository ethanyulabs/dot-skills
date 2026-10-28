import json
import os
import re

import pytest
from conftest import page, read_text, write_text
from darc_lib import DotArcError, __version__, cli

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(capsys, argv):
    code = cli.main(argv)
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) == 1, out
    return code, json.loads(lines[0])


def test_deps_in_sync():
    def deps(name):
        txt = read_text(os.path.join(SCRIPTS, name))
        block = txt.split("# ///")[1]
        return set(re.findall(r'"([^"]+)"', block))
    a, b = deps("darc.py"), deps("run_tests.py")
    assert a <= b and (b - a) == {"pytest>=8"}


def test_version():
    assert __version__ == "0.5.0"


def test_bad_args(capsys):
    code, j = run(capsys, ["no-such-command"])
    assert code == 2 and j["ok"] is False and j["error"]["code"] == "BAD_ARGS"


# ---------------------------------------------------------------- selftest

def test_selftest_green(capsys, arc_env, monkeypatch):
    code, j = run(capsys, ["selftest"])
    assert code == 0 and j["ok"] is True
    assert j["checks"] == {"osascript": True, "arc_installed": True, "arc_running": True, "automation": True, "cdp": True, "websockets": True}
    assert j["port"] == 9222 and j["arc_version"] == "1.152.0" and j["default_space"] is None and j["sessions"] == []
    assert j["arc_home"].endswith("/arc") and j["config_ok"] is True


def test_selftest_cdp_down_exit_4_with_relaunch(capsys, arc_env):
    arc_env[1].down = True
    code, j = run(capsys, ["selftest"])
    assert code == 4 and j["error"]["code"] == "CDP_UNREACHABLE"
    assert "--remote-debugging-port=9222" in j["relaunch"]["shell"]
    assert j["checks"]["cdp"] is False and j["checks"]["automation"] is True


def test_selftest_arc_not_running_never_talks_to_arc(capsys, arc_env):
    arc_env[0].running = False
    code, j = run(capsys, ["selftest"])
    assert code == 4 and j["error"]["code"] == "ARC_NOT_RUNNING" and arc_env[0].calls == []


# ---------------------------------------------------------------- spaces / tabs

def test_spaces_marks_active_default_and_duplicates(capsys, arc_env):
    arc, _ = arc_env
    run(capsys, ["config", "set", "space=byted"])
    arc.spaces.append({"id": "S-dup", "title": "byted", "tabs": []})
    code, j = run(capsys, ["spaces"])
    assert code == 0 and [s["title"] for s in j["spaces"]] == ["agent", "byted", "byted"]
    assert j["spaces"][1]["active"] is True and j["spaces"][1]["tabs"] == 2 and j["default_space"] == "byted"
    assert any("SPACE_TITLE_DUPLICATE" in w for w in j["warnings"])


def test_tabs_uses_flag_then_config(capsys, arc_env):
    code, j = run(capsys, ["tabs", "--space", "agent"])
    assert code == 0 and [t["id"] for t in j["tabs"]] == ["T-a1"] and j["space"] == {"title": "agent", "id": "S-agent", "source": "flag"}
    run(capsys, ["config", "set", "space=byted"])
    code, j = run(capsys, ["tabs"])
    assert code == 0 and j["count"] == 2 and j["space"]["source"] == "config" and j["tabs"][1]["active"] is True
    code, j = run(capsys, ["tabs", "--all"])
    assert code == 0 and j["count"] == 3 and {t["space"] for t in j["tabs"]} == {"agent", "byted"}


def test_tabs_without_space_lists_spaces(capsys, arc_env):
    code, j = run(capsys, ["tabs"])
    assert code == 2 and j["error"]["code"] == "SPACE_REQUIRED" and [s["title"] for s in j["spaces"]] == ["agent", "byted"]


def test_space_not_found(capsys, arc_env):
    code, j = run(capsys, ["tabs", "--space", "nope"])
    assert code == 2 and j["error"]["code"] == "SPACE_NOT_FOUND"


# ---------------------------------------------------------------- open

def test_open_is_silent_and_binds_target(capsys, arc_env, dot_home):
    arc, http = arc_env
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent"])
    assert code == 0 and j["ok"] and re.fullmatch(r"[a-z2-7]{6}", j["session"])
    assert j["export_hint"] == f"export DOT_ARC_SESSION={j['session']}"
    assert j["space"] == {"title": "agent", "id": "S-agent", "source": "flag"}
    assert j["tab"]["arc_id"] == "T-new1" and j["tab"]["target_id"] == "P-T-new1" and j["tab"]["url"] == "https://example.com/"
    assert j["focused"] is False and j["restored"] is False and j["cdp"] is True
    assert arc.active_tab == "T-b2" and arc.active_space == "S-byted"
    assert not any(c[0] in ("focus_space", "select_tab") for c in arc.calls)
    assert ("active_ids",) not in arc.calls  # the user's tab is read and restored inside new_tab's own script
    assert os.path.isfile(j["session_path"]) and j["session_path"].startswith(dot_home)
    sess = json.loads(read_text(j["session_path"]))
    assert sess["tab"]["ws_url"].endswith("/devtools/page/P-T-new1") and sess["space"]["title"] == "agent"


def test_open_restores_the_users_tab_when_arc_switches(capsys, arc_env):
    arc, _ = arc_env
    arc.auto_switch = True
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent"])
    assert code == 0 and j["restored"] is True
    assert arc.active_tab == "T-b2" and arc.active_space == "S-byted"
    assert ("select_tab", "T-b2") in arc.calls


def test_open_focus_switches_space_and_tab(capsys, arc_env):
    arc, _ = arc_env
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent", "--focus"])
    assert code == 0 and j["focused"] is True
    assert ("focus_space", "id:S-agent") in arc.calls and ("select_tab", "T-new1") in arc.calls
    assert arc.active_space == "S-agent" and arc.active_tab == "T-new1"


def test_open_space_from_config_and_flag_override(capsys, arc_env, dot_home):
    run(capsys, ["config", "set", "space=byted"])
    code, j = run(capsys, ["open", "https://example.com/"])
    assert code == 0 and j["space"] == {"title": "byted", "id": "S-byted", "source": "config"}
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent"])
    assert code == 0 and j["space"]["source"] == "flag"
    assert json.loads(read_text(os.path.join(dot_home, "config.json")))["space"] == "byted"


def test_open_without_space_asks_once(capsys, arc_env):
    code, j = run(capsys, ["open", "https://example.com/"])
    assert code == 2 and j["error"]["code"] == "SPACE_REQUIRED"
    assert [s["title"] for s in j["spaces"]] == ["agent", "byted"] and "config set space=" in j["error"]["hint"]
    assert arc_env[0]._n == 0


def test_open_named_session_and_redirect_by_host(capsys, arc_env):
    arc, http = arc_env
    arc.on_new_tab = lambda tab: http.add_later(page("P-R", "https://login.example.com/sso?next=1"), after=http.list_calls + 1)
    code, j = run(capsys, ["open", "https://app.example.com/home", "--space", "agent", "--session", "task-1"])
    assert code == 0 and j["session"] == "task-1" and j["tab"]["target_id"] == "P-R"


def test_open_refuses_to_overwrite_a_session(capsys, arc_env):
    _opened(capsys, "--session", "task-1")
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent", "--session", "task-1"])
    assert code == 2 and j["error"]["code"] == "SESSION_EXISTS" and "close" in j["error"]["hint"]
    assert arc_env[0]._n == 1  # no second tab was created
    code, j = run(capsys, ["attach", "--active", "--session", "task-1"])
    assert code == 2 and j["error"]["code"] == "SESSION_EXISTS"


def test_open_does_not_bind_a_tab_the_user_opened(capsys, arc_env):
    arc, http = arc_env
    arc.on_new_tab = lambda tab: http.add_later(page("P-user", "https://user.example/"), after=http.list_calls + 1)
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent", "--timeout", "300"])
    assert code == 0 and j["tab"]["target_id"] is None and [c["id"] for c in j["candidates"]] == ["P-user"]
    assert any(w.startswith("TARGET_NOT_FOUND") for w in j["warnings"])


def test_open_saves_the_session_even_when_the_load_wait_fails(capsys, arc_env, monkeypatch):
    arc, http = arc_env
    from darc_lib import osa as osamod
    def hang(tab_id):
        raise DotArcError("OSA_TIMEOUT", "osascript did not answer", "", 5)
    monkeypatch.setattr(osamod, "tab_info", hang)
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent"])
    assert code == 0, j
    assert os.path.isfile(j["session_path"]) and any(w.startswith("LOAD_UNKNOWN") for w in j["warnings"])


def test_open_with_cdp_down_still_creates_tab_and_session(capsys, arc_env):
    arc, http = arc_env
    http.down = True
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent"])
    assert code == 0 and j["cdp"] is False and j["tab"]["target_id"] is None and j["tab"]["arc_id"] == "T-new1"
    assert any("TARGET_NOT_FOUND" in w or "CDP_UNREACHABLE" in w for w in j["warnings"])


def test_open_ambiguous_target(capsys, arc_env):
    arc, http = arc_env
    def two(tab):
        http.add_later(page("P-X", "https://example.com/a"), after=http.list_calls + 1)
        http.add_later(page("P-Y", "https://example.com/b"), after=http.list_calls + 1)
    arc.on_new_tab = two
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent"])
    assert code == 0 and j["tab"]["target_id"] is None and {c["id"] for c in j["candidates"]} == {"P-X", "P-Y"}
    assert any(w.startswith("AMBIGUOUS_TARGET") and "--target-id" in w for w in j["warnings"])
    assert os.path.isfile(j["session_path"])  # the tab exists, so the session does too


def test_open_takes_the_lock(capsys, arc_env, monkeypatch):
    from darc_lib import cli as climod
    seen = []
    import darc_lib.lock as lockmod
    real = lockmod.locked
    def spy(path, timeout_s=10.0, poll_s=0.05):
        seen.append(path)
        return real(path, timeout_s, poll_s)
    monkeypatch.setattr(climod, "locked", spy)
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent"])
    assert code == 0 and seen and seen[0].endswith("/arc/lock")


# ---------------------------------------------------------------- attach / goto / close / sessions

def _opened(capsys, *extra):
    code, j = run(capsys, ["open", "https://example.com/", "--space", "agent", *extra])
    assert code == 0
    return j["session"]


def test_attach_active_tab(capsys, arc_env):
    code, j = run(capsys, ["attach", "--active", "--session", "cur"])
    assert code == 0 and j["session"] == "cur" and j["tab"]["arc_id"] == "T-b2" and j["tab"]["target_id"] == "P-b2"
    assert j["space"] == {"title": "byted", "id": "S-byted", "source": "active"}


def test_attach_by_url_ambiguous_target(capsys, arc_env):
    arc, http = arc_env
    http.pages.append(page("P-b2dup", "https://cloud.example/x"))
    code, j = run(capsys, ["attach", "--url", "https://cloud.example/x", "--session", "cur"])
    assert code == 5 and j["error"]["code"] == "AMBIGUOUS_TARGET" and "--target-id" in j["error"]["hint"]
    code, j = run(capsys, ["attach", "--url", "https://cloud.example/x", "--session", "cur", "--target-id", "P-b2dup"])
    assert code == 0 and j["tab"]["target_id"] == "P-b2dup"


def test_goto_back_reload_use_applescript_and_update_session(capsys, arc_env, monkeypatch):
    arc, _ = arc_env
    name = _opened(capsys)
    monkeypatch.setenv("DOT_ARC_SESSION", name)
    code, j = run(capsys, ["goto", "https://example.com/two"])
    assert code == 0 and ("set_url", "T-new1", "https://example.com/two") in arc.calls and j["url"] == "https://example.com/two"
    assert json.loads(read_text(j["session_path"]))["tab"]["url"] == "https://example.com/two"
    for cmd, call in (("back", "go_back"), ("forward", "go_forward"), ("reload", "reload")):
        code, j = run(capsys, [cmd])
        assert code == 0 and (call, "T-new1") in arc.calls
    assert not any(c[0] in ("focus_space", "select_tab") for c in arc.calls)


def test_no_session_without_flag_or_env(capsys, arc_env):
    code, j = run(capsys, ["reload"])
    assert code == 2 and j["error"]["code"] == "NO_SESSION"


def test_close_removes_tab_and_session(capsys, arc_env):
    arc, _ = arc_env
    name = _opened(capsys)
    code, j = run(capsys, ["close", "--session", name])
    assert code == 0 and j["closed"] is True and ("close_tab", "T-new1") in arc.calls and not os.path.exists(j["session_path"])
    name = _opened(capsys)
    code, j = run(capsys, ["close", "--session", name, "--keep-tab"])
    assert code == 0 and j["closed"] is False and not os.path.exists(j["session_path"])


def test_sessions_lists_alive(capsys, arc_env):
    arc, http = arc_env
    a = _opened(capsys)
    b = _opened(capsys)
    http.pages = [p for p in http.pages if p["id"] != "P-T-new1"]
    code, j = run(capsys, ["sessions"])
    assert code == 0 and {s["name"]: s["alive"] for s in j["sessions"]} == {a: False, b: True}
    assert j["sessions"][0]["space"] == "agent" and j["sessions"][0]["url"] == "https://example.com/"


# ---------------------------------------------------------------- config

def test_config_roundtrip_and_errors(capsys, arc_env, dot_home):
    code, j = run(capsys, ["config", "show"])
    assert code == 0 and j["config"] == {} and j["config_path"].startswith(dot_home) and j["sessions"] == []
    code, j = run(capsys, ["config", "set", "space=byted", "port=9333"])
    assert code == 0 and j["config"] == {"space": "byted", "port": 9333}
    code, j = run(capsys, ["config", "set", "port=80"])
    assert code == 2 and j["error"]["code"] == "CONFIG_BAD_VALUE"
    code, j = run(capsys, ["config", "set", "colour=1"])
    assert code == 2 and j["error"]["code"] == "CONFIG_BAD_KEY"
    code, j = run(capsys, ["config", "unset", "port"])
    assert code == 0 and j["config"] == {"space": "byted"}
    write_text(os.path.join(dot_home, "config.json"), "{broken")
    code, j = run(capsys, ["config", "set", "space=x"])
    assert code == 2 and j["error"]["code"] == "CONFIG_INVALID"
    assert read_text(os.path.join(dot_home, "config.json")) == "{broken"
    code, j = run(capsys, ["spaces"])
    assert code == 0 and j["warnings"]


def test_port_flag_overrides_config(capsys, arc_env, monkeypatch):
    arc, http = arc_env
    run(capsys, ["config", "set", "port=9333"])
    code, j = run(capsys, ["selftest"])
    assert code == 4 and j["port"] == 9333
    code, j = run(capsys, ["selftest", "--port", "9222"])
    assert code == 0 and j["port"] == 9222


# ---------------------------------------------------------------- page commands (CDP)

@pytest.fixture
def page_env(capsys, arc_env, fake_cdp, monkeypatch):
    """An open session bound to a live fake target, with DOT_ARC_SESSION exported."""
    arc, http = arc_env
    name = _opened(capsys)
    monkeypatch.setenv("DOT_ARC_SESSION", name)
    return arc, http, fake_cdp, name


def test_snapshot_stores_refs_and_writes_file(capsys, page_env, dot_home):
    arc, http, cdp, name = page_env
    code, j = run(capsys, ["snapshot"])
    assert code == 0 and j["snapshot"].startswith('- heading "Example Domain"') and j["ref_count"] == 7 and j["truncated"] is False
    assert j["url"] == "https://example.com/" and j["title"] == "Example Domain"
    assert j["snapshot_path"] == os.path.join(dot_home, "output", name, "snapshot.txt") and read_text(j["snapshot_path"]) == j["snapshot"]
    sess = json.loads(read_text(j["session_path"]))
    assert sess["snapshot"]["refs"]["e2"]["backend_node_id"] == 8 and sess["snapshot"]["loader_id"] == "L1"
    assert cdp.connected == ["ws://127.0.0.1:9222/devtools/page/P-T-new1"] and cdp.closed
    code, j = run(capsys, ["snapshot", "--max-chars", "40"])
    assert code == 0 and j["truncated"] is True and len(j["snapshot"]) <= 60
    code, j = run(capsys, ["snapshot", "--root", "css=main", "--depth", "1"])
    assert code == 0 and "- textbox" not in j["snapshot"]


def test_click_ref_then_stale(capsys, page_env):
    arc, http, cdp, name = page_env
    run(capsys, ["snapshot"])
    code, j = run(capsys, ["click", "e2"])
    assert code == 0 and j["ref"] == "e2" and j["role"] == "link" and j["name"] == "More information..."
    assert j["navigated"] is True and j["url_after"] == "https://example.com/more"
    assert cdp.mouse[1]["x"] == 60
    code, j = run(capsys, ["click", "e5"])
    assert code == 5 and j["error"]["code"] == "REF_STALE"
    code, j = run(capsys, ["click", "e5", "--snapshot"])
    assert code == 5


def test_click_with_snapshot_returns_fresh_refs(capsys, page_env):
    arc, http, cdp, name = page_env
    code, j = run(capsys, ["click", "button#go", "--snapshot"])
    assert code == 0 and j["navigated"] is False and j["snapshot"].startswith("- heading") and j["ref_count"] == 7
    code, j = run(capsys, ["click", "e5"])
    assert code == 0 and j["name"] == "Go"


def test_click_selectors_and_not_visible(capsys, page_env):
    arc, http, cdp, name = page_env
    for spec in ("css=button#go", "xpath=//h1", "text=Go"):
        code, j = run(capsys, ["click", spec])
        assert code == 0 and j["selector"] == spec
    cdp.hidden.add(13)
    code, j = run(capsys, ["click", "button#go"])
    assert code == 5 and j["error"]["code"] == "NOT_VISIBLE"
    code, j = run(capsys, ["click", "css=nope"])
    assert code == 5 and j["error"]["code"] == "ELEMENT_NOT_FOUND"


def test_fill_press_eval(capsys, page_env, dot_home):
    arc, http, cdp, name = page_env
    code, j = run(capsys, ["fill", "input[name=q]", "hello", "--press", "Enter"])
    assert code == 0 and cdp.inserted == ["hello"] and cdp.keys[-1]["key"] == "Enter"
    code, j = run(capsys, ["press", "Meta+a"])
    assert code == 0 and cdp.keys[-2]["modifiers"] == 4
    code, j = run(capsys, ["eval", "1+1"])
    assert code == 0 and j["result"] == 2
    code, j = run(capsys, ["eval", "throw new Error('boom')"])
    assert code == 5 and j["error"]["code"] == "ACTION_FAILED"
    code, j = run(capsys, ["eval", "big"])
    assert code == 0 and j["result"] is None and j["result_path"].startswith(os.path.join(dot_home, "output", name)) and len(read_text(j["result_path"])) == 5000


def test_screenshot_default_background_and_activate(capsys, page_env, dot_home, monkeypatch):
    arc, http, cdp, name = page_env
    code, j = run(capsys, ["screenshot"])
    assert code == 0 and j["path"].startswith(os.path.join(dot_home, "output", name)) and j["path"].endswith("-screenshot.png")
    assert j["width"] == 1 and j["activated"] is False and http.activated == []
    code, j = run(capsys, ["screenshot", "--out", os.path.join(dot_home, "x.png"), "--full"])
    assert code == 0 and j["path"] == os.path.join(dot_home, "x.png") and os.path.isfile(j["path"])
    cdp.background = True
    code, j = run(capsys, ["screenshot"])
    assert code == 5 and j["error"]["code"] == "SCREENSHOT_NEEDS_FOREGROUND" and http.activated == [] and "--activate" in j["error"]["hint"]
    assert not any(c[0] == "select_tab" for c in arc.calls)
    calls_before = len(arc.calls)
    def activate_then_render(url, timeout):
        if "/json/activate/" in url:
            cdp.background = False
        return http_fetch(url, timeout)
    http_fetch = http.fetch
    from darc_lib import cdp_http as httpmod
    monkeypatch.setattr(httpmod, "_fetch", activate_then_render)
    code, j = run(capsys, ["screenshot", "--activate"])
    assert code == 0 and j["activated"] is True and http.activated == ["P-T-new1"]
    assert ("select_tab", "T-b2") in arc.calls[calls_before:] and arc.active_tab == "T-b2"


def test_extract_and_wait(capsys, page_env, dot_home):
    arc, http, cdp, name = page_env
    code, j = run(capsys, ["extract"])
    assert code == 0 and j["text"].startswith("Example Domain") and j["truncated"] is False
    code, j = run(capsys, ["extract", "--what", "links"])
    assert code == 0 and j["links"][0]["text"] == "More information..."
    code, j = run(capsys, ["extract", "--what", "html", "--out", os.path.join(dot_home, "page.html")])
    assert code == 0 and j["path"] == os.path.join(dot_home, "page.html") and read_text(j["path"]).startswith("<html>")
    code, j = run(capsys, ["wait", "--url", "https://example.com/*"])
    assert code == 0 and j["url"] == "https://example.com/"
    code, j = run(capsys, ["wait", "--url", "https://nope/*", "--timeout", "300"])
    assert code == 5 and j["error"]["code"] == "WAIT_TIMEOUT"


def test_rebind_after_target_gone(capsys, page_env, monkeypatch):
    arc, http, cdp, name = page_env
    http.pages = [p for p in http.pages if p["id"] != "P-T-new1"]
    from darc_lib import osa as osamod, cli as climod
    import darc_lib.lock as lockmod
    locks = []
    real = lockmod.locked
    def spy(path, timeout_s=10.0, poll_s=0.05):
        locks.append(path)
        return real(path, timeout_s, poll_s)
    monkeypatch.setattr(climod, "locked", spy)
    monkeypatch.setattr(osamod, "reload", lambda tab_id: (arc.calls.append(("reload", tab_id)), http.add_later(page("P-woke", "https://example.com/"), after=http.list_calls + 1)))
    code, j = run(capsys, ["snapshot"])
    assert code == 0 and j["rebound"] is True and ("reload", "T-new1") in arc.calls
    assert locks and locks[0].endswith("/arc/lock")  # the rebind takes the same lock as open
    assert not any(c[0] == "select_tab" for c in arc.calls) and cdp.connected[-1].endswith("/P-woke")
    assert json.loads(read_text(j["session_path"]))["tab"]["target_id"] == "P-woke"


def test_target_gone_and_tab_gone(capsys, page_env):
    arc, http, cdp, name = page_env
    http.pages = [p for p in http.pages if p["id"] != "P-T-new1"]
    code, j = run(capsys, ["snapshot", "--timeout", "200"])
    assert code == 5 and j["error"]["code"] == "TARGET_GONE"
    arc.close_tab("T-new1")
    code, j = run(capsys, ["snapshot"])
    assert code == 5 and j["error"]["code"] == "TAB_GONE"


def test_rebind_rejects_a_target_with_another_url(capsys, page_env, monkeypatch):
    arc, http, cdp, name = page_env
    http.pages = [p for p in http.pages if p["id"] != "P-T-new1"]
    from darc_lib import osa as osamod
    monkeypatch.setattr(osamod, "reload", lambda tab_id: http.add_later(page("P-other", "https://user.example/"), after=http.list_calls + 1))
    code, j = run(capsys, ["snapshot", "--timeout", "200"])
    assert code == 5 and j["error"]["code"] == "TARGET_GONE"


def test_explicit_port_beats_session_port(capsys, page_env):
    code, j = run(capsys, ["snapshot", "--port", "9333"])
    assert code == 4 and j["error"]["code"] == "CDP_UNREACHABLE" and "9333" in j["error"]["message"]


def test_extract_root_selector_and_ref(capsys, page_env):
    arc, http, cdp, name = page_env
    code, j = run(capsys, ["extract", "--root", "css=button#go"])
    assert code == 0 and j["text"] == "Go"
    run(capsys, ["snapshot"])
    code, j = run(capsys, ["extract", "--root", "e5"])
    assert code == 0 and j["text"] == "Go"
    code, j = run(capsys, ["extract", "--root", "css=nope"])
    assert code == 5 and j["error"]["code"] == "ELEMENT_NOT_FOUND"


def test_page_command_with_cdp_down(capsys, page_env):
    arc, http, cdp, name = page_env
    http.down = True
    code, j = run(capsys, ["snapshot"])
    assert code == 4 and j["error"]["code"] == "CDP_UNREACHABLE"


def test_selftest_deep_reports_ws(capsys, arc_env, fake_cdp):
    code, j = run(capsys, ["selftest", "--deep"])
    assert code == 0 and j["deep"]["ws_ms"] >= 0 and j["deep"]["target_id"] == "P-b2" and j["deep"]["eval"] == 2
