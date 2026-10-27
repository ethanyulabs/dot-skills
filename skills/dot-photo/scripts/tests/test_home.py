"""~/.dot/photo: the home directory for outputs, user styles and config."""
import json
import os

import pytest

from dphoto_lib import home


def test_dot_home_defaults_to_user_dot_dir(monkeypatch):
    monkeypatch.delenv("DOT_HOME", raising=False)
    assert home.dot_home() == os.path.join(os.path.expanduser("~"), ".dot")
    assert home.photo_home() == os.path.join(os.path.expanduser("~"), ".dot", "photo")


def test_dot_home_env_override_expands_user(monkeypatch, tmp_path):
    monkeypatch.setenv("DOT_HOME", str(tmp_path / "custom"))
    assert home.photo_home() == str(tmp_path / "custom" / "photo")
    assert home.output_root() == str(tmp_path / "custom" / "photo" / "output")
    assert home.runs_root() == str(tmp_path / "custom" / "photo" / "runs")
    assert home.styles_dir() == str(tmp_path / "custom" / "photo" / "styles")
    assert home.config_path() == str(tmp_path / "custom" / "photo" / "config.json")
    monkeypatch.setenv("DOT_HOME", "~/somewhere")
    assert home.dot_home() == os.path.join(os.path.expanduser("~"), "somewhere")


def test_write_source_merges_paths_for_the_same_content(tmp_path):
    out = tmp_path / "out"
    home.write_source(str(out), "/a/x.jpg", "abc", 10, 1.5)
    home.write_source(str(out), "/b/x.jpg", "abc", 10, 1.5)
    home.write_source(str(out), "/a/x.jpg", "abc", 10, 1.5)
    src = json.load(open(out / "source.json", encoding="utf-8"))
    assert src["paths"] == ["/a/x.jpg", "/b/x.jpg"] and src["sha1"] == "abc" and src["schema"] == "dot-photo/source/1"
    assert src["first_seen"] <= src["last_run"]
    home.write_source(str(out), "/c/y.jpg", "other", 11, 2.0)
    src = json.load(open(out / "source.json", encoding="utf-8"))
    assert src["paths"] == ["/c/y.jpg"] and src["sha1"] == "other"


def test_run_dir_name_gets_a_suffix_when_taken(tmp_path):
    import time
    now = time.strptime("2026-10-27 14:30:12", "%Y-%m-%d %H:%M:%S")
    first = home.new_run_dir("/x/trip", root=str(tmp_path), now=now)
    second = home.new_run_dir("/x/trip", root=str(tmp_path), now=now)
    assert os.path.basename(first) == "20261027-143012-trip" and os.path.basename(second) == "20261027-143012-trip-2"
    assert os.path.isdir(first) and os.path.isdir(second)
