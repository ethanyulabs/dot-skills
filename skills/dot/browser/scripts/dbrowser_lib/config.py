"""config.json: the user's defaults.

    {"schema": "dot-browser/config/1", "browser": "arc",
     "arc": {"space": "byted", "port": 9222}, "chrome": {"port": 9223}}

`browser` is the default browser; every other top-level key is a browser key holding that browser's
`space` (only for browsers whose isolation is a space) and `port`. Command-line keys are dotted
(`arc.space`, `chrome.port`). A command-line flag always wins over the config; `config set` is the only
writer. A broken file is reported (ok=False) and never overwritten.
"""
from __future__ import annotations

import json
import os

from . import DotBrowserError
from .home import config_path

SCHEMA = "dot-browser/config/1"
# browser key -> whether it has spaces (kept here so config needs no adapter import)
BROWSERS: dict[str, bool] = {"arc": True, "chrome": False, "edge": False}
PORT_RANGE = (1024, 65535)


def browser_keys(key: str) -> tuple[str, str | None]:
    """'browser' -> ('browser', None); 'arc.space' -> ('arc', 'space'). Anything else: CONFIG_BAD_KEY."""
    parts = key.split(".")
    if parts == ["browser"]:
        return "browser", None
    if len(parts) == 2 and parts[0] in BROWSERS and parts[1] in ("space", "port"):
        if parts[1] == "space" and not BROWSERS[parts[0]]:
            raise DotBrowserError("CONFIG_BAD_KEY", f"{parts[0]} has no spaces; '{key}' is not a config key",
                                  "only browsers with space isolation (arc) take a default space", 2)
        return parts[0], parts[1]
    keys = ", ".join(["browser"] + [f"{b}.port" for b in BROWSERS] + [f"{b}.space" for b, has in BROWSERS.items() if has])
    raise DotBrowserError("CONFIG_BAD_KEY", f"unknown config key '{key}'", f"keys: {keys}", 2)


def coerce(key: str, raw):
    """Validates one dotted key with a value (a string from the command line or a JSON value)."""
    top, sub = browser_keys(key)
    if sub is None:
        if not isinstance(raw, str) or raw.strip() not in BROWSERS:
            raise DotBrowserError("CONFIG_BAD_VALUE", f"browser must be one of {', '.join(BROWSERS)}, got {raw!r}", "", 2)
        return raw.strip()
    if sub == "port":
        try:
            port = int(raw)
        except (TypeError, ValueError):
            raise DotBrowserError("CONFIG_BAD_VALUE", f"{key} must be an integer, got {raw!r}", "", 2)
        if isinstance(raw, bool) or not (PORT_RANGE[0] <= port <= PORT_RANGE[1]):
            raise DotBrowserError("CONFIG_BAD_VALUE", f"{key} must be between {PORT_RANGE[0]} and {PORT_RANGE[1]}, got {raw!r}", "", 2)
        return port
    if not isinstance(raw, str) or not raw.strip():
        raise DotBrowserError("CONFIG_BAD_VALUE", f"{key} must be a non-empty name, got {raw!r}", "", 2)
    return raw.strip()


def get_key(cfg: dict, key: str):
    top, sub = browser_keys(key)
    if sub is None:
        return cfg.get("browser")
    return (cfg.get(top) or {}).get(sub)


def set_key(cfg: dict, key: str, value) -> None:
    top, sub = browser_keys(key)
    if sub is None:
        cfg["browser"] = value
    else:
        cfg.setdefault(top, {})[sub] = value


def unset_key(cfg: dict, key: str) -> bool:
    """Removes the key; drops a browser section that became empty. Returns whether something was removed."""
    top, sub = browser_keys(key)
    if sub is None:
        return cfg.pop("browser", None) is not None
    section = cfg.get(top)
    if not isinstance(section, dict) or sub not in section:
        return False
    del section[sub]
    if not section:
        del cfg[top]
    return True


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

    def take(key, value):
        try:
            set_key(cfg, key, coerce(key, value))
        except DotBrowserError as e:
            warnings.append(f"config.json: {e.message}, key ignored")

    for key, value in raw.items():
        if key == "schema":
            continue
        if key == "browser":
            take(key, value)
        elif key in BROWSERS:
            if not isinstance(value, dict):
                warnings.append(f"config.json: '{key}' must be an object, key ignored")
                continue
            for sub, sv in value.items():
                take(f"{key}.{sub}", sv)
        else:
            warnings.append(f"config.json: unknown key '{key}' ignored")
    return cfg, warnings, True


def save_config(cfg: dict) -> str:
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data: dict = {"schema": SCHEMA}
    if cfg.get("browser"):
        data["browser"] = cfg["browser"]
    for b in BROWSERS:
        section = cfg.get(b)
        if isinstance(section, dict) and section:
            data[b] = {k: section[k] for k in ("space", "port") if k in section}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path
