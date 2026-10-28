"""Command line interface. Every command prints exactly one JSON line on stdout.

Exit codes: 0 ok, 2 bad arguments / space / session / config, 4 environment (osascript, websockets,
CDP port closed, Arc not running), 5 action failed.

Nothing here changes what the user is looking at unless the user asked for it with --focus or
--activate: `open` creates the tab in the background and puts the user's active tab back if Arc
moved away from it.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import traceback

from . import DotArcError, __version__
from . import cdp_http, osa
from .config import load_config
from .home import arc_home, config_path, dot_home, lock_path, output_dir, output_root, session_path, sessions_dir
from .lock import locked
from . import session as sessions

DEFAULT_TIMEOUT_MS = 10000


class Ctx:
    """Per-command context: config, port, warnings, timing."""

    def __init__(self, args):
        self.args = args
        cfg, cfg_warnings, cfg_ok = load_config()
        self.cfg, self.cfg_ok = cfg, cfg_ok
        self.warnings: list[str] = list(cfg_warnings)
        self.explicit_port = getattr(args, "port", None)
        self.port = int(self.explicit_port or cfg.get("port") or cdp_http.DEFAULT_PORT)
        self.timeout_s = float(getattr(args, "timeout", None) or DEFAULT_TIMEOUT_MS) / 1000.0
        self.quiet = bool(getattr(args, "quiet", False))
        self.t0 = time.monotonic()

    def log(self, msg: str) -> None:
        if not self.quiet:
            print(msg, file=sys.stderr, flush=True)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.log("warning: " + msg)

    def result(self, **fields) -> dict:
        out = {"ok": True, "version": __version__, "port": self.port}
        out.update(fields)
        out["warnings"] = list(self.warnings)
        out["timing_ms"] = int((time.monotonic() - self.t0) * 1000)
        return out

    def session_name(self) -> str:
        return sessions.resolve_name(getattr(self.args, "session", None), os.environ)

    # -- spaces
    def space_spec(self) -> tuple[str | None, str]:
        flag = getattr(self.args, "space", None)
        if flag:
            return flag, "flag"
        if self.cfg.get("space"):
            return self.cfg["space"], "config"
        return None, ""

    def resolve_space(self) -> dict:
        """{"title", "id", "source"} for --space, else the configured default; else SPACE_REQUIRED with the list."""
        spec, source = self.space_spec()
        listing = osa.list_spaces()
        _warn_duplicates(self, listing["spaces"])
        if spec is None:
            raise DotArcError("SPACE_REQUIRED", "no space named and no default space configured",
                              "pass --space <title> for this call, or `darc config set space=<title>` as the default; "
                              "ask the user once which of the listed spaces to use", 2,
                              payload={"spaces": listing["spaces"]})
        key, val = ("id", spec[3:]) if spec.startswith("id:") else ("title", spec)
        hits = [s for s in listing["spaces"] if s[key] == val]
        if not hits:
            raise DotArcError("SPACE_NOT_FOUND", f"Arc has no space with {key} {val!r}",
                              "run `darc spaces` and use one of the titles (or id:<uuid>)", 2,
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
    try:
        cdp_http.version(ctx.port)
        return True
    except DotArcError as e:
        ctx.warn(f"CDP_UNREACHABLE: {e.message}; page commands will not work until Arc is relaunched with --remote-debugging-port={ctx.port}")
        return False


def _wait_loaded(ctx: Ctx, arc_id: str) -> dict:
    """Polls the tab's `loading` through AppleScript (no CDP, no focus) until it is false or the timeout passes."""
    deadline = time.monotonic() + ctx.timeout_s
    info = osa.tab_info(arc_id)
    while info["loading"] and time.monotonic() < deadline:
        time.sleep(0.15)
        info = osa.tab_info(arc_id)
    if info["loading"]:
        ctx.warn("LOAD_TIMEOUT: the page is still loading")
    return info


