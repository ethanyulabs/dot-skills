"""Command line interface. Every command prints exactly one JSON line on stdout.

Exit codes: 0 ok, 2 bad arguments / browser / space / session / config, 4 environment (osascript,
websockets, CDP port closed, browser not running, profile locked), 5 action failed.

Every browser-specific call goes through `ctx.browser` (an adapter from `browsers/`): Arc via its
AppleScript dictionary for spaces and tabs, Chrome / Edge as dot's own instance over CDP. Nothing here
changes what the user is looking at unless the user asked for it with --focus or --activate: `open`
creates the tab in the background and puts the user's tab (Arc) or app (Chrome / Edge) back if the
browser moved away from it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import traceback

from . import DotBrowserError, __version__
from . import cdp_http
from .browsers import registry
from .config import load_config
from .home import browser_home, config_path, dot_home, lock_path, output_dir, output_root, profile_dir, session_path, sessions_dir
from .lock import locked
from . import session as sessions

DEFAULT_TIMEOUT_MS = 10000


class Ctx:
    """Per-command context: config, the browser (resolved lazily), its port, warnings, timing.

    Browser order for a command without a session: --browser, config `browser`, the system's https
    handler. A command on a session takes the session's browser and port (--browser must agree).
    """

    def __init__(self, args):
        self.args = args
        cfg, cfg_warnings, cfg_ok = load_config()
        self.cfg, self.cfg_ok = cfg, cfg_ok
        self.warnings: list[str] = list(cfg_warnings)
        self.explicit_port = getattr(args, "port", None)
        self.timeout_s = float(getattr(args, "timeout", None) or DEFAULT_TIMEOUT_MS) / 1000.0
        self.quiet = bool(getattr(args, "quiet", False))
        self.t0 = time.monotonic()
        self._browser = None
        self.browser_source = ""

    # -- browser
    @property
    def browser(self):
        if self._browser is None:
            key, source = self._browser_key()
            self._browser = registry.make(key, port=self.explicit_port or (self.cfg.get(key) or {}).get("port"))
            self.browser_source = source
        return self._browser

    def _browser_key(self) -> tuple[str, str]:
        flag = getattr(self.args, "browser", None)
        if flag:
            return flag, "flag"
        if self.cfg.get("browser"):
            return self.cfg["browser"], "config"
        bundle, key = registry.system_default()
        if key:
            return key, "system"
        installed = registry.installed()
        hint = (f"`dbrowser config set browser=<{'|'.join(registry.BROWSERS)}>` as the default, or --browser <key> for this call"
                + (f"; installed: {', '.join(installed)}" if installed else ""))
        if bundle:
            raise DotBrowserError("BROWSER_UNSUPPORTED", f"the system's default browser is {bundle}, which dot cannot drive", hint, 2,
                                  payload={"installed": installed, "system_default": bundle})
        raise DotBrowserError("BROWSER_REQUIRED", "no browser named, none configured and no system default found", hint, 2,
                              payload={"installed": installed, "system_default": None})

    def use_session(self, sess: dict) -> None:
        """A session command: the session's browser and port win; an explicit --browser must agree."""
        key = sess.get("browser") or "arc"
        flag = getattr(self.args, "browser", None)
        if flag and flag != key:
            raise DotBrowserError("BAD_ARGS", f"session '{sess['name']}' belongs to {key}, not {flag}", "drop --browser or pick another session", 2)
        self._browser = registry.make(key, port=self.explicit_port or sess.get("port"))
        self.browser_source = "session"

    @property
    def port(self) -> int:
        return self.browser.port

    @port.setter
    def port(self, value: int) -> None:
        self.browser.port = int(value)

    @property
    def cdp_hint(self) -> str:
        return self.browser.launch_instruction()["zh"]

    def browser_fields(self) -> dict:
        b = self.browser
        return {"key": b.key, "source": self.browser_source, "display_name": b.display_name, "isolation": b.isolation}

    def log(self, msg: str) -> None:
        if not self.quiet:
            print(msg, file=sys.stderr, flush=True)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.log("warning: " + msg)

    def result(self, **fields) -> dict:
        out = {"ok": True, "version": __version__}
        if self._browser is not None:
            out["browser"] = self.browser_fields()
            out["port"] = self.port
        out.update(fields)
        out["warnings"] = list(self.warnings)
        out["timing_ms"] = int((time.monotonic() - self.t0) * 1000)
        return out

    def session_name(self) -> str:
        return sessions.resolve_name(getattr(self.args, "session", None), os.environ)

    # -- spaces
    def default_space(self) -> str | None:
        return (self.cfg.get(self.browser.key) or {}).get("space")

    def space_spec(self) -> tuple[str | None, str]:
        flag = getattr(self.args, "space", None)
        if flag:
            return flag, "flag"
        if self.default_space():
            return self.default_space(), "config"
        return None, ""

    def resolve_space(self) -> dict:
        """{"title", "id", "source"} for --space, else the configured default; else SPACE_REQUIRED with the list.
        A browser without spaces (instance isolation) gets an empty space; --space is then ignored with a warning."""
        spec, source = self.space_spec()
        if self.browser.isolation != "space":
            if source == "flag":
                self.warn(f"SPACE_IGNORED: {self.browser.display_name} has no spaces; dot's own instance is the isolation")
            return {"title": "", "id": "", "source": "instance"}
        listing = self.browser.list_spaces()
        _warn_duplicates(self, listing["spaces"])
        if spec is None:
            raise DotBrowserError("SPACE_REQUIRED", "no space named and no default space configured",
                              f"pass --space <title> for this call, or `dbrowser config set {self.browser.key}.space=<title>` as the default; "
                              "ask the user once which of the listed spaces to use", 2,
                              payload={"spaces": listing["spaces"]})
        key, val = ("id", spec[3:]) if spec.startswith("id:") else ("title", spec)
        hits = [s for s in listing["spaces"] if s[key] == val]
        if not hits:
            raise DotBrowserError("SPACE_NOT_FOUND", f"{self.browser.display_name} has no space with {key} {val!r}",
                              "run `dbrowser spaces` and use one of the titles (or id:<uuid>)", 2,
                              payload={"spaces": listing["spaces"]})
        if len(hits) > 1:
            self.warn(f"SPACE_TITLE_DUPLICATE: {len(hits)} spaces are titled {val!r}; using the first, pass --space id:<uuid> to pick")
        return {"title": hits[0]["title"], "id": hits[0]["id"], "source": source}


