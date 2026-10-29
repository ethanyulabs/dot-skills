"""The user's home for this subcommand: $DOT_HOME/browser (DOT_HOME defaults to ~/.dot).

    config.json              default space and port
    lock                     flock taken while `open` creates and binds a tab
    sessions/<name>.json     one file per session (space, tab, CDP target, last snapshot refs)
    output/<session>/        screenshots, snapshot.txt, extract-*.txt, eval-*.txt
    profiles/<browser>/      user-data-dir of the browsers dot launches itself (chrome, edge)

Every path is a function that reads the environment on each call, so tests can point DOT_HOME anywhere.
"""
from __future__ import annotations

import os

SKILL_NAME = "browser"


def dot_home() -> str:
    return os.path.abspath(os.path.expanduser(os.environ.get("DOT_HOME") or os.path.join("~", ".dot")))


def browser_home() -> str:
    return os.path.join(dot_home(), SKILL_NAME)


def config_path() -> str:
    return os.path.join(browser_home(), "config.json")


def lock_path() -> str:
    return os.path.join(browser_home(), "lock")


def sessions_dir() -> str:
    return os.path.join(browser_home(), "sessions")


def session_path(name: str) -> str:
    return os.path.join(sessions_dir(), f"{name}.json")


def output_root() -> str:
    return os.path.join(browser_home(), "output")


def output_dir(session: str) -> str:
    return os.path.join(output_root(), session)


def profiles_root() -> str:
    return os.path.join(browser_home(), "profiles")


def profile_dir(browser_key: str) -> str:
    """The dedicated user-data-dir of a browser dot launches itself (chrome, edge)."""
    return os.path.join(profiles_root(), browser_key)