def _tab_fields(arc_id: str, target: dict | None, info: dict, url: str) -> dict:
    return {"arc_id": arc_id, "target_id": target["id"] if target else None,
            "ws_url": target.get("webSocketDebuggerUrl") if target else None,
            "url": info.get("url") or url, "title": info.get("title", "")}


def _new_session_name(args) -> str:
    """--session NAME must not already exist: two agents naming the same session would steal each other's tab."""
    if not args.session:
        return sessions.new_name()
    name = sessions.check_name(args.session)
    if os.path.exists(session_path(name)):
        raise DotArcError("SESSION_EXISTS", f"session '{name}' already exists",
                          f"`darc close --session {name}` (or `--keep-tab`) first, or pick another name", 2)
    return name


def _session_result(ctx: Ctx, sess: dict, path: str, *, focused: bool, restored: bool, cdp: bool) -> dict:
    return ctx.result(session=sess["name"], export_hint=f"export DOT_ARC_SESSION={sess['name']}", space=sess["space"],
                      tab=sess["tab"], focused=focused, restored=restored, session_path=path, cdp=cdp)


# ---------------------------------------------------------------- commands: environment

def cmd_selftest(args) -> dict:
    ctx = Ctx(args)
    checks: dict[str, bool] = {}
    problems: list[dict] = []
    arc_version = None
    relaunch = cdp_http.relaunch_instruction(ctx.port)

    checks["osascript"] = osa.osascript_path() is not None
    if not checks["osascript"]:
        problems.append({"code": "DEPENDENCY_MISSING", "message": "osascript not found", "hint": "dot arc only runs on macOS"})
    checks["arc_installed"] = osa.arc_app_path() is not None
    if not checks["arc_installed"]:
        problems.append({"code": "ARC_NOT_INSTALLED", "message": "Arc.app not found", "hint": "安装 Arc 浏览器（https://arc.net）"})
    checks["arc_running"] = checks["arc_installed"] and osa.is_arc_running()
    if checks["arc_installed"] and not checks["arc_running"]:
        problems.append({"code": "ARC_NOT_RUNNING", "message": "Arc is not running",
                         "hint": f"启动 Arc（要用页面命令请直接以调试端口启动：{relaunch['shell'].split('; ')[-1]}）"})
    checks["automation"] = False
    if checks["arc_running"]:
        try:
            arc_version = osa.arc_version()
            checks["automation"] = True
        except DotArcError as e:
            problems.append({"code": e.code, "message": e.message, "hint": e.hint})
    try:
        cdp_http.version(ctx.port)
        checks["cdp"] = True
    except DotArcError as e:
        checks["cdp"] = False
        problems.append({"code": "CDP_UNREACHABLE", "message": e.message, "hint": relaunch["zh"]})
    checks["websockets"] = importlib.util.find_spec("websockets") is not None
    if not checks["websockets"]:
        problems.append({"code": "DEPENDENCY_MISSING", "message": "python package websockets missing",
                         "hint": "run through uv (`uv run --script darc.py`) so the inline dependency is installed"})

    payload = {"checks": checks, "arc_version": arc_version, "relaunch": relaunch, "dot_home": dot_home(),
               "arc_home": arc_home(), "config_ok": ctx.cfg_ok, "default_space": ctx.cfg.get("space"),
               "sessions": [s["name"] for s in sessions.list_sessions()], "problems": problems}
    if problems:
        first = problems[0]
        raise DotArcError(first["code"], first["message"], first["hint"], 4, payload={**payload, "port": ctx.port})
    if args.deep:
        payload["deep"] = _deep_check(ctx)
    return ctx.result(**payload)


def _deep_check(ctx: Ctx) -> dict:
    """Opens one websocket to the active tab's target and runs 1+1 there; reports how long that took."""
    from . import actions, cdp_ws
    active = osa.active_ids()
    info = osa.tab_info(active["tab"]) if active["tab"] else {"url": ""}
    pages = cdp_http.list_pages(ctx.port)
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
    listing = osa.list_spaces()
    _warn_duplicates(ctx, listing["spaces"])
    return ctx.result(spaces=listing["spaces"], active=listing["active"], windows=listing["windows"],
                      default_space=ctx.cfg.get("space"))


