"""Which browsers exist, which one the system opens links with, and how to build an adapter."""
from __future__ import annotations

import os
import plistlib

from .. import DotBrowserError
from .arc import ArcBrowser
from .base import Browser
from .chromium import ChromeBrowser, EdgeBrowser

BROWSERS: dict[str, type[Browser]] = {"arc": ArcBrowser, "chrome": ChromeBrowser, "edge": EdgeBrowser}


def make(key: str, port: int | None = None) -> Browser:
    cls = BROWSERS.get(key)
    if cls is None:
        raise DotBrowserError("BROWSER_UNSUPPORTED", f"no support for browser {key!r}",
                              f"supported: {', '.join(BROWSERS)}; `dbrowser config set browser=<key>` picks the default", 2)
    return cls(port)


def by_bundle_id(bundle_id: str) -> str | None:
    want = (bundle_id or "").lower()
    for key, cls in BROWSERS.items():
        if cls.bundle_id.lower() == want:
            return key
    return None


def installed() -> list[str]:
    return [key for key, cls in BROWSERS.items() if cls().installed()]


def plist_path() -> str:
    return os.path.expanduser("~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist")


def system_default() -> tuple[str | None, str | None]:
    """(bundle id of the system's https handler, our key for it or None). (None, None) when unreadable."""
    try:
        with open(plist_path(), "rb") as fh:
            data = plistlib.load(fh)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None, None
    for h in data.get("LSHandlers", []) if isinstance(data, dict) else []:
        if isinstance(h, dict) and h.get("LSHandlerURLScheme") == "https":
            bid = h.get("LSHandlerRoleAll") or h.get("LSHandlerRoleViewer")
            if isinstance(bid, str):
                return bid, by_bundle_id(bid)
    return None, None