def _warn_duplicates(ctx: Ctx, spaces: list[dict]) -> None:
    seen: dict[str, int] = {}
    for s in spaces:
        seen[s["title"]] = seen.get(s["title"], 0) + 1
    for title, n in seen.items():
        if n > 1 and not any(w.startswith("SPACE_TITLE_DUPLICATE") and repr(title) in w for w in ctx.warnings):
            ctx.warn(f"SPACE_TITLE_DUPLICATE: {n} spaces are titled {title!r}; address them with --space id:<uuid>")


def _cdp_ok(ctx: Ctx) -> bool:
    """Is the DevTools port up? A browser dot launches itself is started here when it is not running."""
    b = ctx.browser
    if b.cdp_reachable():
        return True
    if b.isolation == "instance":
        restored = b.launch(timeout_s=ctx.timeout_s)  # PROFILE_LOCKED / LAUNCH_FAILED, exit 4
        ctx.warn(f"LAUNCHED: started dot's {b.display_name} instance on port {b.port}"
                 + ("; it had come to the front and the previous app was put back" if restored else ""))
        return True
    ctx.warn(f"CDP_UNREACHABLE: no DevTools endpoint on 127.0.0.1:{b.port}; page commands will not work until "
             f"{b.display_name} runs with --remote-debugging-port={b.port}")
    return False


def _nav_result(ctx: Ctx, tab_id: str, op: str, url: str | None = None) -> dict:
    """Navigates the session's tab through the adapter and waits for the load unless --no-wait."""
    wait = not getattr(ctx.args, "no_wait", False)
    info = ctx.browser.navigate(tab_id, op, url, wait=wait, timeout_s=ctx.timeout_s)
    if wait and info.get("loading"):
        ctx.warn("LOAD_TIMEOUT: the page is still loading")
    return info


def _wait_loaded(ctx: Ctx, tab_id: str) -> dict:
    """After `open`: waits until the page finished loading (Arc: polling its `loading` flag; chromium: the load
    event over CDP) and returns the tab's url and title."""
    b = ctx.browser
    if b.isolation == "space":
        deadline = time.monotonic() + ctx.timeout_s
        info = b.tab_info(tab_id)
        while info["loading"] and time.monotonic() < deadline:
            time.sleep(0.15)
            info = b.tab_info(tab_id)
    else:
        info = b.wait_loaded(tab_id, timeout_s=ctx.timeout_s)
    if info["loading"]:
        ctx.warn("LOAD_TIMEOUT: the page is still loading")
    return info


def _tab_fields(tab_id: str, target: dict | None, info: dict, url: str) -> dict:
    return {"tab_id": tab_id, "target_id": target["id"] if target else None,
            "ws_url": target.get("webSocketDebuggerUrl") if target else None,
            "url": info.get("url") or url, "title": info.get("title", "")}


def _new_session_name(args) -> str:
    """--session NAME must not already exist: two agents naming the same session would steal each other's tab."""
    if not args.session:
        return sessions.new_name()
    name = sessions.check_name(args.session)
    if os.path.exists(session_path(name)):
        raise DotBrowserError("SESSION_EXISTS", f"session '{name}' already exists",
                          f"`dbrowser close --session {name}` (or `--keep-tab`) first, or pick another name", 2)
    return name


def _session_result(ctx: Ctx, sess: dict, path: str, *, focused: bool, restored: bool, cdp: bool) -> dict:
    return ctx.result(session=sess["name"], export_hint=f"export DOT_BROWSER_SESSION={sess['name']}", space=sess["space"],
                      tab=sess["tab"], focused=focused, restored=restored, session_path=path, cdp=cdp)


# ---------------------------------------------------------------- commands: environment

def cmd_selftest(args) -> dict:
    ctx = Ctx(args)
    b = ctx.browser  # BROWSER_REQUIRED / BROWSER_UNSUPPORTED, exit 2
    checks: dict[str, bool] = {}
    problems: list[dict] = []
    browser_version = None
    launch = b.launch_instruction()
    for name, ok, problem in b.extra_checks():
        checks[name] = ok
        if problem:
            problems.append(problem)
    checks["installed"] = b.installed()
    if not checks["installed"]:
        problems.append({"code": "BROWSER_NOT_INSTALLED", "message": f"{b.display_name} is not installed ({b.app_paths[0]})",
                         "hint": f"安装 {b.display_name}，或换一个浏览器（`dbrowser config set browser=…`）"})
    checks["running"] = checks["installed"] and b.running()
    if checks["installed"] and not checks["running"]:
        problems.append({"code": "BROWSER_NOT_RUNNING", "message": f"{b.display_name} is not running", "hint": b.not_running_hint()})
    checks["automation"] = b.isolation != "space"
    if checks["running"] and b.isolation == "space":
        try:
            b.automation_check()
            checks["automation"] = True
        except DotBrowserError as e:
            problems.append({"code": e.code, "message": e.message, "hint": e.hint})
    checks["cdp"] = b.cdp_reachable()
    if not checks["cdp"]:
        problems.append({"code": "CDP_UNREACHABLE", "message": f"no DevTools endpoint on 127.0.0.1:{b.port}", "hint": launch["zh"]})
    elif checks["running"]:
        try:
            browser_version = b.version()
        except DotBrowserError:
            browser_version = None
    checks["websockets"] = importlib.util.find_spec("websockets") is not None
    if not checks["websockets"]:
        problems.append({"code": "DEPENDENCY_MISSING", "message": "python package websockets missing",
                         "hint": "run through uv (`uv run --script dbrowser.py`) so the inline dependency is installed"})
    _migration_hint(ctx)
    payload = {"checks": checks, "browser_version": browser_version, "launch": launch, "dot_home": dot_home(),
               "browser_home": browser_home(), "profile_dir": profile_dir(b.key) if b.isolation == "instance" else None,
               "config_ok": ctx.cfg_ok, "default_space": ctx.default_space() if b.isolation == "space" else None,
               "sessions": [x["name"] for x in sessions.list_sessions()], "problems": problems}
    if problems:
        first = problems[0]
        raise DotBrowserError(first["code"], first["message"], first["hint"], 4,
                              payload={**payload, "browser": ctx.browser_fields(), "port": b.port, "warnings": ctx.warnings})
    if args.deep:
        payload["deep"] = _deep_check(ctx)
    return ctx.result(**payload)


