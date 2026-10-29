# Principles (hold for every action)

## Step 0: orient

1. `SKILL_DIR` is the directory of the `dot` skill (the folder that holds its `SKILL.md`): `~/.claude/skills/dot`, `~/.agents/skills/dot`, or the checkout under `dot-skills/skills/dot`. `BROWSER_DIR="$SKILL_DIR/browser"` holds `COMMAND.md`; every relative path in this subcommand's files is relative to it.
2. Define the command:

   ```bash
   dbrowser() { uv run --script "$BROWSER_DIR/scripts/dbrowser.py" "$@"; }
   ```

   The function lives only in the shell that defined it; an agent whose tool runs each command in a fresh shell writes the full form every time: `uv run --script "$BROWSER_DIR/scripts/dbrowser.py" <command> …`. Do not put the command in a shell variable (`D="uv run …"; $D spaces`): zsh does not word-split it and fails with "no such file or directory". `--script` keeps uv from picking up a `pyproject.toml` in the user's working directory. If `uv` is missing, say so and give the install line (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`); without uv the script runs under any Python 3.11–3.13 that has `websockets` installed (`python3 -I "$BROWSER_DIR/scripts/dbrowser.py" …`).
3. Run `dbrowser selftest` (add `--browser chrome` when the user named a browser). `"ok": true` with every entry of `checks` true is the expected result; `browser` says which browser was picked and why (`references/browsers.md`, Choosing the browser). Exit 2 with `BROWSER_UNSUPPORTED` / `BROWSER_REQUIRED` means no usable browser is named, configured or the system default: ask the user once (the error lists `installed`). Exit 4 means the environment is not ready; `problems[0]` is the first thing to fix and `error.hint` tells the user what to do, in Chinese. The usual ones:

   **`CDP_UNREACHABLE` on Arc: Arc is running without its DevTools port.** Give the user `launch.zh` and this line, both as they are:

   ```bash
   osascript -e 'quit app "Arc"'; sleep 3; open -a Arc --args --remote-debugging-port=9222
   ```

   Quitting Arc keeps every space and tab; relaunching with the flag takes a few seconds. Then `dbrowser selftest` again. If the port still does not answer, start the binary directly: `/Applications/Arc.app/Contents/MacOS/Arc --remote-debugging-port=9222 &`. If page commands later fail with `CDP_CONNECT_FAILED` mentioning 403 or origin, relaunch with `--remote-debugging-port=9222 --remote-allow-origins=*`.

   **`BROWSER_NOT_RUNNING` on Chrome / Edge: dot's instance is not up.** Nothing for the user to do: `dbrowser launch --browser chrome` (or the next `open`) starts it in the background with its dedicated profile. `PROFILE_LOCKED` means an older dot instance holds the profile without the port: `dbrowser quit --browser chrome`, then again. `AUTOMATION_DENIED` naming System Events: macOS has not allowed this terminal to ask which app is in front; `references/troubleshooting.md`.

   Security: the port listens on 127.0.0.1 only, but any process on this Mac can then drive that browser (the user's logged-in Arc, or dot's logged-in profile). Say this once, and suggest a normal restart of Arc / `dbrowser quit` when the task is over.
4. `--deep` adds one websocket round trip to a page (`deep.ws_ms`); well under a second is normal.

## Output contract