def cmd_tabs(args) -> dict:
    ctx = Ctx(args)
    if args.all:
        listing = osa.list_spaces()
        tabs = []
        for s in listing["spaces"]:
            for t in osa.list_tabs(f"id:{s['id']}"):
                tabs.append({**t, "space": s["title"], "space_id": s["id"]})
        return ctx.result(space=None, tabs=tabs, count=len(tabs))
    space = ctx.resolve_space()
    tabs = osa.list_tabs(f"id:{space['id']}")
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
    with locked(lock_path(), timeout_s=ctx.timeout_s):
        before = {t["id"] for t in cdp_http.list_pages(ctx.port)} if cdp else set()
        made = osa.new_tab(f"id:{space['id']}", args.url, restore=not args.focus)
        arc_id = made["id"]
        ctx.log(f"created tab {arc_id} in space {space['title']!r}")
        if len(made["new_ids"]) > 1:
            ctx.warn(f"several tabs appeared in the space at once ({', '.join(made['new_ids'])}); bound the first")
        if args.focus:
            osa.focus_space(f"id:{space['id']}")
            osa.select_tab(arc_id)
            focused = True
        elif made["switched"]:
            restored = True
            ctx.log("Arc had switched to the new tab; the user's tab was selected again")
        if cdp:
            found = cdp_http.wait_new_page(ctx.port, before, args.url, timeout_s=ctx.timeout_s)
            target = found["target"]
            candidates = [{"id": c["id"], "url": c.get("url"), "title": c.get("title")} for c in found["candidates"]]
    # the session is written before the load wait, so the tab is never left without a way to close it
    sess = sessions.create(name, ctx.port, space, _tab_fields(arc_id, target, {}, args.url))
    path = sessions.save(sess)
    if cdp and target is None:
        if candidates and len(candidates) > 1:
            ctx.warn(f"AMBIGUOUS_TARGET: several DevTools targets match the URL; bind one with "
                     f"`darc attach --session {name} --tab-id {arc_id} --target-id <id>` (see candidates)")
        else:
            ctx.warn("TARGET_NOT_FOUND: no DevTools target with this URL appeared in time (candidates lists the unrelated new ones); "
                     f"bind it later with `darc attach --session {name} --tab-id {arc_id}`")
    info: dict = {}
    if not args.no_wait:
        try:
            info = _wait_loaded(ctx, arc_id)
        except DotArcError as e:
            ctx.warn(f"LOAD_UNKNOWN: could not confirm the page finished loading ({e.code}: {e.message})")
    if info:
        sess["tab"]["url"], sess["tab"]["title"] = info.get("url") or args.url, info.get("title", "")
        path = sessions.save(sess)
    out = _session_result(ctx, sess, path, focused=focused, restored=restored, cdp=cdp)
    if candidates and target is None:
        out["candidates"] = candidates
    return out


def _find_tab_everywhere(tab_id: str | None = None, url: str | None = None) -> tuple[dict, dict]:
    """Scans every space of the front window. Returns (space row, tab row)."""
    listing = osa.list_spaces()
    exact, prefix = [], []
    for s in listing["spaces"]:
        for t in osa.list_tabs(f"id:{s['id']}"):
            if tab_id is not None and t["id"] == tab_id:
                return s, t
            if url is not None:
                if t["url"] == url:
                    exact.append((s, t))
                elif t["url"].startswith(url):
                    prefix.append((s, t))
    if tab_id is not None:
        raise DotArcError("TAB_NOT_FOUND", f"no tab with id {tab_id!r} in any space", "run `darc tabs --all`", 2)
    hits = exact or prefix
    if not hits:
        raise DotArcError("TAB_NOT_FOUND", f"no open tab at {url!r}", "run `darc tabs --all` or open it with `darc open`", 2)
    if len(hits) > 1:
        raise DotArcError("AMBIGUOUS_TARGET", f"{len(hits)} tabs match {url!r}",
                          "pass --tab-id <arc tab id> (see `darc tabs --all`)", 5,
                          payload={"candidates": [{"tab_id": t["id"], "space": s["title"], "url": t["url"]} for s, t in hits]})
    return hits[0]


