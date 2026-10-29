# Browsers: what differs, what dot does about it

## The three adapters

| | Arc (`arc`) | Chrome (`chrome`) | Edge (`edge`) |
|---|---|---|---|
| bundle id | `company.thebrowser.Browser` | `com.google.Chrome` | `com.microsoft.edgemac` |
| isolation | **space**: the user's own Arc, one named space per task | **instance**: dot's own Chrome with a dedicated profile | **instance**, same as Chrome |
| spaces / tabs driven by | Arc's AppleScript dictionary (`spaces`, `tabs`, `focus`, `select`) | CDP `Target.*` on the browser websocket; no AppleScript (two Chrome instances share one bundle id, so `tell application "Google Chrome"` would address an arbitrary one) | same as Chrome |
| pages driven by | CDP, one websocket per command | CDP | CDP |
| default DevTools port | 9222 | 9223 | 9224 |
| who starts it | the user: quit Arc, `open -a Arc --args --remote-debugging-port=9222` (`selftest` prints `launch.shell`); Arc accepts the flag on its default profile | dot: `dbrowser launch --browser chrome`, or `open` / `attach` / `tabs` by themselves (`LAUNCHED` warning), as `open -gna "Google Chrome" --args --user-data-dir=~/.dot/browser/profiles/chrome --remote-debugging-port=9223 --no-first-run --no-default-browser-check --disable-backgrounding-occluded-windows --disable-renderer-backgrounding`; `-g` keeps it in the background | same with `Microsoft Edge` and `profiles/edge` |
| logins | the user's own, in every space | dot's profile: the user logs in once in the dot window, cookies stay in the profile | same |
| where a session's tab lives | the named space, as a background tab; Arc renders background tabs, so screenshots work | **its own window** (`Target.createTarget newWindow`), because Chrome does not render a non-foreground tab; the launch flags keep a covered window rendering | same |
| what the user might see | a flicker when Arc raises the new tab and the script selects theirs back (`restored: true`) | a new Chrome window appearing on the desktop (it may come to the front once; the script puts the previous app back through System Events, by pid, `restored: true`; needs the Automation permission for System Events, which `selftest` checks) | same |
| `--focus` / `--activate` | switch Arc to the space / raise the tab, then back | raise dot's window, then put the previous app back | same |
| `quit` | not available (`BAD_ARGS`): the user's Arc is theirs | `Browser.close` over CDP, or `pkill` on the profile path when the port is dead | same |
| verified on | Arc 1.152 / Chrome 149, 2026-10-28 | Chrome 149, 2026-10-28 | **not tested** (no Edge on the development machine); it shares every line of code with Chrome |

Not supported: Safari and Firefox (no DevTools protocol to attach to a running instance; Playwright cannot either). When the system's default browser is one of these and nothing is configured, every command fails with `BROWSER_UNSUPPORTED` listing the installed supported ones.

## Why Chrome / Edge get a dedicated profile

Since Chrome 136 (April 2025) `--remote-debugging-port` is ignored on the default user-data directory ("DevTools remote debugging requires a non-default data directory"); Edge is the same engine. So the user's everyday Chrome profile cannot be attached to, and the only way to reuse logins is a profile dot owns, where the user logs in once. Chrome 144 added a consent-based attach mode in `chrome://inspect/#remote-debugging`; whether raw CDP can use it is unverified, and it is not used here.

## Choosing the browser

Order, for a command without a session: `--browser` (source `flag`); `config.browser` (`config`); the system's https handler from LaunchServices (`system`; bundle ids are compared case-insensitively because the plist stores them in lower case). A command on a session uses the session's browser and port (`session`); a different `--browser` is `BAD_ARGS`. The port: `--port`, then the session's, then `config.<browser>.port`, then the browser's default.

`dbrowser selftest` resolves the browser and reports it (`browser: {key, source, display_name, isolation}`) before anything else; `config` and `sessions` never need a browser, so they keep working when the default is unsupported.

## Running two browsers at once

Ports differ by default, sessions carry their browser, and the profiles are separate directories, so an agent can hold an Arc session and a Chrome session in the same shell: pass `--session` on every command (or export `DOT_BROWSER_SESSION` before switching). `dbrowser sessions` lists both with their `browser` column.
