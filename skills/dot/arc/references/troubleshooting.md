# Troubleshooting

| Code | What it means | What to do |
|---|---|---|
| `CDP_UNREACHABLE` (exit 4) | Arc is running without `--remote-debugging-port` | give the user the `relaunch` command from `selftest` (quit Arc, `open -a Arc --args --remote-debugging-port=9222`), then `selftest` again; AppleScript commands keep working meanwhile |
| `CDP_CONNECT_FAILED` with 403 / origin | Chromium rejected the websocket handshake | relaunch with `--remote-debugging-port=9222 --remote-allow-origins=*` |
| `AUTOMATION_DENIED` (exit 4) | macOS did not allow this process to send Apple events to Arc | 系统设置 → 隐私与安全性 → 自动化：给运行 darc 的终端 / 应用勾上 Arc；第一次会弹窗，让用户点"允许"后重试 |
| `ARC_NOT_RUNNING` | Arc is not running (the script never launches it, because that would open a window the user did not ask for) | ask the user to start Arc, ideally with the port flag |
| `NO_WINDOW` | Arc has no main window (only Little Arc, or all windows closed) | ask the user to open a window (⌘N); the script never creates tabs at the application level because those become Little Arc popups |
| `SPACE_REQUIRED` / `SPACE_NOT_FOUND` | no space named and none configured / no space with that title | ask once from `spaces`; offer `config set space=…` only when the user wants a default; `--space id:<uuid>` for duplicate titles |
| `LOCK_TIMEOUT` | another `open` has held `~/.dot/arc/lock` for more than the timeout | wait and retry; delete the lock only when no darc process is running |
| `TARGET_NOT_FOUND` / `AMBIGUOUS_TARGET` (warnings on `open`) | no DevTools target matched the URL in time / several did; a tab the user opened at the same moment is never taken | `attach --session N --tab-id ARC_ID [--target-id T]`; the Arc tab and the session exist either way |
| `INVALID_URL` | Arc's `make new tab` refused the URL (`data:` and other non-web schemes); the space was switched and switched back inside the script | use an http(s) or file URL |
| `SESSION_EXISTS` | `--session NAME` is already in use (maybe by another agent) | `darc close --session NAME` if it is yours, else another name |
| `TARGET_GONE` | the tab is in Arc but exposes no DevTools target even after a background reload (asleep, archived, or a non-web page) | ask the user to click the tab once in Arc, then `attach --session N --tab-id ARC_ID`; or open the page again |
| `TAB_GONE` | the session's tab no longer exists | `open` again; `close --keep-tab` forgets the session |
| `REF_STALE` | the page navigated or the element disappeared since the snapshot | `snapshot` again; chain actions with `--snapshot` |
| `ELEMENT_NOT_FOUND` / `NOT_VISIBLE` | selector matched nothing / the element has no rendered box | snapshot and pick a ref; look for the control that reveals a collapsed element |
| `SCREENSHOT_NEEDS_FOREGROUND` | Chromium did not render the background tab | use `extract` / `eval`; `--activate` only with the user's agreement; a second Arc window on the agent's space makes screenshots work without any switching |
| `OSA_ERROR` containing `-1700` | an AppleScript object reference could not be resolved (Arc's known quirk when an object is stored in a variable or returned from `make`) | this is a bug in the script text, not the page: report it with the message; the shipped scripts use inline specifiers only |
| `OSA_TIMEOUT` | Arc did not answer AppleScript in time | Arc may be showing a modal dialog; look at it, then retry |
| `WAIT_TIMEOUT` | the condition did not hold within `--timeout` | snapshot or screenshot to see where the page actually is |
| `CONFIG_INVALID` | `config.json` is not valid JSON | fix or delete it; the script never overwrites a broken file |

Other things worth knowing:

- Spaces belong to the Arc profile, not the window: every window lists the same spaces; `active space` is per window and the script always talks to the front window.
- `tabs of front window` is every tab in every space, which is why tab ids are unique and `attach --tab-id` works across spaces.
- Arc switches the front window to a tab it just created; `open` undoes that in the same script (`restored: true`), which the user sees as a flicker of well under a second, if at all.
- Right after a relaunch no tab is loaded (DevTools lists no page target) and the front window may have no active tab; `open` then restores the user's space rather than a tab. Arc renders background tabs for `Page.captureScreenshot`, so `SCREENSHOT_NEEDS_FOREGROUND` is rare in practice (verified on Arc 1.152).
- Arc lets background tabs sleep after a while; their DevTools target disappears and comes back on reload. The script reloads in the background before giving up (`rebound: true`).
- The DevTools port is loopback-only but unauthenticated: any local process can use it while Arc runs with the flag. Recommend a normal relaunch of Arc after the task.