def cmd_attach(args) -> dict:
    ctx = Ctx(args)
    name = _new_session_name(args)
    if args.active:
        active = osa.active_ids()
        if not active["tab"]:
            raise DotArcError("TAB_NOT_FOUND", "the front window has no active tab", "", 2)
        space_row, tab_row = _find_tab_everywhere(tab_id=active["tab"])
        source = "active"
    elif args.tab_id:
        space_row, tab_row = _find_tab_everywhere(tab_id=args.tab_id)
        source = "tab"
    elif args.url:
        space_row, tab_row = _find_tab_everywhere(url=args.url)
        source = "tab"
    else:
        raise DotArcError("BAD_ARGS", "attach needs --active, --tab-id or --url", "", 2)
    space = {"title": space_row["title"], "id": space_row["id"], "source": source}
    target = None
    cdp = _cdp_ok(ctx)
    if cdp:
        if args.target_id:
            target = cdp_http.find_target(ctx.port, args.target_id)
            if target is None:
                raise DotArcError("TARGET_NOT_FOUND", f"no DevTools target {args.target_id!r}", "check http://127.0.0.1:%d/json/list" % ctx.port, 5)
        else:
            hits = [t for t in cdp_http.list_pages(ctx.port) if t.get("url") == tab_row["url"]]
            if len(hits) == 1:
                target = hits[0]
            elif len(hits) > 1:
                raise DotArcError("AMBIGUOUS_TARGET", f"{len(hits)} DevTools targets are at {tab_row['url']!r}",
                                  "pass --target-id <id> (ids and titles are in the candidates)", 5,
                                  payload={"candidates": [{"id": h["id"], "url": h.get("url"), "title": h.get("title")} for h in hits]})
            else:
                ctx.warn("TARGET_NOT_FOUND: no DevTools target has this tab's URL (sleeping tab?); reload it and attach again, or pass --target-id")
    info = osa.tab_info(tab_row["id"])
    sess = sessions.create(name, ctx.port, space, _tab_fields(tab_row["id"], target, info, tab_row["url"]))
    path = sessions.save(sess)
    return _session_result(ctx, sess, path, focused=False, restored=False, cdp=cdp)


# ---------------------------------------------------------------- commands: navigation on a session

def _load_session(ctx: Ctx) -> tuple[dict, str]:
    name = ctx.session_name()
    sess = sessions.load(name)
    return sess, name


def _after_nav(ctx: Ctx, sess: dict) -> dict:
    arc_id = sess["tab"]["arc_id"]
    info = osa.tab_info(arc_id) if getattr(ctx.args, "no_wait", False) else _wait_loaded(ctx, arc_id)
    sess["tab"]["url"], sess["tab"]["title"] = info["url"], info["title"]
    sessions.touch(sess)
    path = sessions.save(sess)
    return ctx.result(session=sess["name"], url=info["url"], title=info["title"], session_path=path)


def cmd_goto(args) -> dict:
    ctx = Ctx(args)
    sess, _ = _load_session(ctx)
    osa.set_url(sess["tab"]["arc_id"], args.url)
    return _after_nav(ctx, sess)


def _nav(op):
    def cmd(args) -> dict:
        ctx = Ctx(args)
        sess, _ = _load_session(ctx)
        getattr(osa, op)(sess["tab"]["arc_id"])
        return _after_nav(ctx, sess)
    cmd.__name__ = f"cmd_{op}"
    return cmd


cmd_back, cmd_forward, cmd_reload = _nav("go_back"), _nav("go_forward"), _nav("reload")


