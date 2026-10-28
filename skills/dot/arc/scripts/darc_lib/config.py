"""config.json: the user's defaults. {"schema": "dot-arc/config/1", "space": "byted", "port": 9222}

A command-line flag always wins over the config; `config set` is the only writer. A broken file is
reported (ok=False) and never overwritten.
"""
from __future__ import annotations

import json
import os

from . import DotArcError
from .home import config_path

SCHEMA = "dot-arc/config/1"
KEYS = {"space": str, "port": int}
PORT_RANGE = (1024, 65535)


def load_config() -> tuple[dict, list[str], bool]:
    """Returns (known keys with valid values, warnings, ok). ok is False only when the file is unreadable."""
    path = config_path()
    if not os.path.isfile(path):
        return {}, [], True
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as e:
        return {}, [f"config.json unreadable: {e}"], False
    if not isinstance(raw, dict):
        return {}, ["config.json is not an object"], False
    cfg: dict = {}
    warnings: list[str] = []
    for key, value in raw.items():
        if key == "schema":
            continue
        if key not in KEYS:
            warnings.append(f"config.json: unknown key '{key}' ignored")
            continue
        try:
            cfg[key] = coerce(key, value)
        except DotArcError as e:
            warnings.append(f"config.json: {e.message}, key ignored")
    return cfg, warnings, True


def save_config(cfg: dict) -> str:
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"schema": SCHEMA, **{k: cfg[k] for k in KEYS if k in cfg}}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def coerce(key: str, raw):
    """Validates one key=value pair (raw may be a string from the command line or a JSON value)."""
    if key not in KEYS:
        raise DotArcError("CONFIG_BAD_KEY", f"unknown config key '{key}'", f"keys: {', '.join(KEYS)}", 2)
    if key == "port":
        try:
            port = int(raw)
        except (TypeError, ValueError):
            raise DotArcError("CONFIG_BAD_VALUE", f"port must be an integer, got {raw!r}", "", 2)
        if isinstance(raw, bool) or not (PORT_RANGE[0] <= port <= PORT_RANGE[1]):
            raise DotArcError("CONFIG_BAD_VALUE", f"port must be between {PORT_RANGE[0]} and {PORT_RANGE[1]}, got {raw!r}", "", 2)
        return port
    if key == "space":
        if not isinstance(raw, str) or not raw.strip():
            raise DotArcError("CONFIG_BAD_VALUE", f"space must be a non-empty name, got {raw!r}", "", 2)
        return raw.strip()
    raise DotArcError("CONFIG_BAD_KEY", f"unknown config key '{key}'", "", 2)  # pragma: no cover
