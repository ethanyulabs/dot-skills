import re
import subprocess

import pytest

from darc_lib import DotArcError
from darc_lib import osa

US, RS = "\x1f", "\x1e"


def test_quote_escapes_backslash_and_quotes():
    assert osa.quote('a"b\\c') == '"a\\"b\\\\c"'


def test_space_selector_by_title_and_id():
    assert 'whose title is "byted"' in osa.space_selector("byted")
    assert 'whose id is "ABC-1"' in osa.space_selector("id:ABC-1")
    assert "front window" in osa.space_selector("byted")


def _capture(monkeypatch, output=""):
    seen = []

    def fake_run(script, timeout=15.0, not_found=None):
        seen.append(script)
        return output
    monkeypatch.setattr(osa, "run", fake_run)
    return seen


def test_builders_never_store_object_specifiers(monkeypatch):
    seen = _capture(monkeypatch, output=f"a{US}b{RS}x{US}y{RS}a{RS}1{RS}1{US}2")
    osa.list_spaces()
    osa.list_tabs("byted")
    osa.active_ids()
    osa.new_tab("byted", "https://example.com", restore=True)
    osa.focus_space("byted")
    osa.select_tab("T1")
    osa.tab_info("T1")
    osa.set_url("T1", "https://example.org")
    osa.go_back("T1"); osa.go_forward("T1"); osa.reload("T1"); osa.close_tab("T1")
    osa.arc_version()
    assert len(seen) == 13
    for script in seen:
        assert not re.search(r"set \w+ to \((first|every|some) (space|tab)", script), script
        assert "front window" in script or "version" in script


def test_list_spaces_parses_bulk_output(monkeypatch):
    out = f"A{US}B{US}C{RS}agent{US}byted{US}a, b{RS}B{RS}2{RS}3{US}45{US}0"
    _capture(monkeypatch, out)
    r = osa.list_spaces()
    assert r["windows"] == 2
    assert r["spaces"] == [
        {"id": "A", "title": "agent", "active": False, "tabs": 3},
        {"id": "B", "title": "byted", "active": True, "tabs": 45},
        {"id": "C", "title": "a, b", "active": False, "tabs": 0},
    ]


def test_list_spaces_empty_and_no_window(monkeypatch):
    _capture(monkeypatch, f"{RS}{RS}{RS}1{RS}")
    assert osa.list_spaces()["spaces"] == []
    _capture(monkeypatch, "NOWINDOW")
    with pytest.raises(DotArcError) as e:
        osa.list_spaces()
    assert e.value.code == "NO_WINDOW" and e.value.exit_code == 2


def test_list_tabs_parses(monkeypatch):
    out = f"T1{US}T2{RS}Home{US}Doc, v2{RS}https://a{US}https://b{RS}pinned{US}unpinned{RS}T2\n"
    _capture(monkeypatch, out)
    r = osa.list_tabs("byted")
    assert r == [{"id": "T1", "title": "Home", "url": "https://a", "location": "pinned", "active": False},
                 {"id": "T2", "title": "Doc, v2", "url": "https://b", "location": "unpinned", "active": True}]


def test_new_tab_diffs_ids_and_restores_the_users_tab(monkeypatch):
    seen = _capture(monkeypatch, f"NEW-ID{RS}true\n")
    assert osa.new_tab("byted", 'https://e.com/?q="x"', restore=True) == {"id": "NEW-ID", "switched": True, "new_ids": ["NEW-ID"]}
    script = seen[0]
    assert 'make new tab with properties {URL:"https://e.com/?q=\\"x\\""}' in script
    assert 'whose title is "byted"' in script
    # the user's active tab is read inside the same script, right before the create: no window for a race
    assert script.index("set keepId to id of active tab of front window") < script.index("make new tab")
    assert "select (first tab of front window whose id is keepId)" in script
    assert "id of (make new tab" not in script  # -1700 on a real Arc
    seen = _capture(monkeypatch, f"A{US}B{RS}false")
    r = osa.new_tab("byted", "https://e.com", restore=False)
    assert r == {"id": "A", "switched": False, "new_ids": ["A", "B"]}
    assert "select (first tab" not in seen[0]
    _capture(monkeypatch, f"{RS}false")
    with pytest.raises(DotArcError) as e:
        osa.new_tab("byted", "https://e.com")
    assert e.value.code == "OSA_ERROR"


def test_tab_info_parses(monkeypatch):
    _capture(monkeypatch, f"T1{US}Title{US}https://a{US}false")
    assert osa.tab_info("T1") == {"id": "T1", "title": "Title", "url": "https://a", "loading": False}


def test_run_maps_osascript_errors(monkeypatch):
    def fake(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="execution error: Arc got an error: Invalid index. (-1719)\n")
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(DotArcError) as e:
        osa.run("x", not_found="SPACE_NOT_FOUND")
    assert e.value.code == "SPACE_NOT_FOUND" and e.value.exit_code == 2

    def denied(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Not authorized to send Apple events to Arc. (-1743)\n")
    monkeypatch.setattr(subprocess, "run", denied)
    with pytest.raises(DotArcError) as e:
        osa.run("x")
    assert e.value.code == "AUTOMATION_DENIED" and e.value.exit_code == 4

    def timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(DotArcError) as e:
        osa.run("x", timeout=1)
    assert e.value.code == "OSA_TIMEOUT"

    def missing(cmd, **kw):
        raise FileNotFoundError
    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(DotArcError) as e:
        osa.run("x")
    assert e.value.code == "DEPENDENCY_MISSING" and e.value.exit_code == 4

    def other(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="syntax error (-2741)\n")
    monkeypatch.setattr(subprocess, "run", other)
    with pytest.raises(DotArcError) as e:
        osa.run("x")
    assert e.value.code == "OSA_ERROR" and "-2741" in e.value.message

    def no_object(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Arc got an error: Can't get active tab of window 1. (-1728)\n")
    monkeypatch.setattr(subprocess, "run", no_object)
    monkeypatch.setattr(osa, "arc_app_path", lambda: "/Applications/Arc.app")
    with pytest.raises(DotArcError) as e:
        osa.run("x", not_found="TAB_NOT_FOUND")
    assert e.value.code == "TAB_NOT_FOUND"  # -1728 is "no such object", not "Arc missing", while Arc is installed
    with pytest.raises(DotArcError) as e:
        osa.run("x")
    assert e.value.code == "OSA_ERROR"
    monkeypatch.setattr(osa, "arc_app_path", lambda: None)
    with pytest.raises(DotArcError) as e:
        osa.run("x")
    assert e.value.code == "ARC_NOT_INSTALLED"


def test_run_passes_script_on_stdin_and_strips(monkeypatch):
    def fake(cmd, **kw):
        assert cmd[0] == "osascript" and kw["input"] == "tell application \"Arc\" to get version"
        return subprocess.CompletedProcess(cmd, 0, stdout="1.152.0\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    assert osa.run('tell application "Arc" to get version') == "1.152.0"


def test_is_arc_running(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="123\n", stderr=""))
    assert osa.is_arc_running() is True
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=""))
    assert osa.is_arc_running() is False