def cmd_close(args) -> dict:
    ctx = Ctx(args)
    sess, name = _load_session(ctx)
    closed = False
    if not args.keep_tab:
        try:
            osa.close_tab(sess["tab"]["arc_id"])
            closed = True
        except DotArcError as e:
            if e.code != "TAB_NOT_FOUND":
                raise
            ctx.warn("TAB_NOT_FOUND: the tab was already closed")
    path = session_path(name)
    sessions.delete(name)
    return ctx.result(session=name, closed=closed, session_path=path)


def cmd_sessions(args) -> dict:
    ctx = Ctx(args)
    rows = []
    cdp = None
    for s in sessions.list_sessions():
        tid = s["tab"].get("target_id")
        alive = None
        if tid:
            if cdp is None:
                try:
                    cdp_http.version(s.get("port", ctx.port))
                    cdp = True
                except DotArcError:
                    cdp = False
            if cdp:
                alive = cdp_http.find_target(s.get("port", ctx.port), tid) is not None
        rows.append({"name": s["name"], "space": s["space"]["title"], "url": s["tab"].get("url"), "title": s["tab"].get("title"),
                     "arc_id": s["tab"].get("arc_id"), "target_id": tid, "alive": alive,
                     "last_used": s.get("last_used"), "created": s.get("created")})
    return ctx.result(sessions=rows, count=len(rows))


# ---------------------------------------------------------------- commands: config

def _config_for_editing() -> dict:
    cfg, warnings, ok = load_config()
    if not ok:
        raise DotArcError("CONFIG_INVALID", "; ".join(warnings), f"fix or delete {config_path()}", 2)
    return cfg


def _config_result(ctx: Ctx, action: str, cfg: dict) -> dict:
    return ctx.result(action=action, config=cfg, config_path=config_path())


def cmd_config_show(args) -> dict:
    ctx = Ctx(args)
    cfg = _config_for_editing()
    return ctx.result(action="config.show", config=cfg, config_path=config_path(), dot_home=dot_home(), arc_home=arc_home(),
                      sessions_dir=sessions_dir(), output_root=output_root(), lock_path=lock_path(),
                      sessions=[s["name"] for s in sessions.list_sessions()])


def cmd_config_set(args) -> dict:
    from .config import coerce, save_config
    ctx = Ctx(args)
    cfg = _config_for_editing()
    for pair in args.pairs:
        if "=" not in pair:
            raise DotArcError("BAD_ARGS", f"expected key=value, got {pair!r}", "", 2)
        key, value = pair.split("=", 1)
        cfg[key.strip()] = coerce(key.strip(), value)
    save_config(cfg)
    return _config_result(ctx, "config.set", cfg)


def cmd_config_unset(args) -> dict:
    from .config import save_config
    ctx = Ctx(args)
    cfg = _config_for_editing()
    cfg.pop(args.key, None)
    save_config(cfg)
    return _config_result(ctx, "config.unset", cfg)


# ---------------------------------------------------------------- page commands (CDP)

