"""Chrome and Edge: a dedicated instance that dot launches itself, driven entirely over CDP.

Why a dedicated instance: since Chrome 136 `--remote-debugging-port` is refused on the default profile,
so the user's everyday profile cannot be attached to; dot keeps its own user-data-dir under
~/.dot/browser/profiles/<key>, where the user logs in once. Why no AppleScript: two instances share one
bundle id, so `tell application "Google Chrome"` would address an arbitrary one.

Every session gets its own window (`Target.createTarget newWindow`), so its tab is the window's foreground
tab and renders for screenshots; `--disable-backgrounding-occluded-windows` keeps it rendering when the
window is covered. Creating a window may raise the browser: `new_tab` puts the user's app back.
"""
from __future__ import annotations

import os
import subprocess
import time

from .. import DotBrowserError, cdp_http, cdp_ws
from ..home import lock_path, profile_dir
from ..lock import locked
from . import frontmost
from .base import Browser

LAUNCH_SETTLE_S = 1.5   # how long after the port opens a first window may still come to the front
WINDOW_SETTLE_S = 0.3   # same for a new window on a running instance
QUIT_GRACE_S = 3.0      # how long Browser.close gets to end the process before pkill
LAUNCH_FLAGS = ("--no-first-run", "--no-default-browser-check",
                "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding")


def _pids(pattern: str) -> set[int]:
    """Pids of every process whose command line contains the pattern (dot's instance and its helpers)."""
    try:
        cp = subprocess.run(["pgrep", "-f", "--", pattern], capture_output=True, text=True)
    except FileNotFoundError:  # pragma: no cover
        return set()
    return {int(x) for x in cp.stdout.split() if x.isdigit()}


def _pkill(pattern: str) -> None:
    subprocess.run(["pkill", "-f", "--", pattern], capture_output=True, text=True)


