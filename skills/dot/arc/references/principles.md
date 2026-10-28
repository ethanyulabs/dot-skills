# Principles (hold for every action)

## Step 0: orient

1. `SKILL_DIR` is the directory of the `dot` skill (the folder that holds its `SKILL.md`): `~/.claude/skills/dot`, `~/.agents/skills/dot`, or the checkout under `dot-skills/skills/dot`. `ARC_DIR="$SKILL_DIR/arc"` holds `COMMAND.md`; every relative path in this subcommand's files is relative to it.
2. Define the command:

   ```bash
   darc() { uv run --script "$ARC_DIR/scripts/darc.py" "$@"; }
   ```

   The function lives only in the shell that defined it; an agent whose tool runs each command in a fresh shell writes the full form every time: `uv run --script "$ARC_DIR/scripts/darc.py" <command> …`. Do not put the command in a shell variable (`D="uv run …"; $D spaces`): zsh does not word-split it and fails with "no such file or directory". `--script` keeps uv from picking up a `pyproject.toml` in the user's working directory. If `uv` is missing, say so and give the install line (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`); without uv the script runs under any Python 3.11–3.13 that has `websockets` installed (`python3 -I "$ARC_DIR/scripts/darc.py" …`).
3. Run `darc selftest`. `"ok": true` with every entry of `checks` true is the expected result. Exit 4 means the environment is not ready; `problems[0]` is the first thing to fix and `error.hint` tells the user what to do, in Chinese. The usual one:

   **`CDP_UNREACHABLE`: Arc is running without its DevTools port.** Give the user `relaunch.zh` and this line, both as they are:

   ```bash
   osascript -e 'quit app "Arc"'; sleep 3; open -a Arc --args --remote-debugging-port=9222
   ```

   Quitting Arc keeps every space and tab; relaunching with the flag takes a few seconds. Then `darc selftest` again. If the port still does not answer, start the binary directly: `/Applications/Arc.app/Contents/MacOS/Arc --remote-debugging-port=9222 &`. If page commands later fail with `CDP_CONNECT_FAILED` mentioning 403 or origin, relaunch with `--remote-debugging-port=9222 --remote-allow-origins=*`.

   Security: the port listens on 127.0.0.1 only, but any process on this Mac can then drive the logged-in browser. Say this once, and suggest a normal restart of Arc when the task is over.
4. `--deep` adds one websocket round trip to the active tab (`deep.ws_ms`); well under a second is normal.

## Output contract

