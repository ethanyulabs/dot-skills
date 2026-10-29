import json
import os
import re

import pytest
from conftest import read_text, write_text

from dbrowser_lib import DotBrowserError
from dbrowser_lib import session as sess
from dbrowser_lib.home import session_path


def make(name="k7q2xd", **kw):
    s = sess.create(name=name, port=9222, browser="arc", space={"title": "byted", "id": "S1", "source": "flag"},
                    tab={"tab_id": "T1", "target_id": "A", "ws_url": "ws://x", "url": "https://a", "title": "A"})
    s.update(kw)
    return s


def test_create_save_load_roundtrip(dot_home):
    s = make()
    path = sess.save(s)
    assert path == session_path("k7q2xd") and os.path.isfile(path)
    loaded = sess.load("k7q2xd")
    assert loaded["schema"] == sess.SCHEMA and loaded["tab"]["target_id"] == "A" and loaded["created"]
    assert not os.path.exists(path + ".tmp")


def test_new_name_is_short_unique_and_valid(dot_home):
    names = {sess.new_name() for _ in range(50)}
    assert len(names) == 50 and all(re.fullmatch(r"[a-z2-7]{6}", n) for n in names)
    sess.save(make("abcdef"))
    taken = sess.new_name
    assert all(n != "abcdef" for n in (taken() for _ in range(5)))


def test_name_validation():
    for bad in ("", "a/b", "x" * 41, "..", "sp ace"):
        with pytest.raises(DotBrowserError) as e:
            sess.check_name(bad)
        assert e.value.code == "SESSION_INVALID" and e.value.exit_code == 2
    assert sess.check_name("my-task.1") == "my-task.1"


def test_load_missing_and_broken(dot_home):
    with pytest.raises(DotBrowserError) as e:
        sess.load("nope")
    assert e.value.code == "NO_SESSION" and e.value.exit_code == 2
    os.makedirs(os.path.dirname(session_path("bad")), exist_ok=True)
    write_text(session_path("bad"), "{")
    with pytest.raises(DotBrowserError) as e:
        sess.load("bad")
    assert e.value.code == "SESSION_INVALID"


def test_resolve_name_flag_then_env_then_error(monkeypatch):
    assert sess.resolve_name("flag1", {"DOT_BROWSER_SESSION": "env1"}) == "flag1"
    assert sess.resolve_name(None, {"DOT_BROWSER_SESSION": "env1"}) == "env1"
    with pytest.raises(DotBrowserError) as e:
        sess.resolve_name(None, {})
    assert e.value.code == "NO_SESSION" and "DOT_BROWSER_SESSION" in e.value.hint


def test_list_delete_touch(dot_home):
    a = make("aaaaaa"); a["last_used"] = "2026-01-01T00:00:00"; sess.save(a)
    b = make("bbbbbb"); b["last_used"] = "2026-02-01T00:00:00"; sess.save(b)
    assert [s["name"] for s in sess.list_sessions()] == ["bbbbbb", "aaaaaa"]
    sess.touch(a)
    assert a["last_used"] > b["last_used"]
    assert sess.delete("aaaaaa") is True and sess.delete("aaaaaa") is False
    assert [s["name"] for s in sess.list_sessions()] == ["bbbbbb"]


def test_set_refs(dot_home):
    s = make()
    sess.set_refs(s, url="https://a", root="body", loader_id="L1", refs={"e1": {"backend_node_id": 5, "role": "link", "name": "x"}})
    assert s["snapshot"]["loader_id"] == "L1" and s["snapshot"]["refs"]["e1"]["backend_node_id"] == 5 and s["snapshot"]["taken"]
