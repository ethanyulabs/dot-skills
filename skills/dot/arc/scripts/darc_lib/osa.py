"""AppleScript side: spaces and tabs through Arc's own dictionary (osascript).

Rules learned on a real Arc (1.152):
- Never store an Arc object in an AppleScript variable (`set sp to (first space ... whose ...)` then
  `tabs of sp` fails with -1700). Always use the inline specifier, in every statement.
- Spaces belong to the profile, not the window: `spaces of front window` lists them all; only
  `active space` / `active tab` and `focus` are window-bound. We always address `front window`.
- `tabs of front window` is every tab of every space, so `first tab of front window whose id is X`
  finds a tab in any space.
- Bulk `(get id of tabs of ...) as text` with `text item delimiters` is 10x faster than a repeat loop.
- `tell application "Arc"` launches Arc when it is not running: check `is_arc_running()` first.
"""
from __future__ import annotations

import subprocess

from . import DotArcError

US = "\x1f"  # between items of one list
RS = "\x1e"  # between lists
NO_WINDOW_MARK = "NOWINDOW"

ERROR_CODES = {
    "-1743": ("AUTOMATION_DENIED", "macOS refused to let this process control Arc",
              "系统设置 → 隐私与安全性 → 自动化：允许终端（或运行 darc 的应用）控制 Arc，然后重试", 4),
    "-600": ("ARC_NOT_RUNNING", "Arc is not running", "先启动 Arc", 4),
}