def _spawn(cmd: list[str]) -> None:
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ChromiumBrowser(Browser):
    isolation = "instance"
    app_name = ""   # what `open -a` takes

    # -- environment
    @property
    def profile(self) -> str:
        return profile_dir(self.key)

    @property
    def _pattern(self) -> str:
        return f"--user-data-dir={self.profile}"

    def installed(self) -> bool:
        return any(os.path.isdir(os.path.expanduser(p)) for p in self.app_paths)

    def running(self) -> bool:
        return bool(_pids(self._pattern))

    def extra_checks(self) -> list[tuple[str, bool, dict | None]]:
        ok = frontmost.current_pid() is not None
        return [("system_events", ok, None if ok else {
            "code": "AUTOMATION_DENIED", "message": "macOS did not let this process ask System Events which app is in front",
            "hint": "系统设置 → 隐私与安全性 → 自动化：给运行 dbrowser 的终端 / 应用勾上 System Events（第一次会弹窗，点「允许」）；"
                    "没有它，dot 开窗后无法把你原来的应用放回前台"})]

    def version(self) -> str | None:
        try:
            return cdp_http.version(self.port).get("Browser")
        except DotBrowserError:
            return None

    def launch_command(self) -> list[str]:
        return ["open", "-gna", self.app_name, "--args", self._pattern, f"--remote-debugging-port={self.port}", *LAUNCH_FLAGS]

    def launch_instruction(self) -> dict:
        shell = " ".join(_sh(a) for a in self.launch_command())
        zh = (f"{self.display_name} 由 dot 以专用 profile（{self.profile}）在后台启动，不影响你自己的 {self.display_name}："
              f"运行 `dbrowser launch --browser {self.key}`（等价命令：{shell}）。第一次使用时需要在这个专用窗口里登录一次，之后会复用。"
              f"注意：端口 {self.port} 只对本机进程开放，但本机任何进程都能借此操作这个实例；任务结束后 `dbrowser quit --browser {self.key}` 退出它。")
        return {"shell": shell, "zh": zh}

    def launch(self, timeout_s: float = 10.0) -> bool:
        """Starts dot's instance when it is not up, under the same lock as `open` so two agents cannot start
        it twice. A process that is there without the port is given the timeout to open it (another agent
        may have spawned it a second ago); only then PROFILE_LOCKED. `open -g` keeps the app in the
        background, but a fresh profile's first window can still come to the front: the previously frontmost
        app is put back. Returns whether that restore happened."""
        with locked(lock_path(), timeout_s=timeout_s):
            if self.cdp_reachable():
                return False
            deadline = time.monotonic() + timeout_s
            if self.running():
                while time.monotonic() < deadline:
                    time.sleep(0.2)
                    if self.cdp_reachable():
                        return False
                raise DotBrowserError("PROFILE_LOCKED", f"dot's {self.display_name} instance is running but port {self.port} does not answer",
                                      f"它可能是以别的端口启动的：`dbrowser quit --browser {self.key}` 退出后重试", 4)
            os.makedirs(self.profile, exist_ok=True)
            before = frontmost.current_pid()
            _spawn(self.launch_command())
            while not self.cdp_reachable():
                if time.monotonic() >= deadline:
                    raise DotBrowserError("LAUNCH_FAILED", f"{self.display_name} did not open port {self.port} within {timeout_s:g}s",
                                          f"看一眼 {self.display_name} 是否弹了对话框；手动运行：{self.launch_instruction()['shell']}", 4)
                time.sleep(0.2)
            return self._restore_front(before, settle_s=min(LAUNCH_SETTLE_S, timeout_s))

    def _restore_front(self, before: int | None, settle_s: float = 0.0) -> bool:
        """Puts the app `before` (a pid) back in front if dot's own instance took it; an app the user
        switched to themselves is left alone. The window may appear a moment after the command returns."""
        if not before:
            return False
        deadline = time.monotonic() + settle_s
        while True:
            now = frontmost.current_pid()
            if now is not None and now != before:
                if now in _pids(self._pattern):
                    frontmost.activate_pid(before)
                    return True
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def quit(self, timeout_s: float = 10.0) -> bool:
        """Browser.close first (a clean exit that flushes the profile), pkill only when the process is still
        there after QUIT_GRACE_S or when the port was dead to begin with. Returns whether it is gone."""
        deadline = time.monotonic() + timeout_s
        kill_at = time.monotonic()
        if self.cdp_reachable():
            try:
                with self._browser_ws() as ws:
                    ws.send("Browser.close")
                kill_at = time.monotonic() + QUIT_GRACE_S
            except DotBrowserError:
                pass
        killed = False
        while self.running():
            if not killed and time.monotonic() >= kill_at:
                _pkill(self._pattern)
                killed = True
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        return not self.running()

    # -- CDP plumbing
    def _browser_ws(self):
        v = cdp_http.version(self.port)
        return cdp_ws.connect(v.get("webSocketDebuggerUrl") or f"ws://127.0.0.1:{self.port}/devtools/browser", timeout_s=10.0)

    def _target(self, tab_id: str) -> dict:
        t = cdp_http.find_target(self.port, tab_id)
        if t is None:
            raise DotBrowserError("TAB_NOT_FOUND", f"no tab (DevTools target) {tab_id!r} in dot's {self.display_name}", "run `dbrowser tabs`", 2)
        return t

    # -- spaces and tabs
    def list_spaces(self) -> dict:
        return {"spaces": [], "active": "", "windows": None, "isolation": "instance"}

    def list_tabs(self, space: str) -> list[dict]:
        return [{"id": t["id"], "title": t.get("title", ""), "url": t.get("url", ""), "location": "window", "active": False}
                for t in cdp_http.list_pages(self.port)]

    def active_ids(self) -> dict:
        return {"space": "", "tab": ""}

    def new_tab(self, space: str, url: str, restore: bool = True) -> dict:
        before = frontmost.current_pid() if restore else None
        with self._browser_ws() as ws:
            tid = ws.send("Target.createTarget", {"url": url, "newWindow": True, "background": True})["targetId"]
        switched = self._restore_front(before, settle_s=WINDOW_SETTLE_S) if restore else False
        return {"id": tid, "switched": switched, "new_ids": [tid]}

    def tab_info(self, tab_id: str) -> dict:
        t = self._target(tab_id)
        return {"id": t["id"], "url": t.get("url", ""), "title": t.get("title", ""), "loading": False}

    def navigate(self, tab_id: str, op: str, url: str | None = None, *, wait: bool = True, timeout_s: float = 10.0) -> dict:
        from .. import actions
        t = self._target(tab_id)
        with cdp_ws.connect(t["webSocketDebuggerUrl"], timeout_s=timeout_s) as cdp:
            cdp.enable("Page")
            started = True
            same_document = False
            if op == "goto":
                same_document = "loaderId" not in cdp.send("Page.navigate", {"url": url})
            elif op == "reload":
                cdp.send("Page.reload", {})
            elif op in ("back", "forward"):
                h = cdp.send("Page.getNavigationHistory")
                idx = h["currentIndex"] + (1 if op == "forward" else -1)
                if 0 <= idx < len(h["entries"]):
                    cdp.send("Page.navigateToHistoryEntry", {"entryId": h["entries"][idx]["id"]})
                else:
                    started = False
            else:
                raise ValueError(op)
            loading = started
            if wait and started:
                loading = not _wait_navigation(cdp, timeout_s, same_document=same_document)
            state = actions.page_state(cdp)
        return {"id": tab_id, "url": state.get("url", "") or t.get("url", ""), "title": state.get("title", ""), "loading": loading}

    def wait_loaded(self, tab_id: str, timeout_s: float = 10.0) -> dict:
        """After `open`: waits for the page's load event (unless it is already complete) and reads url / title."""
        from .. import actions
        t = self._target(tab_id)
        with cdp_ws.connect(t["webSocketDebuggerUrl"], timeout_s=timeout_s) as cdp:
            cdp.enable("Page")
            state = actions.page_state(cdp)
            loading = state.get("ready") != "complete"
            if loading:
                loading = cdp.wait_event("Page.loadEventFired", timeout_s) is None
                state = actions.page_state(cdp)
        return {"id": tab_id, "url": state.get("url", "") or t.get("url", ""), "title": state.get("title", ""), "loading": loading}

    def close_tab(self, tab_id: str) -> None:
        self._target(tab_id)
        with self._browser_ws() as ws:
            ws.send("Target.closeTarget", {"targetId": tab_id})

    def select_tab(self, tab_id: str) -> None:
        self._target(tab_id)
        cdp_http.activate(self.port, tab_id)

    def focus_space(self, space: str) -> None:
        pass

    def not_running_hint(self) -> str:
        return f"运行 `dbrowser launch --browser {self.key}` 在后台启动 dot 的专用 {self.display_name} 实例（不影响你自己的 {self.display_name}）"

    def raise_tab(self, tab_id: str, target_id: str | None) -> int | None:
        before = frontmost.current_pid()
        cdp_http.activate(self.port, target_id or tab_id)
        return before

    def restore_after_raise(self, token: int | None, tab_id: str) -> None:
        self._restore_front(token, settle_s=WINDOW_SETTLE_S)


