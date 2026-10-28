# Spaces, tabs and sessions

## Inputs

| Input | Used for | When missing |
|---|---|---|
| space title, or `id:<uuid>` | `open`, `tabs`; `--space` on any command | the configured default; else `SPACE_REQUIRED` with the list of spaces: ask once |
| URL (http, https or file; Arc refuses `data:` URLs with `INVALID_URL`) | `open`, `goto`, `attach --url` | `BAD_ARGS` |
| session name | every command after `open` / `attach`, via `--session` or `DOT_ARC_SESSION` | `open` makes one up; others fail with `NO_SESSION` |

## Steps: spaces / tabs

1. `darc spaces` lists `spaces[{title, id, tabs, active}]`, `active`, `windows` and `default_space`. Two spaces with the same title give `SPACE_TITLE_DUPLICATE` in `warnings`; address them with `--space id:<uuid>`.
2. `darc tabs --space S` lists `tabs[{id, title, url, location, active}]` (`location`: `pinned`, `unpinned`, `topApp`); `--all` adds `space` to every row across all spaces. Use it to find a tab for `attach --tab-id`.

## Steps: open

1. `darc open <url> --space S [--session NAME]`. The script takes `~/.dot/arc/lock`, records the DevTools targets, creates the tab in the space with the real URL (one AppleScript that also reads the user's active tab first and selects it again if Arc moved away from it), waits for a new target whose URL matches (prefix, then host for redirects; a tab the user opened meanwhile is never taken), writes the session, then waits for the page to finish loading and records its title and URL.
2. Read `session`, `export_hint`, `space`, `tab{arc_id, target_id, url, title}`, `focused`, `restored`, `cdp`. Export the session name before the next command.
3. `cdp: false` (port closed) still creates the tab and the session, with `target_id: null` and a `CDP_UNREACHABLE` warning: page commands will not work until Arc is relaunched; `goto` / `close` will.
4. `TARGET_NOT_FOUND` in `warnings`: the tab exists but no matching target showed up in time (`candidates` lists unrelated new ones); `darc attach --session NAME --tab-id ARC_ID` binds it later. `AMBIGUOUS_TARGET` in `warnings`: several matching targets appeared at once; the session was saved without a target; pick one from `candidates` and run the `attach … --tab-id … --target-id` line from the warning. `LOAD_UNKNOWN` / `LOAD_TIMEOUT`: the title and URL in the result may be stale; `darc tabs --space S` shows the current ones. A `--session NAME` that already exists is refused (`SESSION_EXISTS`).
5. `--focus` switches the user's window to the space and raises the tab: only when the user wants to watch. `--no-wait` returns before the page finished loading.

### Done when

The result has `ok: true`, `tab.target_id` is set (or the user knows why not), and the user's active tab is what it was.

## Steps: attach

1. The user is "on" a page or already logged in somewhere: `darc attach --active` binds the front window's active tab; `--tab-id ID` a tab from `darc tabs --all`; `--url U` the tab at that URL (exact, then prefix; several → `AMBIGUOUS_TARGET` with `candidates`, pick with `--tab-id`).
2. The DevTools target is matched by the tab's URL; two targets at the same URL → `AMBIGUOUS_TARGET`, pass `--target-id` from `candidates`. A sleeping tab has no target: `TARGET_NOT_FOUND` warning; `darc reload` on the session, then the next page command rebinds.
3. `space.source` is `active` or `tab`; `attach` never focuses anything.

## Steps: goto / back / forward / reload / close / sessions

- `darc goto <url>`, `darc back`, `darc forward`, `darc reload`: AppleScript on the session's tab, then wait for `loading` to end (`--no-wait` skips the wait); the result carries the new `url` and `title`, and the session file is updated. These keep the DevTools target, so refs survive a `reload` only if the document did not change: take a new snapshot anyway.
- `darc close`: closes the tab and deletes the session; `--keep-tab` deletes only the session. A tab the user already closed is a warning, not an error.
- `darc sessions`: every session with `space`, `url`, `alive` (whether its target still exists; `null` when the port is closed) and `last_used`. A coordinating agent cleans up with it.

### Done when

`url` matches what was asked (allowing for redirects), or the error names the tab that is gone.

## Recipe for other tools

Without this script, the same thing in plain AppleScript (never store Arc objects in variables; always `front window`):

```applescript
tell application "Arc"
  get title of spaces of front window
  tell front window to tell (first space whose title is "agent") to make new tab with properties {URL:"https://example.com"}
  select (first tab of front window whose id is "<the user's tab id>")  -- Arc raised the new tab; put theirs back
end tell
```