def _migration_hint(ctx: Ctx) -> None:
    """The subcommand used to be `dot arc` with its home at ~/.dot/arc: point at the equivalent config once."""
    old = os.path.join(dot_home(), "arc", "config.json")
    if not os.path.isfile(old) or os.path.isfile(config_path()):
        return
    try:
        with open(old, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    pairs = [f"arc.{k}={raw[k]}" for k in ("space", "port") if isinstance(raw, dict) and raw.get(k)]
    cmd = f"dbrowser config set {' '.join(pairs)}" if pairs else "dbrowser config set arc.space=<title>"
    ctx.warn(f"MIGRATION_HINT: {old} is from `dot arc` and is not read any more; `{cmd}` recreates it as {config_path()}; "
             "the old directory can be deleted")


def _deep_check(ctx: Ctx) -> dict:
    """Opens one websocket to the active tab's target and runs 1+1 there; reports how long that took."""
    from . import actions, cdp_ws
    active = ctx.browser.active_ids()
    info = ctx.browser.tab_info(active["tab"]) if active["tab"] else {"url": ""}
    pages = cdp_http.list_pages(ctx.port, hint=ctx.cdp_hint)
    target = next((t for t in pages if t.get("url") == info["url"]), None) or (pages[0] if pages else None)
    if target is None:
        return {"target_id": None, "ws_ms": None, "eval": None, "pages": len(pages), "note": "no page target to test against"}
    t0 = time.monotonic()
    with cdp_ws.connect(target["webSocketDebuggerUrl"], timeout_s=ctx.timeout_s) as cdp:
        value = actions.evaluate(cdp, "1+1")
    return {"target_id": target["id"], "ws_ms": int((time.monotonic() - t0) * 1000), "eval": value, "pages": len(pages)}


# ---------------------------------------------------------------- commands: spaces and tabs

def cmd_spaces(args) -> dict:
    ctx = Ctx(args)
    listing = ctx.browser.list_spaces()
    _warn_duplicates(ctx, listing["spaces"])
    return ctx.result(spaces=listing["spaces"], active=listing["active"], windows=listing["windows"],
                      isolation=ctx.browser.isolation, default_space=ctx.default_space() if ctx.browser.isolation == "space" else None)


def cmd_tabs(args) -> dict:
    ctx = Ctx(args)
    if ctx.browser.isolation != "space":
        _cdp_ok(ctx)
        tabs = ctx.browser.list_tabs("")
        return ctx.result(space=None, tabs=tabs, count=len(tabs))
    if args.all:
        listing = ctx.browser.list_spaces()
        tabs = []
        for s in listing["spaces"]:
            for t in ctx.browser.list_tabs(f"id:{s['id']}"):
                tabs.append({**t, "space": s["title"], "space_id": s["id"]})
        return ctx.result(space=None, tabs=tabs, count=len(tabs))
    space = ctx.resolve_space()
    tabs = ctx.browser.list_tabs(f"id:{space['id']}")
    return ctx.result(space=space, tabs=tabs, count=len(tabs))


# ---------------------------------------------------------------- commands: open / attach

def cmd_open(args) -> dict:
    ctx = Ctx(args)
    space = ctx.resolve_space()
    name = _new_session_name(args)
    cdp = _cdp_ok(ctx)
    target = None
    candidates: list[dict] = []
    restored = focused = False
    b = ctx.browser
    space_sel = f"id:{space['id']}" if b.isolation == "space" else ""
    with locked(lock_path(), timeout_s=ctx.timeout_s):
        before = {t["id"] for t in cdp_http.list_pages(ctx.port)} if cdp else set()
        made = b.new_tab(space_sel, args.url, restore=not args.focus)
        tab_id = made["id"]
        ctx.log(f"created tab {tab_id} in space {space['title']!r}" if space_sel else f"created tab {tab_id} in a new {b.display_name} window")
        if len(made["new_ids"]) > 1:
            ctx.warn(f"several tabs appeared in the space at once ({', '.join(made['new_ids'])}); bound the first")
        if args.focus:
            if space_sel:
                b.focus_space(space_sel)
            b.select_tab(tab_id)
            focused = True
        elif made["switched"]:
            restored = True
            ctx.log(f"{b.display_name} had moved to the new tab; the user's view was put back")
        if cdp and b.isolation == "instance":
            target = cdp_http.find_target(ctx.port, tab_id)  # the tab id is the target id
        elif cdp:
            found = cdp_http.wait_new_page(ctx.port, before, args.url, timeout_s=ctx.timeout_s)
            target = found["target"]
            candidates = [{"id": c["id"], "url": c.get("url"), "title": c.get("title")} for c in found["candidates"]]
    # the session is written before the load wait, so the tab is never left without a way to close it
    sess = sessions.create(name, ctx.port, space, _tab_fields(tab_id, target, {}, args.url), browser=b.key)
    path = sessions.save(sess)
    if cdp and target is None:
        if candidates and len(candidates) > 1:
            ctx.warn(f"AMBIGUOUS_TARGET: several DevTools targets match the URL; bind one with "
                     f"`dbrowser attach --session {name} --tab-id {tab_id} --target-id <id>` (see candidates)")
        else:
            ctx.warn("TARGET_NOT_FOUND: no DevTools target with this URL appeared in time (candidates lists the unrelated new ones); "
                     f"bind it later with `dbrowser attach --session {name} --tab-id {tab_id}`")
    info: dict = {}
    if not args.no_wait:
        try:
            info = _wait_loaded(ctx, tab_id)
        except DotBrowserError as e:
            ctx.warn(f"LOAD_UNKNOWN: could not confirm the page finished loading ({e.code}: {e.message})")
    if info:
        sess["tab"]["url"], sess["tab"]["title"] = info.get("url") or args.url, info.get("title", "")
        path = sessions.save(sess)
    out = _session_result(ctx, sess, path, focused=focused, restored=restored, cdp=cdp)
    if candidates and target is None:
        out["candidates"] = candidates
    return out


def _find_tab_everywhere(ctx: Ctx, tab_id: str | None = None, url: str | None = None) -> tuple[dict, dict]:
    """Scans every space of the front window (or dot's instance). Returns (space row, tab row)."""
    b = ctx.browser
    if b.isolation == "space":
        listing = b.list_spaces()
        groups = [(s, b.list_tabs(f"id:{s['id']}")) for s in listing["spaces"]]
    else:
        groups = [({"title": "", "id": ""}, b.list_tabs(""))]
    exact, prefix = [], []
    for s, tabs in groups:
        for t in tabs:
            if tab_id is not None and t["id"] == tab_id:
                return s, t
            if url is not None:
                if t["url"] == url:
                    exact.append((s, t))
                elif t["url"].startswith(url):
                    prefix.append((s, t))
    if tab_id is not None:
        raise DotBrowserError("TAB_NOT_FOUND", f"no tab with id {tab_id!r} in any space", "run `dbrowser tabs --all`", 2)
    hits = exact or prefix
    if not hits:
        raise DotBrowserError("TAB_NOT_FOUND", f"no open tab at {url!r}", "run `dbrowser tabs --all` or open it with `dbrowser open`", 2)
    if len(hits) > 1:
        raise DotBrowserError("AMBIGUOUS_TARGET", f"{len(hits)} tabs match {url!r}",
                          "pass --tab-id <arc tab id> (see `dbrowser tabs --all`)", 5,
                          payload={"candidates": [{"tab_id": t["id"], "space": s["title"], "url": t["url"]} for s, t in hits]})
    return hits[0]


def cmd_attach(args) -> dict:
    ctx = Ctx(args)
    name = _new_session_name(args)
    cdp = _cdp_ok(ctx)
    if args.active:
        active = ctx.browser.active_ids()
        if not active["tab"]:
            raise DotBrowserError("TAB_NOT_FOUND", "the front window has no active tab"
                                  + (" (dot's own instance has no user-facing active tab; use --tab-id or --url)" if ctx.browser.isolation != "space" else ""), "", 2)
        space_row, tab_row = _find_tab_everywhere(ctx, tab_id=active["tab"])
        source = "active"
    elif args.tab_id:
        space_row, tab_row = _find_tab_everywhere(ctx, tab_id=args.tab_id)
        source = "tab"
    elif args.url:
        space_row, tab_row = _find_tab_everywhere(ctx, url=args.url)
        source = "tab"
    else:
        raise DotBrowserError("BAD_ARGS", "attach needs --active, --tab-id or --url", "", 2)
    space = {"title": space_row["title"], "id": space_row["id"], "source": source if ctx.browser.isolation == "space" else "instance"}
    target = None
    if cdp:
        if args.target_id:
            target = cdp_http.find_target(ctx.port, args.target_id)
            if target is None:
                raise DotBrowserError("TARGET_NOT_FOUND", f"no DevTools target {args.target_id!r}", "check http://127.0.0.1:%d/json/list" % ctx.port, 5)
        else:
            hits = [t for t in cdp_http.list_pages(ctx.port) if t.get("url") == tab_row["url"]]
            if len(hits) == 1:
                target = hits[0]
            elif len(hits) > 1:
                raise DotBrowserError("AMBIGUOUS_TARGET", f"{len(hits)} DevTools targets are at {tab_row['url']!r}",
                                  "pass --target-id <id> (ids and titles are in the candidates)", 5,
                                  payload={"candidates": [{"id": h["id"], "url": h.get("url"), "title": h.get("title")} for h in hits]})
            else:
                ctx.warn("TARGET_NOT_FOUND: no DevTools target has this tab's URL (sleeping tab?); reload it and attach again, or pass --target-id")
    info = ctx.browser.tab_info(tab_row["id"])
    sess = sessions.create(name, ctx.port, space, _tab_fields(tab_row["id"], target, info, tab_row["url"]), browser=ctx.browser.key)
    path = sessions.save(sess)
    return _session_result(ctx, sess, path, focused=False, restored=False, cdp=cdp)


# ---------------------------------------------------------------- commands: navigation on a session

def _load_session(ctx: Ctx) -> tuple[dict, str]:
    name = ctx.session_name()
    sess = sessions.load(name)
    ctx.use_session(sess)
    return sess, name


def _after_nav(ctx: Ctx, sess: dict, info: dict) -> dict:
    sess["tab"]["url"], sess["tab"]["title"] = info["url"], info["title"]
    sessions.touch(sess)
    path = sessions.save(sess)
    return ctx.result(session=sess["name"], url=info["url"], title=info["title"], session_path=path)


def cmd_goto(args) -> dict:
    ctx = Ctx(args)
    sess, _ = _load_session(ctx)
    return _after_nav(ctx, sess, _nav_result(ctx, sess["tab"]["tab_id"], "goto", args.url))


def _nav(op):
    def cmd(args) -> dict:
        ctx = Ctx(args)
        sess, _ = _load_session(ctx)
        return _after_nav(ctx, sess, _nav_result(ctx, sess["tab"]["tab_id"], op))
    cmd.__name__ = f"cmd_{op}"
    return cmd


cmd_back, cmd_forward, cmd_reload = _nav("back"), _nav("forward"), _nav("reload")


def cmd_close(args) -> dict:
    ctx = Ctx(args)
    sess, name = _load_session(ctx)
    closed = False
    if not args.keep_tab:
        try:
            ctx.browser.close_tab(sess["tab"]["tab_id"])
            closed = True
        except DotBrowserError as e:
            if e.code != "TAB_NOT_FOUND":
                raise
            ctx.warn("TAB_NOT_FOUND: the tab was already closed")
    path = session_path(name)
    sessions.delete(name)
    return ctx.result(session=name, closed=closed, session_path=path)


def cmd_sessions(args) -> dict:
    ctx = Ctx(args)
    rows = []
    reachable: dict[int, bool] = {}
    for s in sessions.list_sessions():
        tid = s["tab"].get("target_id")
        port = int(s.get("port") or 0)
        alive = None
        if tid and port:
            if port not in reachable:
                try:
                    cdp_http.version(port)
                    reachable[port] = True
                except DotBrowserError:
                    reachable[port] = False
            if reachable[port]:
                alive = cdp_http.find_target(port, tid) is not None
        rows.append({"name": s["name"], "browser": s.get("browser", "arc"), "port": port, "space": s["space"]["title"],
                     "url": s["tab"].get("url"), "title": s["tab"].get("title"),
                     "tab_id": s["tab"].get("tab_id"), "target_id": tid, "alive": alive,
                     "last_used": s.get("last_used"), "created": s.get("created")})
    return ctx.result(sessions=rows, count=len(rows))


# ---------------------------------------------------------------- commands: launch / quit / endpoint

def cmd_launch(args) -> dict:
    ctx = Ctx(args)
    b = ctx.browser
    was_up = b.cdp_reachable()
    restored = False
    if not was_up:
        restored = bool(b.launch(timeout_s=ctx.timeout_s))  # BAD_ARGS for a browser the user runs themselves
    return ctx.result(launched=not was_up, running=True, restored=restored, launch=b.launch_instruction(),
                      profile_dir=profile_dir(b.key) if b.isolation == "instance" else None)


def cmd_quit(args) -> dict:
    ctx = Ctx(args)
    b = ctx.browser
    left = [s["name"] for s in sessions.list_sessions() if s.get("browser", "arc") == b.key]
    gone = b.quit(timeout_s=ctx.timeout_s)
    if not gone:
        ctx.warn(f"QUIT_TIMEOUT: dot's {b.display_name} instance is still running after {ctx.timeout_s:g}s; "
                 f"run `dbrowser quit --browser {b.key}` again or look at its window")
    if left:
        ctx.warn(f"SESSIONS_LEFT: {len(left)} session(s) of {b.key} still have files ({', '.join(left[:8])}); "
                 "`dbrowser close --keep-tab --session <name>` forgets them")
    return ctx.result(running=b.running(), sessions_left=left)


def cmd_endpoint(args) -> dict:
    """Where a Playwright (or any CDP client) can attach: the HTTP endpoint, the browser websocket and, with
    a session, that tab's target. Playwright is not a dependency; this only tells another tool where to connect."""
    ctx = Ctx(args)
    sess = None
    if getattr(args, "session", None) or os.environ.get("DOT_BROWSER_SESSION"):
        sess, _ = _load_session(ctx)
    v = cdp_http.version(ctx.port, hint=ctx.cdp_hint)
    http = f"http://127.0.0.1:{ctx.port}"
    target = cdp_http.find_target(ctx.port, sess["tab"]["target_id"]) if sess and sess["tab"].get("target_id") else None
    url = (target or {}).get("url") or (sess["tab"].get("url") if sess else None)
    page_hint = (f"page = next(p for c in browser.contexts for p in c.pages if p.url == {url!r})  "
                 "# or: context.new_cdp_session(page).send('Target.getTargetInfo')['targetInfo']['targetId'] == target_id"
                 if sess else "browser.contexts[0].pages lists the open tabs; dot's sessions are matched by url or target id")
    return ctx.result(session=sess["name"] if sess else None, http=http, ws_browser=v.get("webSocketDebuggerUrl"),
                      browser_version=v.get("Browser"), target_id=(target or {}).get("id") if sess else None,
                      ws_url=(target or {}).get("webSocketDebuggerUrl") if sess else None, url=url,
                      playwright={"python": f"from playwright.sync_api import sync_playwright\n"
                                            f"with sync_playwright() as p:\n    browser = p.chromium.connect_over_cdp('{http}')",
                                  "page": page_hint,
                                  "note": "connect_over_cdp attaches to every open tab and starts a Node driver (about two seconds); "
                                          "use it for long multi-step work on one page, dbrowser for one-off commands"})


# ---------------------------------------------------------------- commands: config

def _config_for_editing() -> dict:
    cfg, warnings, ok = load_config()
    if not ok:
        raise DotBrowserError("CONFIG_INVALID", "; ".join(warnings), f"fix or delete {config_path()}", 2)
    return cfg


def _config_result(ctx: Ctx, action: str, cfg: dict) -> dict:
    return ctx.result(action=action, config=cfg, config_path=config_path())


def cmd_config_show(args) -> dict:
    ctx = Ctx(args)
    cfg = _config_for_editing()
    return ctx.result(action="config.show", config=cfg, config_path=config_path(), dot_home=dot_home(), browser_home=browser_home(),
                      sessions_dir=sessions_dir(), output_root=output_root(), lock_path=lock_path(),
                      sessions=[s["name"] for s in sessions.list_sessions()])


def cmd_config_set(args) -> dict:
    from .config import coerce, save_config, set_key
    ctx = Ctx(args)
    cfg = _config_for_editing()
    for pair in args.pairs:
        if "=" not in pair:
            raise DotBrowserError("BAD_ARGS", f"expected key=value, got {pair!r}", "", 2)
        key, value = pair.split("=", 1)
        set_key(cfg, key.strip(), coerce(key.strip(), value))
    save_config(cfg)
    return _config_result(ctx, "config.set", cfg)


def cmd_config_unset(args) -> dict:
    from .config import save_config, unset_key
    ctx = Ctx(args)
    cfg = _config_for_editing()
    unset_key(cfg, args.key)
    save_config(cfg)
    return _config_result(ctx, "config.unset", cfg)


# ---------------------------------------------------------------- page commands (CDP)

def _bind_page(ctx: Ctx) -> tuple[dict, dict, bool]:
    """Loads the session and finds its DevTools target; wakes a sleeping tab with a reload (never a select).

    The port is the session's unless --port was given explicitly. The rebind takes the same lock as
    `open`, so a tab another agent is creating at that moment cannot be mistaken for ours.
    """
    sess, _name = _load_session(ctx)
    port = ctx.port
    cdp_http.version(port, hint=ctx.cdp_hint)  # CDP_UNREACHABLE, exit 4
    tid = sess["tab"].get("target_id")
    target = cdp_http.find_target(port, tid) if tid else None
    rebound = False
    if target is None:
        tab_id = sess["tab"]["tab_id"]
        try:
            info = ctx.browser.tab_info(tab_id)
        except DotBrowserError as e:
            if e.code == "TAB_NOT_FOUND":
                raise DotBrowserError("TAB_GONE", f"the session's tab no longer exists in {ctx.browser.display_name}",
                                  "run `dbrowser open` again (the session file is kept for the record; `dbrowser close --keep-tab` removes it)", 5)
            raise
        if ctx.browser.isolation == "instance":
            target = cdp_http.find_target(port, tab_id)  # the tab id is the target id; the tab exists, so this binds it
            if target is None:
                raise DotBrowserError("TARGET_GONE", f"the tab is in {ctx.browser.display_name} but exposes no DevTools target",
                                      "open the page again", 5)
            sess["tab"]["target_id"], sess["tab"]["ws_url"] = target["id"], target.get("webSocketDebuggerUrl")
            sess["tab"]["url"] = target.get("url") or info["url"]
            return sess, target, True
        with locked(lock_path(), timeout_s=ctx.timeout_s):
            before = {t["id"] for t in cdp_http.list_pages(port)}
            ctx.log(f"no DevTools target for tab {tab_id}; reloading it in the background")
            ctx.browser.navigate(tab_id, "reload", wait=False, timeout_s=ctx.timeout_s)
            found = cdp_http.wait_new_page(port, before, info["url"], timeout_s=ctx.timeout_s)
        target = found["target"]
        if target is None:
            raise DotBrowserError("TARGET_GONE", f"the tab is in {ctx.browser.display_name} but exposes no DevTools target (asleep, archived, or not a web page)",
                              f"select the tab in Arc once, then `dbrowser attach --session {sess['name']} --tab-id {tab_id}`; "
                              "or open the page again", 5)
        sess["tab"]["target_id"], sess["tab"]["ws_url"] = target["id"], target.get("webSocketDebuggerUrl")
        sess["tab"]["url"] = target.get("url") or info["url"]
        rebound = True
    return sess, target, rebound


def _take_snapshot(ctx: Ctx, cdp, sess: dict, *, root: str | None, depth: int | None, boxes: bool, max_chars: int) -> dict:
    from . import actions, locate, snapshot
    cdp.enable("Accessibility")
    root_bid = locate.resolve(cdp, sess, root)[0] if root else None
    nodes = cdp.send("Accessibility.getFullAXTree")["nodes"]
    text, refs = snapshot.build(nodes, max_depth=depth, root_backend_id=root_bid)
    if boxes and refs:
        cdp.enable("DOM")
        box_map = {}
        for entry in refs.values():
            try:
                q = cdp.send("DOM.getBoxModel", {"backendNodeId": entry["backend_node_id"]})["model"]["border"]
                xs, ys = q[0::2], q[1::2]
                box_map[entry["backend_node_id"]] = (round(min(xs)), round(min(ys)), round(max(xs) - min(xs)), round(max(ys) - min(ys)))
            except DotBrowserError:
                continue
        text, refs = snapshot.build(nodes, max_depth=depth, root_backend_id=root_bid, boxes=box_map)
    loader = cdp.send("Page.getFrameTree")["frameTree"]["frame"].get("loaderId", "")
    state = actions.page_state(cdp)
    sessions.set_refs(sess, url=state.get("url", ""), root=root or "body", loader_id=loader, refs=refs)
    out_dir = output_dir(sess["name"])
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "snapshot.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    truncated = len(text) > max_chars
    shown = text if not truncated else text[:max_chars] + "\n…[truncated]"
    return {"url": state.get("url", ""), "title": state.get("title", ""), "snapshot": shown, "truncated": truncated,
            "snapshot_path": path, "ref_count": len(refs)}


def _page_command(args, body) -> dict:
    """Binds the session, opens the websocket, runs body(ctx, cdp, sess) → fields, saves the session, adds --snapshot."""
    from . import cdp_ws
    ctx = Ctx(args)
    sess, target, rebound = _bind_page(ctx)
    with cdp_ws.connect(target["webSocketDebuggerUrl"], timeout_s=ctx.timeout_s) as cdp:
        fields = body(ctx, cdp, sess)
        if getattr(args, "snapshot", False):
            fields.update(_take_snapshot(ctx, cdp, sess, root=None, depth=None, boxes=False, max_chars=getattr(args, "max_chars", 30000) or 30000))
    sessions.touch(sess)
    path = sessions.save(sess)
    return ctx.result(session=sess["name"], session_path=path, rebound=rebound, **fields)


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _out_file(sess: dict, name: str) -> str:
    d = output_dir(sess["name"])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def cmd_snapshot(args) -> dict:
    def body(ctx, cdp, sess):
        return _take_snapshot(ctx, cdp, sess, root=args.root, depth=args.depth, boxes=args.boxes, max_chars=args.max_chars)
    args.snapshot = False
    return _page_command(args, body)


def _resolve(cdp, sess, spec) -> tuple[int, dict]:
    from . import locate
    return locate.resolve(cdp, sess, spec)


def cmd_click(args) -> dict:
    from . import actions

    def body(ctx, cdp, sess):
        bid, how = _resolve(cdp, sess, args.target)
        actions.click(cdp, bid, button=args.button, count=2 if args.double else 1, timeout_s=ctx.timeout_s)
        after = actions.settle(cdp)
        return {**how, "url_after": after["url"], "title_after": after["title"], "navigated": after["navigated"]}
    return _page_command(args, body)


def cmd_fill(args) -> dict:
    from . import actions

    def body(ctx, cdp, sess):
        bid, how = _resolve(cdp, sess, args.target)
        actions.fill(cdp, bid, args.text, timeout_s=ctx.timeout_s)
        if args.press:
            actions.press(cdp, args.press)
        after = actions.settle(cdp, nav_wait_s=1.0 if args.press else 0.2)
        return {**how, "url_after": after["url"], "title_after": after["title"], "navigated": after["navigated"]}
    return _page_command(args, body)


def cmd_press(args) -> dict:
    from . import actions

    def body(ctx, cdp, sess):
        bid = _resolve(cdp, sess, args.target)[0] if args.target else None
        key = actions.press(cdp, args.key, bid=bid)
        after = actions.settle(cdp)
        return {"key": key["key"], "modifiers": key["modifiers"], "url_after": after["url"], "title_after": after["title"], "navigated": after["navigated"]}
    return _page_command(args, body)


def cmd_eval(args) -> dict:
    from . import actions

    def body(ctx, cdp, sess):
        value = actions.evaluate(cdp, args.js)
        encoded = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if args.out or len(encoded) > 4000:
            path = args.out or _out_file(sess, f"eval-{_stamp()}.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(encoded)
            return {"result": None if len(encoded) > 4000 else value, "result_path": path, "chars": len(encoded)}
        return {"result": value, "result_path": None, "chars": len(encoded)}
    return _page_command(args, body)


def cmd_screenshot(args) -> dict:
    from . import actions

    def body(ctx, cdp, sess):
        path = os.path.abspath(args.out) if args.out else _out_file(sess, f"{_stamp()}-screenshot.png")
        clip = _resolve(cdp, sess, args.target)[0] if args.target else None
        try:
            shot = actions.screenshot(cdp, path, full=args.full, clip_bid=clip, timeout_s=min(3.0, ctx.timeout_s))
            return {**shot, "activated": False}
        except DotBrowserError as e:
            if e.code != "SCREENSHOT_NEEDS_FOREGROUND" or not args.activate:
                raise
        # --activate: raise the tab for the capture, then put the user's view back
        token = ctx.browser.raise_tab(sess["tab"]["tab_id"], sess["tab"]["target_id"])
        try:
            shot = actions.screenshot(cdp, path, full=args.full, clip_bid=clip, timeout_s=ctx.timeout_s)
        finally:
            ctx.browser.restore_after_raise(token, sess["tab"]["tab_id"])
        return {**shot, "activated": True}
    return _page_command(args, body)


def cmd_extract(args) -> dict:
    from . import actions

    def body(ctx, cdp, sess):
        root_bid = _resolve(cdp, sess, args.root)[0] if args.root else None
        value = actions.extract(cdp, args.what, root_bid=root_bid)
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1)
        path = None
        if args.out:
            path = os.path.abspath(args.out)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        truncated = len(text) > args.max_chars
        if truncated and path is None:
            path = _out_file(sess, f"extract-{_stamp()}.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        shown = value if not truncated else text[:args.max_chars] + "\n… [truncated; full text in file]"
        return {args.what: shown, "path": path, "truncated": truncated, "chars": len(text)}
    return _page_command(args, body)


def cmd_wait(args) -> dict:
    from . import actions

    def body(ctx, cdp, sess):
        if not any(v is not None for v in (args.url, args.selector, args.text, args.ms, args.load)):
            raise DotBrowserError("BAD_ARGS", "wait needs --url, --selector, --text, --ms or --load", "", 2)
        return actions.wait(cdp, url=args.url, selector=args.selector, text=args.text, ms=args.ms, load=args.load, timeout_s=ctx.timeout_s)
    return _page_command(args, body)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--browser", default=None, choices=list(registry.BROWSERS), help="arc | chrome | edge (overrides config `browser`)")
    common.add_argument("--port", type=int, default=None, help="DevTools port (config `<browser>.port`, default per browser)")
    common.add_argument("--session", default=None, help="session name (or DOT_BROWSER_SESSION)")
    common.add_argument("--space", default=None, help="space title or id:<uuid> (overrides the configured default; browsers without spaces ignore it)")
    common.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_MS, help="milliseconds")
    common.add_argument("--quiet", action="store_true")

    p = argparse.ArgumentParser(prog="dbrowser", description="dot browser: drive Arc (in a named space), Chrome or Edge (dot's own instance)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("selftest", parents=[common]); s.add_argument("--deep", action="store_true"); s.set_defaults(func=cmd_selftest)
    s = sub.add_parser("spaces", parents=[common]); s.set_defaults(func=cmd_spaces)
    s = sub.add_parser("tabs", parents=[common]); s.add_argument("--all", action="store_true"); s.set_defaults(func=cmd_tabs)

    s = sub.add_parser("open", parents=[common]); s.add_argument("url")
    s.add_argument("--focus", action="store_true", help="also switch to the space and raise the tab (the user wants to watch)")
    s.add_argument("--no-wait", action="store_true"); s.set_defaults(func=cmd_open)
    s = sub.add_parser("attach", parents=[common])
    g = s.add_mutually_exclusive_group(); g.add_argument("--active", action="store_true"); g.add_argument("--tab-id"); g.add_argument("--url")
    s.add_argument("--target-id"); s.set_defaults(func=cmd_attach)

    s = sub.add_parser("goto", parents=[common]); s.add_argument("url"); s.add_argument("--no-wait", action="store_true"); s.set_defaults(func=cmd_goto)
    for name, fn in (("back", cmd_back), ("forward", cmd_forward), ("reload", cmd_reload)):
        s = sub.add_parser(name, parents=[common]); s.add_argument("--no-wait", action="store_true"); s.set_defaults(func=fn)
    s = sub.add_parser("close", parents=[common]); s.add_argument("--keep-tab", action="store_true"); s.set_defaults(func=cmd_close)
    s = sub.add_parser("sessions", parents=[common]); s.set_defaults(func=cmd_sessions)
    s = sub.add_parser("launch", parents=[common]); s.set_defaults(func=cmd_launch)
    s = sub.add_parser("quit", parents=[common]); s.set_defaults(func=cmd_quit)
    s = sub.add_parser("endpoint", parents=[common]); s.set_defaults(func=cmd_endpoint)

    page = argparse.ArgumentParser(add_help=False)
    page.add_argument("--snapshot", action="store_true", help="also return a fresh snapshot after the action")
    page.add_argument("--max-chars", type=int, default=30000)
    s = sub.add_parser("snapshot", parents=[common])
    s.add_argument("--root", default=None); s.add_argument("--depth", type=int, default=None)
    s.add_argument("--boxes", action="store_true"); s.add_argument("--max-chars", type=int, default=30000); s.set_defaults(func=cmd_snapshot)
    s = sub.add_parser("click", parents=[common, page]); s.add_argument("target")
    s.add_argument("--double", action="store_true"); s.add_argument("--button", default="left", choices=["left", "right", "middle"]); s.set_defaults(func=cmd_click)
    s = sub.add_parser("fill", parents=[common, page]); s.add_argument("target"); s.add_argument("text")
    s.add_argument("--press", default=None); s.set_defaults(func=cmd_fill)
    s = sub.add_parser("press", parents=[common, page]); s.add_argument("key"); s.add_argument("--target", default=None); s.set_defaults(func=cmd_press)
    s = sub.add_parser("eval", parents=[common, page]); s.add_argument("js"); s.add_argument("--out", default=None); s.set_defaults(func=cmd_eval)
    s = sub.add_parser("screenshot", parents=[common, page]); s.add_argument("--out", default=None)
    s.add_argument("--full", action="store_true"); s.add_argument("--target", default=None)
    s.add_argument("--activate", action="store_true", help="raise the tab for the capture, then switch back"); s.set_defaults(func=cmd_screenshot)
    s = sub.add_parser("extract", parents=[common, page]); s.add_argument("--what", default="text", choices=["text", "links", "html", "title"])
    s.add_argument("--root", default=None); s.add_argument("--out", default=None); s.set_defaults(func=cmd_extract)
    s = sub.add_parser("wait", parents=[common, page]); s.add_argument("--url", default=None); s.add_argument("--selector", default=None)
    s.add_argument("--text", default=None); s.add_argument("--ms", type=int, default=None)
    s.add_argument("--load", default=None, choices=["load", "domcontentloaded"]); s.set_defaults(func=cmd_wait)

    cf = sub.add_parser("config", parents=[common])
    cf_sub = cf.add_subparsers(dest="config_cmd", required=True)
    x = cf_sub.add_parser("show"); x.set_defaults(func=cmd_config_show)
    x = cf_sub.add_parser("set"); x.add_argument("pairs", nargs="+", metavar="key=value"); x.set_defaults(func=cmd_config_set)
    x = cf_sub.add_parser("unset"); x.add_argument("key"); x.set_defaults(func=cmd_config_unset)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        if e.code == 0:
            return 0
        print(json.dumps({"ok": False, "action": "parse",
                          "error": {"code": "BAD_ARGS", "message": "invalid arguments", "hint": "run with --help"}}))
        return 2
    action = args.cmd if not getattr(args, "config_cmd", None) else f"config.{args.config_cmd}"
    try:
        out = args.func(args)
        out.setdefault("ok", True)
        out.setdefault("action", action)
        print(json.dumps(out, ensure_ascii=False, default=str))
        return 0
    except DotBrowserError as e:
        out = {"ok": False, "action": action, "error": e.to_json()}
        out.update(e.payload)
        print(json.dumps(out, ensure_ascii=False, default=str))
        return e.exit_code
    except Exception as e:  # pragma: no cover - unexpected
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"ok": False, "action": action,
                          "error": {"code": "INTERNAL", "message": f"{type(e).__name__}: {e}", "hint": "see stderr"}},
                         ensure_ascii=False))
        return 5
