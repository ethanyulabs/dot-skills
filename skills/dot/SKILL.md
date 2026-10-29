---
name: dot
description: Personal toolbox, one subcommand per directory, run as /dot subcommand action … (Codex $dot …); a request without a subcommand is matched to one. photo processes JPEG / PNG / TIFF / HEIC photos, one or a whole folder, with a bundled uv Python script, outputs and user defaults in ~/.dot/photo, as style (extract and apply a JSON style), portrait (skin retouch that keeps pores), landscape (depth, dehaze), export (print 300 ppi, web 2048 px, dating-app 1:1 and 4:5) and run (all of it). browser drives the user's browser on macOS, either Arc in a named space with their logins or dot's own Chrome / Edge instance (open, snapshot, click, fill, screenshot, extract). Trigger on Arc, Chrome, Edge, 浏览器, 打开网页, Arc 空间, "open in Chrome", "in the X space". Also trigger on /dot, $dot, 修图, 批量修图, 磨皮, 人像精修, 去瑕疵, 风景调色, 风景层次, 提取风格, 套用风格, 导出打印, 交友软件头像, "retouch this photo", "apply this look", "export for print", "process this folder", even if they don't name this skill.
license: MIT
metadata:
  version: "0.6.0"
  compatibility: "Any agent that can read files and run shell commands. Each subcommand states its own requirements at the top of its COMMAND.md (photo needs uv and a network connection on first run; browser needs macOS and uv, plus Arc started with its DevTools port or Chrome / Edge, which it launches itself)."
---

# dot: one entry, one directory per subcommand

Usage: `/dot <subcommand> <action> [args]` (Codex: `$dot <subcommand> …`), or plain language such as "把这张人像磨一下皮", "把这个文件夹里的照片都处理一下", "在 byted 空间打开这个链接", "用 Chrome 打开这个页面". Without a subcommand, step 2 picks one from the request. Every subcommand lives in its own directory under this skill, with `COMMAND.md` as its entry: the same Usage / Actions / Steps / Done when shape as a SKILL.md, without frontmatter. The user's own things (saved presets, default parameters, outputs) live under `~/.dot/<subcommand>/`, never next to their files; `DOT_HOME` moves the `~/.dot` root.

## Subcommands

| Subcommand | Invocation | What it does | The user wants to | Read |
|---|---|---|---|---|
| `photo` | `/dot photo <action> <photo\|folder> [options]`, actions `style` / `portrait` / `landscape` / `export` / `run` / `config` | photo style processing by a bundled uv Python script: extract and apply a JSON style, portrait skin retouch that keeps texture, landscape depth, print / web / dating-app exports, one photo or a whole folder | retouch, smooth skin, remove blemishes, add depth to a landscape, copy a look, save a look, export for print / web / a dating app, process a folder of photos; 修图 / 磨皮 / 精修 / 风景层次 / 调色 / 提取或套用风格 / 导出 / 批量 | `photo/COMMAND.md` |
| `browser` | `/dot browser <action> [args]`, actions `selftest` / `launch` / `quit` / `spaces` / `tabs` / `open` / `attach` / `goto` / `back` / `forward` / `reload` / `close` / `sessions` / `snapshot` / `click` / `fill` / `press` / `wait` / `screenshot` / `extract` / `eval` / `endpoint` / `config` | drives a browser through the Chrome DevTools Protocol: the user's Arc in a named space (AppleScript for spaces and tabs, their logged-in sessions, never touching the space or tab they are looking at) or dot's own Chrome / Edge instance with a dedicated profile, one window per session; default browser and default space are configurable; several agents can work side by side | open a page in Arc / Chrome / Edge, in space X, read / click / fill / screenshot a page they are logged into, grab a page with their Arc login, use Chrome instead of Arc; 用 Arc / Chrome 打开 / 在某个空间 / 看一下这个页面 / 用登录态抓页面 / 默认浏览器 | `browser/COMMAND.md` |

## Steps

1. **Orient.** `SKILL_DIR` is the directory of this file (`~/.claude/skills/dot`, `~/.agents/skills/dot`, or `dot-skills/skills/dot` in a checkout). Every subcommand's files are under `$SKILL_DIR/<subcommand>/`.
2. **Pick the subcommand**, in this order:
   - The user named one (`/dot photo …`, `$dot photo …`): use it; the words after it are that subcommand's action and arguments.
   - Plain language: match the request against the "The user wants to" column. One match: take it without asking. Several or none: ask the user once, naming the candidates.
3. **Read `$SKILL_DIR/<subcommand>/COMMAND.md`** and follow it from its first step to its "Done when". Every relative path it names (`references/…`, `scripts/…`, `assets/…`) is relative to `$SKILL_DIR/<subcommand>/`.

## Done when

- The subcommand's own "Done when" holds, or the user knows exactly what blocks it.
- Nothing was written next to the user's files; the user's originals are untouched; no commit was made.