- Every command prints exactly one JSON line on stdout. Progress goes to stderr (`--quiet` silences it). Parse stdout, never scrape stderr.
- Exit codes: 0 ok, 2 arguments / browser / space / session / config (`BAD_ARGS`, `INVALID_URL`, `BROWSER_REQUIRED`, `BROWSER_UNSUPPORTED`, `SPACE_REQUIRED`, `SPACE_NOT_FOUND`, `TAB_NOT_FOUND`, `NO_WINDOW`, `NO_SESSION`, `SESSION_INVALID`, `SESSION_EXISTS`, `CONFIG_*`), 4 environment (`DEPENDENCY_MISSING`, `BROWSER_NOT_INSTALLED`, `BROWSER_NOT_RUNNING`, `AUTOMATION_DENIED`, `CDP_UNREACHABLE`, `PROFILE_LOCKED`, `LAUNCH_FAILED`), 5 the action failed (`OSA_ERROR`, `OSA_TIMEOUT`, `LOCK_TIMEOUT`, `CDP_CONNECT_FAILED`, `CDP_TIMEOUT`, `CDP_ERROR`, `TARGET_NOT_FOUND`, `TARGET_GONE`, `TAB_GONE`, `REF_STALE`, `ELEMENT_NOT_FOUND`, `NOT_VISIBLE`, `ELEMENT_DISABLED`, `SCREENSHOT_NEEDS_FOREGROUND`, `WAIT_TIMEOUT`, `ACTION_FAILED`, `INTERNAL`). On failure the line is `{"ok": false, "error": {"code", "message", "hint"}}` plus any extra fields the error carries (`spaces`, `candidates`, `checks`, `installed`); relay `message` and `hint` (hints that need the user's hands are in Chinese).
- Every success carries `warnings` (strings that start with a code: `CDP_UNREACHABLE`, `LAUNCHED`, `SPACE_IGNORED`, `TARGET_NOT_FOUND`, `AMBIGUOUS_TARGET`, `LOAD_TIMEOUT`, `LOAD_UNKNOWN`, `SPACE_TITLE_DUPLICATE`, `TAB_NOT_FOUND`, `SESSIONS_LEFT`, `QUIT_TIMEOUT`, `MIGRATION_HINT`) and `timing_ms`; every command that touched a browser also carries `browser {key, source, display_name, isolation}` and `port` (`config` and `sessions` do not). A warning is not an error: the command did its work, but tell the user what it says.
- `--browser`: an explicit flag wins, then the session's browser (session commands; a conflicting flag is `BAD_ARGS`), then `config.browser`, then the system default. `--port`: an explicit flag, then the session's port, then `config.<browser>.port`, then the browser's default (9222 / 9223 / 9224).
- Cost: AppleScript commands take 0.2–1 s; page commands open one websocket to one tab, about 0.1–0.3 s plus the page's own time; `click` / `fill` wait for actionability only as long as the element needs. Chain with `--snapshot` instead of calling `snapshot` separately. Starting dot's Chrome takes a few seconds once.

## Sessions

A session is one tab, bound to one DevTools target, in one browser, in `~/.dot/browser/sessions/<name>.json` (`browser`, `port`, `space`, `tab`, last snapshot refs). `open` and `attach` create one and print `session` and `export_hint`; every later command finds it through `--session NAME` or `DOT_BROWSER_SESSION`, takes the browser and port from it, and fails with `NO_SESSION` (listing the existing names) when neither is set. There is no default session, so two agents never share one by accident. Names are 6 random base32 letters unless `--session` names one (1–40 characters from `A-Z a-z 0-9 . _ -`, starting with a letter or digit); a name that already exists is refused with `SESSION_EXISTS`.

The tab is tracked by its browser id (Arc's tab id; on Chrome / Edge the DevTools target id itself) and its DevTools `target_id` (stable across navigations). When the target disappears because Arc put the tab to sleep, the next page command reloads the tab in the background and rebinds (`rebound: true` in the result); when even that gives no target, `TARGET_GONE` says what to do; when the tab itself is gone, `TAB_GONE`.

## Not disturbing the user

The user keeps working while the agent uses a browser. Therefore, by default:

- Arc: `open` creates the tab in the background. Arc itself switches the front window to a new tab, so the same AppleScript reads the user's active tab first and selects it again before returning (`restored: true` when that happened; a flicker of a fraction of a second, and nothing else). `goto`, `back`, `forward`, `reload`, `close` act on the tab by id, without raising it.
- Chrome / Edge: dot's instance is launched with `open -g` (not brought to the front) and every session gets its own window. Creating a window can still raise the browser once; the script reads the frontmost application through System Events before, and puts it back after (`restored: true`). Nothing runs in the user's own Chrome.
- `snapshot`, `click`, `fill`, `press`, `eval`, `extract`, `wait` work through DevTools without raising anything.
- `screenshot` captures the tab where it is; Chromium may refuse to render a tab it is not showing, which comes back as `SCREENSHOT_NEEDS_FOREGROUND` (Arc renders background tabs; on Chrome / Edge the session's tab is the foreground tab of its own window).

Only two flags change what the user sees, and only when the user asked: `open --focus` (switch to the space and raise the tab / window, "我看着你做") and `screenshot --activate` (raise the tab for the capture, then put the user's tab or app back). Several agents in parallel: each with its own session, ideally its own space on Arc, none with these flags.

## Refs and selectors

`snapshot` numbers every clickable or focusable element `e1…eN` in document order and keeps `{ref → backendDOMNodeId, role, name}` in the session file together with the frame's loaderId. `click e12` in a later process checks that the page has not navigated (same loaderId) and that the node still exists, then acts on it. Otherwise `REF_STALE`: take a new snapshot. Selectors work without a snapshot and follow Playwright's forms: `css=button.primary` (or a bare CSS selector), `xpath=//a[1]`, `text=Sign in` (exact match first, then contains, deepest element wins), `role=button[name="Sign in"]` (accessible role and name; exact name first, then contains). Iframes are not entered (same-origin ones neither, in this version); the outline shows `- iframe "name" [ref=…] [cross-origin content not included]`.

## Home directory

```
~/.dot/browser/
├── config.json              {"schema": "dot-browser/config/1", "browser": "arc", "arc": {"space": "byted", "port": 9222}, "chrome": {"port": 9223}}
├── lock                     taken by `open` while it creates and binds a tab (parallel-safe)
├── profiles/<browser>/      the user-data-dir of dot's own Chrome / Edge instance (logins live here)
├── sessions/<name>.json     one file per session
└── output/<session>/        <stamp>-screenshot.png, snapshot.txt, extract-<stamp>.txt, eval-<stamp>.txt
```

`DOT_HOME` moves the `~/.dot` root (tests use it). `config set` is the only writer of `config.json`: keys are `browser` and `<browser>.space` (browsers with spaces only) / `<browser>.port`; `--browser` / `--space` / `--port` on a command win over it for that command and leave it untouched (`browser.source` and `space.source` in every result say where the value came from). A broken `config.json` is reported (`CONFIG_INVALID`, exit 2) and never overwritten. `~/.dot/arc/` from the former `dot arc` is not read; `selftest` prints a `MIGRATION_HINT` with the equivalent `config set` line while it exists.

## What the script decides and what you decide

| Decision | Who |
|---|---|
| which tab the session is, which DevTools target, whether the page navigated after a click, when to start dot's Chrome | the script |
| which browser, when none was named, none is configured and the system default is unsupported | you ask the user once (give `installed`) |
| which space (Arc), when none was named and none is configured | you ask the user once (give the titles) |
| whether to save a browser or a space as the default | the user ("以后都用这个"); never silently |
| logging in to a site in dot's Chrome / Edge profile | the user, in the dot window, once per site |
| what to click next, when a ref is stale, when to stop retrying | you, from the snapshot; at most two blind retries, then screenshot and look |
| raising the tab, switching the space, raising dot's window (`--focus`, `--activate`) | the user; never on your own |
| paying, sending, deleting, granting, signing in | the user, named in this conversation |

## Manual fallback

If Arc's DevTools port cannot be opened at all (the user cannot relaunch Arc now), the AppleScript half still works: `spaces`, `tabs`, `open`, `attach`, `goto`, `back`, `forward`, `reload`, `close`, `sessions` and `config`; `open` and `tabs` return each tab's title and URL, which answers "open X and tell me the title". For anything on the page itself, open it for the user in their space and tell them which steps they have to do themselves, or, when the site does not need their Arc login, do it in dot's Chrome instead (`--browser chrome`). Do not fall back to GUI clicking or to re-implementing CDP by hand.
