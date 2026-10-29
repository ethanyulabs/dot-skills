# Playwright compatibility

`dbrowser` is one process per command on raw CDP, which is what keeps a command at 0.1–1 s. Playwright would add a Node driver start and an attach to every open tab on every command (about two seconds), so it is not the engine here. Three things are kept compatible instead:

1. **Selectors** take Playwright's forms: `text=Sign in` (`getByText`), `role=button[name="Sign in"]` (`getByRole`: exact accessible name first, then "contains"), `css=…` / bare CSS, `xpath=…`. Refs `e12` from `snapshot` are the cheaper, exact alternative.
2. **Actionability**: `click` and `fill` resolve the element once (`ELEMENT_NOT_FOUND` when it is not there yet: `wait --selector` first), then wait until it has a rendered box and is not disabled, for up to `--timeout` (default 10 s), then `NOT_VISIBLE` / `ELEMENT_DISABLED`, like `locator.click()`.
3. **`dbrowser endpoint`** tells a real Playwright where to attach when a task is long and interactive enough to be worth the driver (many steps on one page, drag and drop, file uploads, network interception):

```json
{"http": "http://127.0.0.1:9222", "ws_browser": "ws://127.0.0.1:9222/devtools/browser/…",
 "target_id": "…", "ws_url": "ws://127.0.0.1:9222/devtools/page/…", "url": "https://…",
 "playwright": {"python": "…connect_over_cdp('http://127.0.0.1:9222')", "page": "…", "note": "…"}}
```

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")      # from endpoint.http
    page = next(pg for ctx in browser.contexts for pg in ctx.pages if pg.url == URL)  # from endpoint.url
    # or match the exact tab: ctx.new_cdp_session(pg).send("Target.getTargetInfo")["targetInfo"]["targetId"] == endpoint.target_id
    page.get_by_role("button", name="Sign in").click()
```

Rules when doing that: run it with `uv run --with playwright python …` (Playwright is not a dependency of this skill and `playwright install` is not needed for `connect_over_cdp`); keep working in the session's own tab, never `browser.close()` (it would close the user's Arc or dot's instance; disconnect instead); on Arc never bring tabs to the front; `dbrowser close` the session afterwards as usual. `connect_over_cdp` is Chromium-only and, per Playwright's docs, lower fidelity than its own protocol: if something misbehaves there, fall back to `dbrowser` commands rather than fighting it.