def quote(s: str) -> str:
    """An AppleScript string literal."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def space_selector(spec: str) -> str:
    """`id:<uuid>` addresses a space by id, anything else by title. Always inline, always front window."""
    if spec.startswith("id:"):
        return f"(first space of front window whose id is {quote(spec[3:])})"
    return f"(first space of front window whose title is {quote(spec)})"


def tab_selector(tab_id: str) -> str:
    return f"(first tab of front window whose id is {quote(tab_id)})"


def run(script: str, timeout: float = 15.0, not_found: str | None = None) -> str:
    """Runs one AppleScript and returns its stdout stripped. Errors become DotArcError."""
    try:
        cp = subprocess.run(["osascript", "-"], input=script, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise DotArcError("DEPENDENCY_MISSING", "osascript not found", "dot arc only runs on macOS", 4)
    except subprocess.TimeoutExpired:
        raise DotArcError("OSA_TIMEOUT", f"osascript did not answer within {timeout:g}s",
                          "Arc 可能卡住或弹出了对话框；看一眼 Arc 再重试", 5)
    if cp.returncode == 0:
        return cp.stdout.strip("\n")
    err = (cp.stderr or cp.stdout).strip()
    for num, (code, message, hint, exit_code) in ERROR_CODES.items():
        if f"({num})" in err:
            raise DotArcError(code, message, hint, exit_code)
    if "(-1701)" in err and "URL" in err:
        raise DotArcError("INVALID_URL", "Arc rejected the URL for a new tab", "use an http(s) or file URL; Arc does not open data: URLs through AppleScript", 2)
    if "(-1728)" in err and arc_app_path() is None:
        raise DotArcError("ARC_NOT_INSTALLED", "Arc.app not found", "安装 Arc 浏览器（https://arc.net）", 4)
    if ("(-1719)" in err or "(-1728)" in err) and not_found:
        raise DotArcError(not_found, f"Arc has no such object: {err}", "", 2)
    raise DotArcError("OSA_ERROR", err or f"osascript exited {cp.returncode}", "", 5)


ARC_APP_PATHS = ("/Applications/Arc.app", "~/Applications/Arc.app")


def arc_app_path() -> str | None:
    import os
    for p in ARC_APP_PATHS:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            return p
    return None


def osascript_path() -> str | None:
    import shutil
    return shutil.which("osascript")


def is_arc_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "Arc"], capture_output=True, text=True).returncode == 0
    except FileNotFoundError:  # pragma: no cover
        return False


# ---------------------------------------------------------------- helpers

def _split(block: str) -> list[str]:
    return block.split(US) if block != "" else []


def _bool(s: str) -> bool:
    return s.strip().lower() == "true"


_PRELUDE = (
    'tell application "Arc"\n'
    '  set AppleScript\'s text item delimiters to (character id 31)\n'
    '  if (count of windows) is 0 then return "NOWINDOW"\n'
)


def _guard(out: str) -> str:
    if out.strip() == NO_WINDOW_MARK:
        raise DotArcError("NO_WINDOW", "Arc has no window open", "在 Arc 里开一个窗口（⌘N）再重试", 2)
    return out


# ---------------------------------------------------------------- builders

def arc_version() -> str:
    return run('tell application "Arc" to get version')


def list_spaces() -> dict:
    """Spaces of the front window with their tab counts, the active one marked, and the window count."""
    script = (
        _PRELUDE +
        '  set ids to (get id of spaces of front window) as text\n'
        '  set titles to (get title of spaces of front window) as text\n'
        '  set activeId to id of active space of front window\n'
        '  set n to count of windows\n'
        '  set counts to {}\n'
        '  repeat with i from 1 to (count of spaces of front window)\n'
        '    set end of counts to (count of tabs of space i of front window)\n'
        '  end repeat\n'
        '  return ids & (character id 30) & titles & (character id 30) & activeId & (character id 30) & n & (character id 30) & (counts as text)\n'
        'end tell'
    )
    out = _guard(run(script))
    ids, titles, active, n, counts = (out.split(RS) + ["", "", "", "", ""])[:5]
    ids, titles, counts = _split(ids), _split(titles), _split(counts)
    spaces = []
    for i, sid in enumerate(ids):
        spaces.append({"id": sid, "title": titles[i] if i < len(titles) else "", "active": sid == active,
                       "tabs": int(counts[i]) if i < len(counts) and counts[i].isdigit() else 0})
    return {"spaces": spaces, "active": active, "windows": int(n) if n.strip().isdigit() else 0}


def list_tabs(space: str) -> list[dict]:
    sel = space_selector(space)
    script = (
        _PRELUDE +
        f'  set ids to (get id of tabs of {sel}) as text\n'
        f'  set titles to (get title of tabs of {sel}) as text\n'
        f'  set urls to (get URL of tabs of {sel}) as text\n'
        f'  set locs to (get location of tabs of {sel}) as text\n'
        '  set activeId to id of active tab of front window\n'
        '  return ids & (character id 30) & titles & (character id 30) & urls & (character id 30) & locs & (character id 30) & activeId\n'
        'end tell'
    )
    out = _guard(run(script, not_found="SPACE_NOT_FOUND"))
    ids, titles, urls, locs, active = (out.split(RS) + [""] * 5)[:5]
    ids, titles, urls, locs = _split(ids), _split(titles), _split(urls), _split(locs)
    tabs = []
    for i, tid in enumerate(ids):
        tabs.append({"id": tid, "title": titles[i] if i < len(titles) else "", "url": urls[i] if i < len(urls) else "",
                     "location": locs[i] if i < len(locs) else "", "active": tid == active.strip()})
    return tabs


def active_ids() -> dict:
    """Ids of the front window's active space and active tab ("" when Arc has none, e.g. right after launch).

    Read with `set … to`, never by concatenating the bare property: `(id of active tab of front window) & x`
    fails with -1700 when the tab is a missing value.
    """
    script = (
        _PRELUDE +
        '  set sp to ""\n'
        '  try\n'
        '    set sp to (id of active space of front window) as text\n'
        '  end try\n'
        '  set tb to ""\n'
        '  try\n'
        '    set tb to (id of active tab of front window) as text\n'
        '  end try\n'
        '  return sp & (character id 30) & tb\n'
        'end tell'
    )
    out = _guard(run(script))
    space, tab = (out.split(RS) + ["", ""])[:2]
    return {"space": space.strip(), "tab": tab.strip()}


def new_tab(space: str, url: str, restore: bool = True) -> dict:
    """Creates a tab with the real URL inside the space, in one script that also undoes Arc's own switch.

    Arc raises a newly created tab (and its space) in the front window, and `id of (make new tab …)`
    fails with -1700, so the script reads the user's active tab, diffs the space's tab ids around the
    creation and, with `restore`, selects the user's tab again when it is no longer active, all before
    returning (no osascript round trip in between, so the user cannot switch tabs inside the window).
    Returns {"id": new tab id, "switched": whether Arc had moved away, "new_ids": every new id}.
    """
    sel = space_selector(space)
    restore_block = ""
    if restore:
        restore_block = (
            '  if keepId is not "" then\n'
            '    set nowId to ""\n'
            '    try\n'
            '      set nowId to (id of active tab of front window) as text\n'
            '    end try\n'
            '    if nowId is not keepId then\n'
            '      select (first tab of front window whose id is keepId)\n'
            '      set switched to "true"\n'
            '    end if\n'
            '  else if keepSpace is not "" and ((id of active space of front window) as text) is not keepSpace then\n'
            '    focus (first space of front window whose id is keepSpace)\n'
            '    set switched to "true"\n'
            '  end if\n'
        )
    script = (
        _PRELUDE +
        '  set keepId to ""\n'
        '  set keepSpace to ""\n'
        '  try\n'
        '    set keepSpace to (id of active space of front window) as text\n'
        '  end try\n'
        '  try\n'
        '    set keepId to (id of active tab of front window) as text\n'
        '  end try\n'
        '  set switched to "false"\n'
        f'  set beforeIds to (get id of tabs of {sel})\n'
        '  try\n'
        f'    tell {sel} to make new tab with properties {{URL:{quote(url)}}}\n'
        '  on error errMsg number errNum\n'
        # Arc switches to the space before it validates the URL: put the user back, then re-raise
        + restore_block +
        '    error errMsg number errNum\n'
        '  end try\n'
        f'  set afterIds to (get id of tabs of {sel})\n'
        '  set newIds to {}\n'
        '  repeat with x in afterIds\n'
        '    if beforeIds does not contain (x as text) then set end of newIds to (x as text)\n'
        '  end repeat\n'
        + restore_block +
        '  return (newIds as text) & (character id 30) & switched\n'
        'end tell'
    )
    out = _guard(run(script, not_found="SPACE_NOT_FOUND"))
    ids, switched = (out.split(RS) + ["", ""])[:2]
    new_ids = _split(ids.strip("\n"))
    if not new_ids:
        raise DotArcError("OSA_ERROR", "Arc created no new tab in that space", "run `darc tabs --space …` to see what happened", 5)
    return {"id": new_ids[0], "switched": _bool(switched), "new_ids": new_ids}


def focus_space(space: str) -> None:
    run(f'tell application "Arc" to focus {space_selector(space)}', not_found="SPACE_NOT_FOUND")


def select_tab(tab_id: str) -> None:
    run(f'tell application "Arc" to select {tab_selector(tab_id)}', not_found="TAB_NOT_FOUND")


def tab_info(tab_id: str) -> dict:
    sel = tab_selector(tab_id)
    script = (
        _PRELUDE +
        f'  return (id of {sel}) & (character id 31) & (title of {sel}) & (character id 31) & (URL of {sel}) & (character id 31) & (loading of {sel})\n'
        'end tell'
    )
    out = _guard(run(script, not_found="TAB_NOT_FOUND"))
    tid, title, url, loading = (out.split(US) + [""] * 4)[:4]
    return {"id": tid, "title": title, "url": url, "loading": _bool(loading)}


def set_url(tab_id: str, url: str) -> None:
    run(f'tell application "Arc" to set URL of {tab_selector(tab_id)} to {quote(url)}', not_found="TAB_NOT_FOUND")


def go_back(tab_id: str) -> None:
    run(f'tell application "Arc" to go back {tab_selector(tab_id)}', not_found="TAB_NOT_FOUND")


def go_forward(tab_id: str) -> None:
    run(f'tell application "Arc" to go forward {tab_selector(tab_id)}', not_found="TAB_NOT_FOUND")


def reload(tab_id: str) -> None:
    run(f'tell application "Arc" to reload {tab_selector(tab_id)}', not_found="TAB_NOT_FOUND")


def close_tab(tab_id: str) -> None:
    run(f'tell application "Arc" to close {tab_selector(tab_id)}', not_found="TAB_NOT_FOUND")
