import json
import os

import pytest
from conftest import read_text

from dbrowser_lib import DotBrowserError
from dbrowser_lib import config as cfgmod
from dbrowser_lib.home import config_path


def test_missing_file_is_empty_and_ok():
    assert cfgmod.load_config() == ({}, [], True)


def test_roundtrip_nested(dot_home):
    cfgmod.save_config({"browser": "arc", "arc": {"space": "byted", "port": 9333}, "chrome": {"port": 9444}})
    cfg, warnings, ok = cfgmod.load_config()
    assert (cfg, warnings, ok) == ({"browser": "arc", "arc": {"space": "byted", "port": 9333}, "chrome": {"port": 9444}}, [], True)
    raw = json.loads(read_text(config_path()))
    assert raw["schema"] == cfgmod.SCHEMA == "dot-browser/config/1"


def test_broken_json_is_refused_not_overwritten():
    os.makedirs(os.path.dirname(config_path()))
    with open(config_path(), "w") as fh:
        fh.write("{not json")
    cfg, warnings, ok = cfgmod.load_config()
    assert cfg == {} and ok is False and warnings
    assert read_text(config_path()) == "{not json"


def test_unknown_keys_and_bad_values_are_dropped_with_warnings():
    os.makedirs(os.path.dirname(config_path()))
    with open(config_path(), "w") as fh:
        json.dump({"schema": cfgmod.SCHEMA, "browser": "safari", "space": "old-top-level", "colour": 1,
                   "arc": {"space": "x", "port": "nine", "zoom": 2}, "chrome": {"space": "no-spaces-here", "port": 9223},
                   "edge": "not-an-object"}, fh)
    cfg, warnings, ok = cfgmod.load_config()
    assert ok is True
    assert cfg == {"arc": {"space": "x"}, "chrome": {"port": 9223}}
    joined = "\n".join(warnings)
    for needle in ("browser", "space", "colour", "arc.port", "arc.zoom", "chrome.space", "edge"):
        assert needle in joined, needle


def test_coerce_dotted_keys():
    assert cfgmod.coerce("browser", "chrome") == "chrome"
    assert cfgmod.coerce("arc.space", " byted ") == "byted"
    assert cfgmod.coerce("edge.port", "9224") == 9224
    for key, value, code in (("browser", "safari", "CONFIG_BAD_VALUE"), ("port", "9222", "CONFIG_BAD_KEY"),
                             ("space", "byted", "CONFIG_BAD_KEY"), ("chrome.space", "x", "CONFIG_BAD_KEY"),
                             ("firefox.port", "9000", "CONFIG_BAD_KEY"), ("arc.port", "80", "CONFIG_BAD_VALUE"),
                             ("arc.port", "abc", "CONFIG_BAD_VALUE"), ("arc.space", "", "CONFIG_BAD_VALUE"),
                             ("arc.zoom", "1", "CONFIG_BAD_KEY"), ("a.b.c", "1", "CONFIG_BAD_KEY")):
        with pytest.raises(DotBrowserError) as e:
            cfgmod.coerce(key, value)
        assert (e.value.code, e.value.exit_code) == (code, 2), key


def test_set_and_unset_nest_and_prune():
    cfg = {}
    cfgmod.set_key(cfg, "arc.space", "byted")
    cfgmod.set_key(cfg, "browser", "arc")
    assert cfg == {"browser": "arc", "arc": {"space": "byted"}}
    assert cfgmod.get_key(cfg, "arc.space") == "byted" and cfgmod.get_key(cfg, "chrome.port") is None
    assert cfgmod.unset_key(cfg, "arc.space") is True and cfg == {"browser": "arc"}
    assert cfgmod.unset_key(cfg, "arc.space") is False
    assert cfgmod.unset_key(cfg, "browser") is True and cfg == {}
