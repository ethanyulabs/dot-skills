# Snapshot, click, fill, press, wait

## Inputs

| Input | Used for | When missing |
|---|---|---|
| session | every command here | `NO_SESSION` |
| a ref `e12` from the last snapshot, or a selector `css=…` / bare CSS / `xpath=…` / `text=…` | `click`, `fill`, `press --target`, `screenshot --target`, `snapshot --root` | `BAD_ARGS` |
| text | `fill` | `BAD_ARGS`; an empty string clears the field |
| key | `press`: `Enter`, `Tab`, `Escape`, `Backspace`, `Delete`, `ArrowUp/Down/Left/Right`, `Home`, `End`, `PageUp`, `PageDown`, `Space`, `F5`, one character, with `Meta+` / `Ctrl+` / `Alt+` / `Shift+` | `BAD_ARGS` |

## Steps: snapshot

1. `darc snapshot` prints the page outline, one node per line, indented by nesting:

   ```
   - heading "Example Domain" [level=1] [ref=e1]
   - paragraph: This domain is for use in illustrative examples.
   - form:
     - textbox "Search" [active] [ref=e3]
     - checkbox "Remember" [checked] [ref=e4]
     - button "Go" [ref=e5]
   - iframe "ad" [ref=e6] [cross-origin content not included]
   ```

   `[ref=eN]` marks what can be acted on; `[active]` the focused element; `[checked]`, `[disabled]`, `[expanded]`, `[selected]`, `[pressed]` the state; a textbox's current value follows the colon. Generic wrappers are flattened away; hidden (`aria-hidden`, `display:none`) nodes do not appear.
2. Large pages: `--root css=main` (any selector or ref) limits the outline to a subtree; `--depth 2` hides deeper levels (shown as `…`); `--max-chars` (default 30000) truncates the printed text, the full outline is always in `snapshot_path`. `--boxes` appends `[box=x,y,w,h]` to every ref (slower).
3. The result carries `url`, `title`, `ref_count`, `truncated`, `snapshot_path`. The refs are stored in the session; `rebound: true` means the tab had to be reloaded to get a DevTools target first.

### Done when

The outline shows the element you need, with a ref, or you know it is inside a cross-origin iframe (then the user has to do that step).

## Steps: click / fill / press

1. `darc click e12` scrolls the element into view, dispatches a real mouse click at its center, waits up to two seconds for a navigation (`darc wait --url` afterwards when a slow cross-site load matters), and returns `url_after`, `title_after`, `navigated`, plus the `ref`, `role`, `name` it acted on (or `selector`). `--double`, `--button right`.
2. `darc fill e7 "text"` focuses the field, selects its content and inserts the text through the browser's input path (frameworks see a normal input event); `--press Enter` submits afterwards. `fill` with `""` clears the field.
3. `darc press Enter` / `darc press Meta+a` sends a key to the focused element; `--target e7` focuses that element first. Cmd shortcuts (`Meta+a/c/v/x/z`) also carry the editing command, because macOS Chromium handles them outside the page.
4. Add `--snapshot` to any of them to get the outline after the action in the same result (`snapshot`, `ref_count`, …): the next ref you use is then always from the current page.
5. Errors: `REF_STALE` (page navigated or the node is gone: snapshot again), `ELEMENT_NOT_FOUND` (selector matched nothing), `NOT_VISIBLE` (no rendered box: hidden, collapsed, or off-screen in a way scrolling cannot fix; snapshot again and look for the control that reveals it), `CDP_ERROR` (the browser refused the call; the message says why).

### Done when

`navigated` or the fresh snapshot shows the expected change; otherwise at most two retries with a different ref or selector, then `screenshot` and look.

## Steps: wait

`darc wait --url "https://*/dashboard*"` (glob on the full URL), `--selector css`, `--text "Welcome"`, `--load load|domcontentloaded`, `--ms 500`; several conditions must all hold. Polls every 100 ms until `--timeout` (default 10000 ms) → `WAIT_TIMEOUT` with the URL the page is at. Use it after a submit and before the next snapshot.

## Recipe for other tools

Playwright users: `snapshot` ≈ `page.locator("body").ariaSnapshot()`, `click e12` ≈ `getByRole(role, {name}).click()`, `fill` ≈ `locator.fill()`, `wait --url` ≈ `page.waitForURL()`. The refs here are backendDOMNodeIds over raw CDP (`DOM.scrollIntoViewIfNeeded`, `DOM.getContentQuads`, `Input.dispatchMouseEvent`, `Input.insertText`, `Input.dispatchKeyEvent`).
