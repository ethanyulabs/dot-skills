"""Arc: spaces and tabs through its AppleScript dictionary (`osa`), pages through CDP. The user runs Arc."""
from __future__ import annotations

import time

from .. import osa
from .base import Browser


class ArcBrowser(Browser):
    key = "arc"
    display_name = "Arc"
    bundle_id = "company.thebrowser.Browser"
    app_paths = osa.ARC_APP_PATHS
    isolation = "space"
    default_port = 9222

    def installed(self) -> bool:
        return osa.arc_app_path() is not None

    def running(self) -> bool:
        return osa.is_arc_running()

    def version(self) -> str | None:
        return osa.arc_version()

    def automation_check(self) -> None:
        osa.arc_version()

    def launch_instruction(self) -> dict:
        port = self.port
        shell = f"osascript -e 'quit app \"Arc\"'; sleep 3; open -a Arc --args --remote-debugging-port={port}"
        zh = (f"Arc 需要以调试端口 {port} 重新启动一次：先退出 Arc（会保留所有标签和空间），再运行 "
              f"`open -a Arc --args --remote-debugging-port={port}`。完成后再跑一次 selftest。"
              "注意：端口只对本机进程开放，但本机任何进程都能借此操作已登录的 Arc；任务结束后正常重启 Arc 即可关闭。")
        return {"shell": shell, "zh": zh}

    def extra_checks(self) -> list[tuple[str, bool, dict | None]]:
        ok = osa.osascript_path() is not None
        return [("osascript", ok, None if ok else {"code": "DEPENDENCY_MISSING", "message": "osascript not found", "hint": "dot browser only runs on macOS"})]

    def not_running_hint(self) -> str:
        return f"启动 Arc（要用页面命令请直接以调试端口启动：open -a Arc --args --remote-debugging-port={self.port}）"

    def raise_tab(self, tab_id: str, target_id: str | None) -> dict:
        """Brings the tab to the front for a screenshot; returns what `restore_after_raise` needs."""
        active = osa.active_ids()
        from .. import cdp_http
        cdp_http.activate(self.port, target_id)
        return active

    def restore_after_raise(self, token: dict, tab_id: str) -> None:
        if token.get("tab") and token["tab"] != tab_id:
            osa.select_tab(token["tab"])

    def list_spaces(self) -> dict:
        return {**osa.list_spaces(), "isolation": "space"}

    def list_tabs(self, space: str) -> list[dict]:
        return osa.list_tabs(space)

    def active_ids(self) -> dict:
        return osa.active_ids()

    def new_tab(self, space: str, url: str, restore: bool = True) -> dict:
        return osa.new_tab(space, url, restore=restore)

    def tab_info(self, tab_id: str) -> dict:
        return osa.tab_info(tab_id)

    def navigate(self, tab_id: str, op: str, url: str | None = None, *, wait: bool = True, timeout_s: float = 10.0) -> dict:
        if op == "goto":
            osa.set_url(tab_id, url)
        elif op == "back":
            osa.go_back(tab_id)
        elif op == "forward":
            osa.go_forward(tab_id)
        elif op == "reload":
            osa.reload(tab_id)
        else:
            raise ValueError(op)
        info = osa.tab_info(tab_id)
        if not wait:
            return info
        deadline = time.monotonic() + timeout_s
        while info["loading"] and time.monotonic() < deadline:
            time.sleep(0.15)
            info = osa.tab_info(tab_id)
        return info

    def close_tab(self, tab_id: str) -> None:
        osa.close_tab(tab_id)

    def select_tab(self, tab_id: str) -> None:
        osa.select_tab(tab_id)

    def focus_space(self, space: str) -> None:
        osa.focus_space(space)
