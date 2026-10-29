# Spaces, tabs and sessions

Spaces exist on Arc only. On Chrome / Edge (`isolation: instance`) `spaces` returns an empty list, `--space` is ignored with a `SPACE_IGNORED` warning, `tabs` lists the tabs of dot's instance, and `open` puts every session in its own window; the rest of this file reads the same with "space" meaning "dot's instance".

## Inputs

| Input | Used for | When missing |
|---|---|---|
| browser key (`arc` / `chrome` / `edge`) | `--browser` on any command | the configured default, else the system default (`references/browsers.md`) |
| space title, or `id:<uuid>` (Arc) | `open`, `tabs`; `--space` on any command | the configured default (`arc.space`); else `SPACE_REQUIRED` with the list of spaces: ask once |
| URL (http, https or file; Arc refuses `data:` URLs with `INVALID_URL`) | `open`, `goto`, `attach --url` | `BAD_ARGS` |
| session name | every command after `open` / `attach`, via `--session` or `DOT_BROWSER_SESSION` | `open` makes one up; others fail with `NO_SESSION` |

## Steps: spaces / tabs

1. `dbrowser spaces` lists `spaces[{title, id, tabs, active}]`, `active`, `windows`, `isolation` and `default_space` (Arc); on Chrome / Edge `spaces` is `[]` and `isolation` is `instance`. Two spaces with the same title give `SPACE_TITLE_DUPLICATE` in `warnings`; address them with `--space id:<uuid>`.
2. `dbrowser tabs --space S` lists `tabs[{id, title, url, location, active}]` (`location`: `pinned`, `unpinned`, `topApp`); `--all` adds `space` to every row across all spaces. Use it to find a tab for `attach --tab-id`.

## Steps: open

1. `dbrowser open <url> [--browser B] --space S [--session NAME]`. Arc: the script takes `~/.dot/browser/lock`, records the DevTools targets, creates the tab in the space with the real URL (one AppleScript that also reads the user's active tab first and selects it again if Arc moved away from it), waits for a new target whose URL matches (prefix, then host for redirects; a tab the user opened meanwhile is never taken), writes the session, then waits for the page to finish loading and records its title and URL. Chrome / Edge: starts dot's instance if needed (`LAUNCHED`), creates a new window with the page (`Target.createTarget`), puts the previously frontmost app back if the window came to the front, and binds the session to that target directly.
2. Read `session`, `export_hint`, `space`, `tab{tab_id, target_id, url, title}`, `focused`, `restored`, `cdp`. Export the session name before the next command.
3. `cdp: false` (port closed) still creates the tab and the session, with `target_id: null` and a `CDP_UNREACHABLE` warning: page commands will not work until Arc is relaunched; `goto` / `close` will.
4. `TARGET_NOT_FOUND` in `warnings`: the tab exists but no matching target showed up in time (`candidates` lists unrelated new ones); `dbrowser attach --session NAME --tab-id ARC_ID` binds it later. `AMBIGUOUS_TARGET` in `warnings`: several matching targets appeared at once; the session was saved without a target; pick one from `candidates` and run the `attach … --tab-id … --target-id` line from the warning. `LOAD_UNKNOWN` / `LOAD_TIMEOUT`: the title and URL in the result may be stale; `dbrowser tabs --space S` shows the current ones. A `--session NAME` that already exists is refused (`SESSION_EXISTS`).
5. `--focus` switches the user's window to the space and raises the tab (Chrome / Edge: raises dot's window): only when the user wants to watch. `--no-wait` returns before the page finished loading.

### Done when

The result has `ok: true`, `tab.target_id` is set (or the user knows why not), and the user's active tab is what it was.

## Steps: attach

1. The user is "on" a page or already logged in somewhere: `dbrowser attach --active` binds the front window's active tab (Arc; dot's Chrome has no user-facing active tab, use `--tab-id` / `--url` there); `--tab-id ID` a tab from `dbrowser tabs --all`; `--url U` the tab at that URL (exact, then prefix; several → `AMBIGUOUS_TARGET` with `candidates`, pick with `--tab-id`).
2. The DevTools target is matched by the tab's URL; two targets at the same URL → `AMBIGUOUS_TARGET`, pass `--target-id` from `candidates`. A sleeping tab has no target: `TARGET_NOT_FOUND` warning; `dbrowser reload` on the session, then the next page command rebinds.
3. `space.source` is `active` or `tab`; `attach` never focuses anything.

## Steps: goto / back / forward / reload / close / sessions

- `dbrowser goto <url>`, `dbrowser back`, `dbrowser forward`, `dbrowser reload`: on the session's tab (Arc: AppleScript, then wait for `loading` to end; Chrome / Edge: `Page.navigate` and friends, then wait for the load event), `--no-wait` skips the wait, `LOAD_TIMEOUT` warns when the page is still loading after `--timeout`; the result carries the new `url` and `title`, and the session file is updated. These keep the DevTools target, so refs survive a `reload` only if the document did not change: take a new snapshot anyway.
- `dbrowser close`: closes the tab (Chrome / Edge: its window goes with it) and deletes the session; `--keep-tab` deletes only the session. A tab the user already closed is a warning, not an error.
- `dbrowser sessions`: every session with `browser`, `port`, `space`, `url`, `alive` (whether its target still exists; `null` when the port is closed) and `last_used`. A coordinating agent cleans up with it.

### Done when

`url` matches what was asked (allowing for redirects), or the error names the tab that is gone.

## Recipe for other tools

Chrome / Edge: `curl -X PUT http://127.0.0.1:9223/json/new?https://example.com`, `/json/list`, `/json/close/<id>`, or `Target.createTarget` over the browser websocket from `dbrowser endpoint`. Arc, without this script, in plain AppleScript (never store Arc objects in variables; always `front window`):

```applescript
tell application "Arc"
  get title of spaces of front window
  tell front window to tell (first space whose title is "agent") to make new tab with properties {URL:"https://example.com"}
  select (first tab of front window whose id is "<the user's tab id>")  -- Arc raised the new tab; put theirs back
end tell
```
