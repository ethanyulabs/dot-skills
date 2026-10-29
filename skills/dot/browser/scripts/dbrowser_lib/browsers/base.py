"""The interface between cli.py and one browser.

Two isolation models:
- "space": the browser has spaces (Arc). The user drives the browser themselves; dot opens tabs in a named
  space and never changes what the user is looking at.
- "instance": dot launches its own instance of the browser with a dedicated profile (chrome, edge). There
  are no spaces; every session gets its own window; `running()` means that instance, not the user's own.
"""
from __future__ import annotations

from .. import DotBrowserError


class Browser:
    key = ""
    display_name = ""
    bundle_id = ""
    app_paths: tuple[str, ...] = ()
    isolation = ""          # "space" | "instance"
    default_port = 9222

    def __init__(self, port: int | None = None):
        self.port = int(port or self.default_port)

    # -- environment
    def installed(self) -> bool:
        raise NotImplementedError

    def running(self) -> bool:
        raise NotImplementedError

    def version(self) -> str | None:
        raise NotImplementedError

    def automation_check(self) -> None:
        """Raises when macOS refuses Apple events to this browser; a no-op for browsers driven over CDP only."""

    def extra_checks(self) -> list[tuple[str, bool, dict | None]]:
        """Browser-specific selftest entries: (name, ok, problem or None)."""
        return []

    def not_running_hint(self) -> str:
        return self.launch_instruction()["zh"]

    def cdp_reachable(self) -> bool:
        from .. import DotBrowserError as _E, cdp_http
        try:
            cdp_http.version(self.port)
            return True
        except _E:
            return False

    def raise_tab(self, tab_id: str, target_id: str | None) -> object:
        """Brings the tab to the front (screenshot --activate); returns a token for restore_after_raise."""
        raise NotImplementedError

    def restore_after_raise(self, token: object, tab_id: str) -> None:
        raise NotImplementedError

    def launch_instruction(self) -> dict:
        """{"shell": one command line, "zh": what to tell the user} to get this browser up with the DevTools port."""
        raise NotImplementedError

    def launch(self, timeout_s: float = 10.0) -> None:
        raise DotBrowserError("BAD_ARGS", f"{self.display_name} is started by the user, not by dot", self.launch_instruction()["zh"], 2)

    def quit(self, timeout_s: float = 10.0) -> None:
        raise DotBrowserError("BAD_ARGS", f"dot does not quit the user's own {self.display_name}", "", 2)

    # -- spaces and tabs
    def list_spaces(self) -> dict:
        raise NotImplementedError

    def list_tabs(self, space: str) -> list[dict]:
        raise NotImplementedError

    def active_ids(self) -> dict:
        raise NotImplementedError

    def new_tab(self, space: str, url: str, restore: bool = True) -> dict:
        """{"id", "switched", "new_ids"}; `id` is the browser's own tab id (a DevTools target id on chromium)."""
        raise NotImplementedError

    def tab_info(self, tab_id: str) -> dict:
        """{"id", "url", "title", "loading"}; TAB_NOT_FOUND (exit 2) when the tab is gone."""
        raise NotImplementedError

    def navigate(self, tab_id: str, op: str, url: str | None = None, *, wait: bool = True, timeout_s: float = 10.0) -> dict:
        """op: goto | back | forward | reload. Returns tab_info after the navigation; `loading` is True when
        the page had not finished loading within timeout_s (or wait was False)."""
        raise NotImplementedError

    def wait_loaded(self, tab_id: str, timeout_s: float = 10.0) -> dict:
        """After `open`: tab_info once the page finished loading (or `loading: True` after timeout_s)."""
        return self.tab_info(tab_id)

    def close_tab(self, tab_id: str) -> None:
        raise NotImplementedError

    def select_tab(self, tab_id: str) -> None:
        raise NotImplementedError

    def focus_space(self, space: str) -> None:
        raise NotImplementedError
