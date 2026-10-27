"""config.json in the home: user defaults per command section, applied below the command line.

    {"schema": "dot-photo/config/1",
     "defaults": {"portrait": {"skin-strength": 0.4, "blemish": "off"},
                  "landscape": {"dehaze": 0.25},
                  "export": {"paper": "5x7", "for": "print,web"},
                  "run": {"style": "my-look"}}}

Keys are the command-line option names. Precedence: explicit option > config.json > built-in default.
`run` takes the portrait, landscape and export sections (without their style/strength) and then its own.
Common options (--out, --quiet, ...) are never taken from the config: argparse shares their Action objects
between sub-commands, so a default set on one would leak into every other.
"""
from __future__ import annotations

import argparse
import json
import os

from . import DotPhotoError
from .home import config_path

CONFIG_SCHEMA = "dot-photo/config/1"
SECTIONS = ("portrait", "landscape", "export", "run")
COMMON_KEYS = {"out", "quiet", "debug", "seed", "max-analyze-px", "max-process-px", "no-recursive",
               "skip-existing"}
# which sections feed which command, in order (later sections win on the same dest)
TARGETS = {"portrait": ["portrait"], "landscape": ["landscape"], "export": ["export"],
           "run": ["portrait", "landscape", "export", "run"]}
_TRUE, _FALSE = {"1", "true", "on", "yes"}, {"0", "false", "off", "no"}


def empty_config() -> dict:
    return {"schema": CONFIG_SCHEMA, "defaults": {}}


def load_config() -> tuple[dict, list[str], bool]:
    """(config, warnings, ok). A missing file is an empty config; a broken one is empty with a warning."""
    path = config_path()
    if not os.path.isfile(path):
        return empty_config(), [], True
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict) or not isinstance(cfg.get("defaults", {}), dict):
            raise ValueError("top level must be an object with a 'defaults' object")
    except (OSError, ValueError) as e:
        return empty_config(), [f"config.json ignored: {path}: {e}"], False
    cfg.setdefault("schema", CONFIG_SCHEMA)
    cfg.setdefault("defaults", {})
    return cfg, [], True


def save_config(cfg: dict) -> str:
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    return path


def section_actions(section: str, *, for_run: bool = False) -> dict[str, argparse.Action]:
    """option name (without dashes) -> argparse Action for one section. for_run drops the
    style/strength options that run defines itself."""
    from . import cli
    tmp = argparse.ArgumentParser(add_help=False)
    if section == "portrait":
        cli._add_portrait_args(tmp, with_style=not for_run)
    elif section == "landscape":
        cli._add_landscape_args(tmp, with_style=not for_run)
    elif section == "export":
        cli._add_export_args(tmp)
    elif section == "run":
        cli._add_run_args(tmp)
    else:
        raise DotPhotoError("CONFIG_BAD_SECTION", f"unknown section '{section}'",
                            "sections: " + ", ".join(SECTIONS), 2)
    return {opt.lstrip("-"): act for act in tmp._actions for opt in act.option_strings}


def coerce(section: str, key: str, raw):
    """Turns a config value into what the option's Action expects; raises CONFIG_BAD_KEY / CONFIG_BAD_VALUE."""
    actions = section_actions(section)
    if key in COMMON_KEYS or key not in actions:
        raise DotPhotoError("CONFIG_BAD_KEY", f"'{key}' is not an option of {section}",
                            "options: " + ", ".join(sorted(k for k in actions if k not in COMMON_KEYS)), 2)
    act = actions[key]
    if isinstance(act, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise DotPhotoError("CONFIG_BAD_VALUE", f"{section}.{key}: expected true/false, got {raw!r}", "", 2)
    value = raw
    if act.type is not None and not isinstance(raw, bool):
        try:
            value = act.type(raw) if isinstance(raw, str) else act.type(raw)
        except (TypeError, ValueError):
            raise DotPhotoError("CONFIG_BAD_VALUE", f"{section}.{key}: {raw!r} is not a {act.type.__name__}", "", 2)
    elif act.type is None and not isinstance(raw, str):
        value = str(raw).lower() if isinstance(raw, bool) else str(raw)
    if act.choices is not None and value not in act.choices:
        raise DotPhotoError("CONFIG_BAD_VALUE", f"{section}.{key}: {raw!r} is not one of {list(act.choices)}", "", 2)
    return value


def apply_config(subparsers: dict[str, argparse.ArgumentParser], cfg: dict, warnings: list[str]) -> list[str]:
    """set_defaults() on every target parser from cfg['defaults']; returns the warnings (unknown
    sections/keys, bad values). Each parser also gets config_applied and config_warnings."""
    warnings = list(warnings)
    valid: dict[str, dict] = {}
    for section, values in (cfg.get("defaults") or {}).items():
        if section not in SECTIONS or not isinstance(values, dict):
            warnings.append(f"config.json: unknown section '{section}' ignored")
            continue
        for key, raw in values.items():
            try:
                valid.setdefault(section, {})[key] = coerce(section, key, raw)
            except DotPhotoError as e:
                warnings.append(f"config.json: {section}.{key} ignored: {e.message}")
    for cmd, parser in subparsers.items():
        applied: dict[str, dict] = {}
        for section in TARGETS.get(cmd, []):
            if section not in valid:
                continue
            actions = section_actions(section, for_run=(cmd == "run" and section != "run"))
            dests = {k: actions[k].dest for k in valid[section] if k in actions}
            if dests:
                parser.set_defaults(**{dests[k]: valid[section][k] for k in dests})
                applied[section] = {k: valid[section][k] for k in dests}
        parser.set_defaults(config_applied=applied, config_warnings=warnings)
    return warnings
