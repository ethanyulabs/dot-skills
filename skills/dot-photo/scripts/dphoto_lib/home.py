"""The user's home for this skill: $DOT_HOME/photo (DOT_HOME defaults to ~/.dot).

    config.json              user defaults per section (portrait, landscape, export, run)
    styles/<name>.json       user styles, resolvable by name
    output/<stem>-<hash8>/   one directory per photo content (sha1 of the file), plus source.json
    runs/<stamp>-<folder>/   batch.json, contact*.jpg, log.txt of one folder run

Every path is a function that reads the environment on each call, so tests can point DOT_HOME
anywhere. This module must stay free of numpy / cv2: it runs before argument parsing.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time

SKILL_NAME = "photo"
SOURCE_SCHEMA = "dot-photo/source/1"


def dot_home() -> str:
    return os.path.abspath(os.path.expanduser(os.environ.get("DOT_HOME") or os.path.join("~", ".dot")))


def photo_home() -> str:
    return os.path.join(dot_home(), SKILL_NAME)


def output_root() -> str:
    return os.path.join(photo_home(), "output")


def runs_root() -> str:
    return os.path.join(photo_home(), "runs")


def styles_dir() -> str:
    return os.path.join(photo_home(), "styles")


def config_path() -> str:
    return os.path.join(photo_home(), "config.json")


def output_dir(stem: str, sha1: str, home: str | None = None) -> str:
    """<home>/output/<stem>-<first 8 hex of sha1>; home defaults to photo_home()."""
    root = os.path.join(home, "output") if home else output_root()
    return os.path.join(root, f"{stem}-{sha1[:8]}")


def write_source(out_dir: str, path: str, sha1: str, size: int, mtime: float) -> str:
    """source.json: which file(s) this output directory was made from. Same content merges paths;
    different content replaces the record."""
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, "source.json")
    now = _dt.datetime.now().isoformat(timespec="seconds")
    rec = None
    if os.path.isfile(target):
        try:
            with open(target, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            rec = None
    if not rec or rec.get("sha1") != sha1:
        rec = {"schema": SOURCE_SCHEMA, "sha1": sha1, "paths": [], "first_seen": now}
    path = os.path.abspath(path)
    if path not in rec["paths"]:
        rec["paths"].append(path)
    rec.update({"size": size, "mtime": mtime,
                "mtime_iso": _dt.datetime.fromtimestamp(mtime).isoformat(timespec="seconds"), "last_run": now})
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
    return target


def run_dir_name(folder: str, now: time.struct_time | None = None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", now or time.localtime())
    base = os.path.basename(os.path.abspath(folder).rstrip(os.sep)) or "root"
    return f"{stamp}-{base}"


def new_run_dir(folder: str, *, root: str | None = None, now: time.struct_time | None = None) -> str:
    """Creates and returns a fresh runs/<stamp>-<folder>[-N]/ directory; never reuses one."""
    root = root or runs_root()
    name = run_dir_name(folder, now)
    n = 1
    while True:
        cand = os.path.join(root, name if n == 1 else f"{name}-{n}")
        try:
            os.makedirs(cand, exist_ok=False)
            return cand
        except FileExistsError:
            n += 1
