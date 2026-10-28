# Screenshot, extract, eval

## Inputs

| Input | Used for | When missing |
|---|---|---|
| session | all three | `NO_SESSION` |
| `--out PATH` | where the PNG / text goes | `~/.dot/arc/output/<session>/<stamp>-screenshot.png`, `extract-<stamp>.txt`, `eval-<stamp>.txt` |
| `--target ref\|selector` | `screenshot`: clip to one element | the viewport (`--full`: the whole page) |
| `--what text\|links\|html\|title`, `--root <ref\|selector>` | `extract` | `text` of `body` |
| JavaScript expression | `eval` | `BAD_ARGS` |

## Steps: screenshot

1. `darc screenshot` captures the viewport of the session's tab as PNG and returns `path`, `width`, `height`, `activated: false`. Open `path` with the Read tool and say what you see; never describe a screenshot you did not open.
2. `--full` captures the whole scrollable page; `--target e12` only that element; `--out` picks the file.
3. `SCREENSHOT_NEEDS_FOREGROUND` (exit 5): the tab is in the background and Chromium did not render it within 3 s. First choice: read the page with `extract` or `eval`, which do not need a visible tab. If the user needs the picture and agreed that Arc may flash: `darc screenshot --activate` raises the tab, captures, and selects the user's tab again (`activated: true`). A user who keeps a second Arc window on the agent's space never hits this.

### Done when

The PNG was opened with Read and the report says what it shows.

## Steps: extract

1. `darc extract` returns the page's visible text (`innerText`) as `text`; `--what links` returns `links[{text, href}]`; `--what html` the outer HTML; `--what title` the title. `--root css=main` (or a ref from the last snapshot, or `xpath=` / `text=`) limits it to one element (`ELEMENT_NOT_FOUND` when it matches nothing, `REF_STALE` for an old ref).
2. Long results: `--max-chars` (default 30000) truncates what is printed and writes the full text to `path` (`truncated: true`); `--out FILE` always writes the file.

### Done when

The text needed for the answer is in the result or in the file named by `path`.

## Steps: eval

1. `darc eval "document.querySelectorAll('tr').length"` runs the expression in the page (promises are awaited) and returns `result` as JSON. Strings, numbers, arrays and plain objects come back; DOM nodes do not (map them to values first).
2. Results over 4000 characters go to `result_path` instead (`result: null`); `--out FILE` chooses the file.
3. An exception in the page is `ACTION_FAILED` with the first line of the error.

### Done when

`result` holds the value, or the error names the JavaScript problem.

## Recipe for other tools

Chrome DevTools: `Page.captureScreenshot`, `Runtime.evaluate` with `returnByValue`. The same results are available in any CDP client once Arc runs on `--remote-debugging-port`.
