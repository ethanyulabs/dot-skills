import os

from darc_lib import home


def test_dot_home_follows_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DOT_HOME", str(tmp_path / "elsewhere"))
    assert home.dot_home() == str(tmp_path / "elsewhere")
    assert home.arc_home() == os.path.join(str(tmp_path / "elsewhere"), "arc")


def test_paths_under_arc_home(dot_home):
    assert home.config_path() == os.path.join(dot_home, "config.json")
    assert home.sessions_dir() == os.path.join(dot_home, "sessions")
    assert home.session_path("k7q2xd") == os.path.join(dot_home, "sessions", "k7q2xd.json")
    assert home.output_root() == os.path.join(dot_home, "output")
    assert home.output_dir("k7q2xd") == os.path.join(dot_home, "output", "k7q2xd")
    assert home.lock_path() == os.path.join(dot_home, "lock")


def test_default_home_is_under_user_home(monkeypatch):
    monkeypatch.delenv("DOT_HOME")
    assert home.dot_home() == os.path.abspath(os.path.expanduser("~/.dot"))
