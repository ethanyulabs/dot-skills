import json
import os

import pytest
from conftest import read_text, write_text

from darc_lib import DotArcError
from darc_lib import config as cfgmod
from darc_lib.home import config_path


def test_missing_file_is_empty_and_ok():
    assert cfgmod.load_config() == ({}, [], True)


def test_roundtrip(dot_home):
    cfgmod.save_config({"space": "byted", "port": 9333})
    cfg, warnings, ok = cfgmod.load_config()
    assert (cfg, warnings, ok) == ({"space": "byted", "port": 9333}, [], True)
    raw = json.loads(read_text(config_path()))
    assert raw["schema"] == cfgmod.SCHEMA


def test_broken_json_is_refused_not_overwritten():
    os.makedirs(os.path.dirname(config_path()))
    with open(config_path(), "w") as fh:
        fh.write("{not json")
    cfg, warnings, ok = cfgmod.load_config()
    assert cfg == {} and ok is False and warnings
    assert read_text(config_path()) == "{not json"


def test_unknown_key_and_bad_type_are_dropped_with_warning():
    os.makedirs(os.path.dirname(config_path()))
    with open(config_path(), "w") as fh:
        json.dump({"schema": cfgmod.SCHEMA, "space": "x", "port": "nine", "colour": 1}, fh)
    cfg, warnings, ok = cfgmod.load_config()
    assert cfg == {"space": "x"} and ok is True
    assert any("port" in w for w in warnings) and any("colour" in w for w in warnings)


def test_coerce():
    assert cfgmod.coerce("space", "byted") == "byted"
    assert cfgmod.coerce("port", "9222") == 9222
    with pytest.raises(DotArcError) as e:
        cfgmod.coerce("port", "80")
    assert e.value.code == "CONFIG_BAD_VALUE" and e.value.exit_code == 2
    with pytest.raises(DotArcError) as e:
        cfgmod.coerce("port", "abc")
    assert e.value.code == "CONFIG_BAD_VALUE"
    with pytest.raises(DotArcError) as e:
        cfgmod.coerce("space", "")
    assert e.value.code == "CONFIG_BAD_VALUE"
    with pytest.raises(DotArcError) as e:
        cfgmod.coerce("colour", "x")
    assert e.value.code == "CONFIG_BAD_KEY"