def _wait_navigation(cdp, timeout_s: float, same_document: bool = False) -> bool:
    """True when the navigation finished: a same-document navigation (fragment, pushState, or a
    `Page.navigate` without loaderId), a back-forward-cache restore, or the main frame's load event."""
    if same_document:
        return True
    deadline = time.monotonic() + timeout_s
    main = lambda p: not p.get("frame", {}).get("parentId")  # noqa: E731
    while True:
        if cdp.wait_event("Page.navigatedWithinDocument", 0.0) is not None:
            return True
        nav = cdp.wait_event("Page.frameNavigated", 0.0, predicate=main)
        if nav is not None:
            if nav.get("type") == "BackForwardCacheRestore":
                return True
            return cdp.wait_event("Page.loadEventFired", max(0.0, deadline - time.monotonic())) is not None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        # one short wait that also queues whatever other events arrive meanwhile
        if cdp.wait_event("Page.loadEventFired", min(0.1, remaining)) is not None:
            return True


def _sh(arg: str) -> str:
    return arg if all(c.isalnum() or c in "-_=./:" for c in arg) else "'" + arg.replace("'", "'\\''") + "'"


class ChromeBrowser(ChromiumBrowser):
    key = "chrome"
    display_name = "Chrome"
    app_name = "Google Chrome"
    bundle_id = "com.google.Chrome"
    app_paths = ("/Applications/Google Chrome.app", "~/Applications/Google Chrome.app")
    default_port = 9223


class EdgeBrowser(ChromiumBrowser):
    key = "edge"
    display_name = "Edge"
    app_name = "Microsoft Edge"
    bundle_id = "com.microsoft.edgemac"
    app_paths = ("/Applications/Microsoft Edge.app", "~/Applications/Microsoft Edge.app")
    default_port = 9224