def _bind_page(ctx: Ctx) -> tuple[dict, dict, bool]:
    """Loads the session and finds its DevTools target; wakes a sleeping tab with a reload (never a select).

    The port is the session's unless --port was given explicitly. The rebind takes the same lock as
    `open`, so a tab another agent is creating at that moment cannot be mistaken for ours.
    """
    sess, _name = _load_session(ctx)
    ctx.port = int(ctx.explicit_port or sess.get("port") or ctx.port)
    port = ctx.port
    cdp_http.version(port)  # CDP_UNREACHABLE, exit 4
    tid = sess["tab"].get("target_id")
    target = cdp_http.find_target(port, tid) if tid else None
    rebound = False
    if target is None:
        arc_id = sess["tab"]["arc_id"]
        try:
            info = osa.tab_info(arc_id)
        except DotArcError as e:
            if e.code == "TAB_NOT_FOUND":
                raise DotArcError("TAB_GONE", "the session's tab no longer exists in Arc",
                                  "run `darc open` again (the session file is kept for the record; `darc close --keep-tab` removes it)", 5)
            raise
        with locked(lock_path(), timeout_s=ctx.timeout_s):
            before = {t["id"] for t in cdp_http.list_pages(port)}
            ctx.log(f"no DevTools target for tab {arc_id}; reloading it in the background")
            osa.reload(arc_id)
            found = cdp_http.wait_new_page(port, before, info["url"], timeout_s=ctx.timeout_s)
        target = found["target"]
        if target is None:
            raise DotArcError("TARGET_GONE", "the tab is in Arc but exposes no DevTools target (asleep, archived, or not a web page)",
                              f"select the tab in Arc once, then `darc attach --session {sess['name']} --tab-id {arc_id}`; "
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
            except DotArcError:
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
        actions.click(cdp, bid, button=args.button, count=2 if args.double else 1)
        after = actions.settle(cdp)
        return {**how, "url_after": after["url"], "title_after": after["title"], "navigated": after["navigated"]}
    return _page_command(args, body)


def cmd_fill(args) -> dict:
    from . import actions

    def body(ctx, cdp, sess):
        bid, how = _resolve(cdp, sess, args.target)
        actions.fill(cdp, bid, args.text)
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
        except DotArcError as e:
            if e.code != "SCREENSHOT_NEEDS_FOREGROUND" or not args.activate:
                raise
        # --activate: raise the tab for the capture, then put the user's tab back
        active = osa.active_ids()
        cdp_http.activate(ctx.port, sess["tab"]["target_id"])
        try:
            shot = actions.screenshot(cdp, path, full=args.full, clip_bid=clip, timeout_s=ctx.timeout_s)
        finally:
            if active.get("tab") and active["tab"] != sess["tab"]["arc_id"]:
                osa.select_tab(active["tab"])
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
            raise DotArcError("BAD_ARGS", "wait needs --url, --selector, --text, --ms or --load", "", 2)
        return actions.wait(cdp, url=args.url, selector=args.selector, text=args.text, ms=args.ms, load=args.load, timeout_s=ctx.timeout_s)
    return _page_command(args, body)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", type=int, default=None, help="DevTools port (config `port`, default 9222)")
    common.add_argument("--session", default=None, help="session name (or DOT_ARC_SESSION)")
    common.add_argument("--space", default=None, help="space title or id:<uuid> (overrides the configured default)")
    common.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_MS, help="milliseconds")
    common.add_argument("--quiet", action="store_true")

    p = argparse.ArgumentParser(prog="darc", description="dot arc: drive Arc in a named space")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("selftest", parents=[common]); s.add_argument("--deep", action="store_true"); s.set_defaults(func=cmd_selftest)
    s = sub.add_parser("spaces", parents=[common]); s.set_defaults(func=cmd_spaces)
    s = sub.add_parser("tabs", parents=[common]); s.add_argument("--all", action="store_true"); s.set_defaults(func=cmd_tabs)

    s = sub.add_parser("open", parents=[common]); s.add_argument("url")
    s.add_argument("--focus", action="store_true", help="also switch Arc to the space and raise the tab")
    s.add_argument("--no-wait", action="store_true"); s.set_defaults(func=cmd_open)
    s = sub.add_parser("attach", parents=[common])
    g = s.add_mutually_exclusive_group(); g.add_argument("--active", action="store_true"); g.add_argument("--tab-id"); g.add_argument("--url")
    s.add_argument("--target-id"); s.set_defaults(func=cmd_attach)

    s = sub.add_parser("goto", parents=[common]); s.add_argument("url"); s.add_argument("--no-wait", action="store_true"); s.set_defaults(func=cmd_goto)
    for name, fn in (("back", cmd_back), ("forward", cmd_forward), ("reload", cmd_reload)):
        s = sub.add_parser(name, parents=[common]); s.add_argument("--no-wait", action="store_true"); s.set_defaults(func=fn)
    s = sub.add_parser("close", parents=[common]); s.add_argument("--keep-tab", action="store_true"); s.set_defaults(func=cmd_close)
    s = sub.add_parser("sessions", parents=[common]); s.set_defaults(func=cmd_sessions)

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
    except DotArcError as e:
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