- Every command prints exactly one JSON line on stdout. Progress goes to stderr (`--quiet` silences it). Parse stdout, never scrape stderr.
- Exit codes: 0 ok, 2 arguments / space / session / config (`BAD_ARGS`, `SPACE_REQUIRED`, `SPACE_NOT_FOUND`, `TAB_NOT_FOUND`, `NO_WINDOW`, `NO_SESSION`, `SESSION_INVALID`, `SESSION_EXISTS`, `CONFIG_*`), 4 environment (`DEPENDENCY_MISSING`, `ARC_NOT_INSTALLED`, `ARC_NOT_RUNNING`, `AUTOMATION_DENIED`, `CDP_UNREACHABLE`), 5 the action failed (`OSA_ERROR`, `OSA_TIMEOUT`, `LOCK_TIMEOUT`, `CDP_CONNECT_FAILED`, `CDP_TIMEOUT`, `CDP_ERROR`, `TARGET_NOT_FOUND`, `TARGET_GONE`, `TAB_GONE`, `REF_STALE`, `ELEMENT_NOT_FOUND`, `NOT_VISIBLE`, `SCREENSHOT_NEEDS_FOREGROUND`, `WAIT_TIMEOUT`, `ACTION_FAILED`, `INTERNAL`). On failure the line is `{"ok": false, "error": {"code", "message", "hint"}}` plus any extra fields the error carries (`spaces`, `candidates`, `checks`); relay `message` and `hint` (hints that need the user's hands are in Chinese).
- Every success carries `warnings` (strings that start with a code: `CDP_UNREACHABLE`, `TARGET_NOT_FOUND`, `AMBIGUOUS_TARGET`, `LOAD_TIMEOUT`, `LOAD_UNKNOWN`, `SPACE_TITLE_DUPLICATE`, `TAB_NOT_FOUND`) and `timing_ms`. A warning is not an error: the command did its work, but tell the user what it says.
- `--port`: an explicit flag wins, then the session's port (page commands), then `config.json`, then 9222.
- Cost: AppleScript commands take 0.2–1 s; page commands open one websocket to one tab, about 0.1–0.3 s plus the page's own time. Chain with `--snapshot` instead of calling `snapshot` separately.

## Sessions

A session is one tab in one space, bound to one DevTools target, in `~/.dot/arc/sessions/<name>.json`. `open` and `attach` create one and print `session` and `export_hint`; every later command finds it through `--session NAME` or `DOT_ARC_SESSION`, and fails with `NO_SESSION` (listing the existing names) when neither is set. There is no default session, so two agents never share one by accident. Names are 6 random base32 letters unless `--session` names one (1–40 characters from `A-Z a-z 0-9 . _ -`, starting with a letter or digit); a name that already exists is refused with `SESSION_EXISTS`, so two agents never share one by accident.

The tab is tracked by its Arc id (AppleScript) and its DevTools `target_id` (stable across navigations). When the target disappears because Arc put the tab to sleep, the next page command reloads the tab in the background and rebinds (`rebound: true` in the result); when even that gives no target, `TARGET_GONE` says what to do; when the tab itself is gone, `TAB_GONE`.

## Not disturbing the user

The user keeps working in Arc while the agent uses it. Therefore, by default:

- `open` creates the tab in the background. Arc itself switches the front window to a new tab, so the same AppleScript reads the user's active tab first and selects it again before returning (`restored: true` when that happened; a flicker of a fraction of a second, and nothing else).
- `goto`, `back`, `forward`, `reload`, `close` act on the tab by id, without raising it.
- `snapshot`, `click`, `fill`, `press`, `eval`, `extract`, `wait` work through DevTools on a background tab.
- `screenshot` tries to capture the background tab; Chromium may refuse to render a tab it is not showing, which comes back as `SCREENSHOT_NEEDS_FOREGROUND`.

Only two flags change what the user sees, and only when the user asked: `open --focus` (switch to the space and raise the tab, "我看着你做") and `screenshot --activate` (raise the tab for the capture, then switch back to the user's tab). Several agents in parallel: each with its own session, ideally its own space, none with these flags.

## Refs

`snapshot` numbers every clickable or focusable element `e1…eN` in document order and keeps `{ref → backendDOMNodeId, role, name}` in the session file together with the frame's loaderId. `click e12` in a later process checks that the page has not navigated (same loaderId) and that the node still exists, then acts on it. Otherwise `REF_STALE`: take a new snapshot. Selectors work without a snapshot: `css=button.primary` (or a bare CSS selector), `xpath=//a[1]`, `text=Sign in` (exact match first, then contains, deepest element wins). Iframes are not entered (same-origin ones neither, in this version); the outline shows `- iframe "name" [ref=…] [cross-origin content not included]`.

## Home directory

```
~/.dot/arc/
├── config.json              {"schema": "dot-arc/config/1", "space": "byted", "port": 9222}
├── lock                     taken by `open` while it creates and binds a tab (parallel-safe)
├── sessions/<name>.json     one file per session
└── output/<session>/        <stamp>-screenshot.png, snapshot.txt, extract-<stamp>.txt, eval-<stamp>.txt
```

`DOT_HOME` moves the `~/.dot` root (tests use it). `config set space=NAME` is the only writer of `config.json`; `--space` on a command wins over it for that command and leaves it untouched (`space.source` in every result says `flag`, `config`, `active` or `tab`, the last two for `attach`). A broken `config.json` is reported (`CONFIG_INVALID`, exit 2) and never overwritten.

## What the script decides and what you decide

| Decision | Who |
|---|---|
| which Arc tab the session is, which DevTools target, whether the page navigated after a click | the script |
| which space, when none was named and none is configured | you ask the user once (give the titles) |
| whether to save a space as the default | the user ("以后都用这个"); never silently |
| what to click next, when a ref is stale, when to stop retrying | you, from the snapshot; at most two blind retries, then screenshot and look |
| raising the tab or switching the space (`--focus`, `--activate`) | the user; never on your own |
| paying, sending, deleting, granting, signing in | the user, named in this conversation |

## Manual fallback

If the DevTools port cannot be opened at all (the user cannot relaunch Arc now), the AppleScript half still works: `spaces`, `tabs`, `open`, `attach`, `goto`, `back`, `forward`, `reload`, `close`, `sessions` and `config`; `open` and `tabs` return each tab's title and URL, which answers "open X and tell me the title". For anything on the page itself, open it for the user in their space and tell them which steps they have to do themselves. Do not fall back to GUI clicking, to another browser, or to re-implementing CDP by hand.

## Acceptance (for whoever edits this subcommand)

1. `python3 ~/.claude/skills/skill-creator/scripts/quick_validate.py <SKILL_DIR>` passes (the validator reads the `dot` SKILL.md, whose description carries this subcommand's sentence).
2. `uv run --script <ARC_DIR>/scripts/run_tests.py` is green without a real Arc.
3. With Arc relaunched on the port: `DOT_ARC_LIVE=1 uv run --script <ARC_DIR>/scripts/run_tests.py -k live` is green, and a manual `open → snapshot → click → screenshot → close` in the user's agent space leaves their active tab untouched.
