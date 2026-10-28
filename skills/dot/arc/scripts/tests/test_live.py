"""Against a real Arc relaunched with --remote-debugging-port. Runs only with DOT_ARC_LIVE=1.

It opens tabs in the space named by DOT_ARC_LIVE_SPACE (default "agent"), never focuses anything,
and closes what it opened. The user's active tab must be the same before and after.
"""
import json
import os
import subprocess
import sys
import threading

import pytest

LIVE = os.environ.get("DOT_ARC_LIVE") == "1"
SPACE = os.environ.get("DOT_ARC_LIVE_SPACE", "agent")
SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(not LIVE, reason="set DOT_ARC_LIVE=1 (and relaunch Arc with --remote-debugging-port) to run")


@pytest.fixture(autouse=True)
def real_home(monkeypatch, tmp_path):
    monkeypatch.setenv("DOT_HOME", str(tmp_path / "dot"))


def darc(*argv, env=None):
    cp = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "darc.py"), *argv], capture_output=True, text=True,
                        env={**os.environ, **(env or {})})
    lines = [l for l in cp.stdout.splitlines() if l.strip()]
    assert len(lines) == 1, cp.stdout + cp.stderr
    return cp.returncode, json.loads(lines[0])


def same_view(before, after):
    """The user's space must be unchanged; the tab too, unless they had none active (Arc just launched)."""
    bs, bt = before.split("|"); as_, at = after.split("|")
    return bs == as_ and (not bt or bt == at)


def active_ids():
    script = ('tell application "Arc"\n set sp to ""\n try\n  set sp to (id of active space of front window) as text\n end try\n'
              ' set tb to ""\n try\n  set tb to (id of active tab of front window) as text\n end try\n return sp & "|" & tb\nend tell')
    return subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True).stdout.strip()


def test_selftest_deep():
    code, j = darc("selftest", "--deep")
    assert code == 0, j
    assert all(j["checks"].values())
    if j["deep"]["pages"]:  # right after a relaunch Arc has no loaded tab to test against
        assert j["deep"]["eval"] == 2 and j["deep"]["ws_ms"] < 2000


def test_open_snapshot_click_screenshot_close(tmp_path):
    before = active_ids()
    code, j = darc("open", "https://example.com/", "--space", SPACE, "--session", "live-main")
    assert code == 0 and j["tab"]["target_id"] and j["focused"] is False, j
    env = {"DOT_ARC_SESSION": "live-main"}
    try:
        assert same_view(before, active_ids())
        code, j = darc("snapshot", env=env)
        assert code == 0 and "- paragraph:" in j["snapshot"] and j["ref_count"] >= 1, j
        link = next(line for line in j["snapshot"].splitlines() if "- link" in line)
        ref = link.split("[ref=")[1].split("]")[0]
        code, j = darc("click", ref, "--snapshot", env=env)
        assert code == 0, j
        code, j = darc("wait", "--url", "*iana.org*", env=env)  # a cold cross-site load may outlast click's own wait
        assert code == 0 and "iana" in j["url"], j
        code, j = darc("extract", "--what", "title", env=env)
        assert code == 0 and j["title"], j
        code, j = darc("back", env=env)
        assert code == 0 and "example.com" in j["url"], j
        code, j = darc("extract", "--what", "title", env=env)
        assert code == 0 and j["title"] == "Example Domain", j
        code, j = darc("eval", "1+1", env=env)
        assert code == 0 and j["result"] == 2
        code, j = darc("screenshot", "--out", str(tmp_path / "shot.png"), env=env)
        assert code in (0, 5), j
        if code == 5:
            assert j["error"]["code"] == "SCREENSHOT_NEEDS_FOREGROUND"
        else:
            assert os.path.getsize(j["path"]) > 1000 and j["width"] > 100
        assert same_view(before, active_ids())
    finally:
        darc("close", env=env)
    code, j = darc("sessions")
    assert code == 0 and not any(s["name"] == "live-main" for s in j["sessions"])
    assert same_view(before, active_ids())


def test_two_sessions_in_parallel():
    before = active_ids()
    results = {}

    def worker(name, url):
        code, j = darc("open", url, "--space", SPACE, "--session", name)
        results[name] = (code, j)
        if code == 0:
            results[name + ".snap"] = darc("snapshot", env={"DOT_ARC_SESSION": name})

    threads = [threading.Thread(target=worker, args=("live-a", "https://example.com/")),
               threading.Thread(target=worker, args=("live-b", "https://example.org/"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        for name in ("live-a", "live-b"):
            code, j = results[name]
            assert code == 0 and j["tab"]["target_id"], j
            code, j = results[name + ".snap"]
            assert code == 0 and "- paragraph:" in j["snapshot"] and j["url"].startswith(("https://example.com", "https://example.org")), j
        assert results["live-a"][1]["tab"]["target_id"] != results["live-b"][1]["tab"]["target_id"]
        assert same_view(before, active_ids())
    finally:
        for name in ("live-a", "live-b"):
            darc("close", "--session", name)
