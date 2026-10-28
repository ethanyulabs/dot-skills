---
name: dot
description: Personal toolbox, one subcommand per directory, run as /dot subcommand action … (Codex $dot …); a request without a subcommand is matched to one. photo processes JPEG / PNG / TIFF / HEIC photos, one or a whole folder, with a bundled uv Python script, outputs and user defaults in ~/.dot/photo, as style (extract and apply a JSON style), portrait (skin retouch that keeps pores), landscape (depth, dehaze), export (print 300 ppi, web 2048 px, dating-app 1:1 and 4:5) and run (all of it). arc drives the user's Arc browser (macOS) in a named Arc space, reusing their logged-in sessions (spaces, open, snapshot, click, fill, screenshot, extract). Trigger on Arc, Arc 空间, 打开网页, 用 Arc 打开, 浏览器操作, "open in Arc", "in the X space". Also trigger on /dot, $dot, 修图, 批量修图, 磨皮, 人像精修, 去瑕疵, 风景调色, 风景层次, 提取风格, 套用风格, 导出打印, 交友软件头像, "retouch this photo", "apply this look", "export for print", "process this folder", even if they don't name this skill.
license: MIT
metadata:
  version: "0.5.0"
  compatibility: "Any agent that can read files and run shell commands. Each subcommand states its own requirements at the top of its COMMAND.md (photo needs uv and a network connection on first run; arc needs macOS, Arc and uv)."
---

# dot: one entry, one directory per subcommand

Usage: `/dot <subcommand> <action> [args]` (Codex: `$dot <subcommand> …`), or plain language such as "把这张人像磨一下皮", "把这个文件夹里的照片都处理一下", "在 byted 空间打开这个链接". Without a subcommand, step 2 picks one from the request. Every subcommand lives in its own directory under this skill, with `COMMAND.md` as its entry: the same Usage / Actions / Steps / Done when shape as a SKILL.md, without frontmatter. The user's own things (saved presets, default parameters, outputs) live under `~/.dot/<subcommand>/`, never next to their files; `DOT_HOME` moves the `~/.dot` root.

## Subcommands

| Subcommand | Invocation | What it does | The user wants to | Read |
|---|---|---|---|---|
| `photo` | `/dot photo <action> <photo\|folder> [options]`, actions `style` / `portrait` / `landscape` / `export` / `run` / `config` | photo style processing by a bundled uv Python script: extract and apply a JSON style, portrait skin retouch that keeps texture, landscape depth, print / web / dating-app exports, one photo or a whole folder | retouch, smooth skin, remove blemishes, add depth to a landscape, copy a look, save a look, export for print / web / a dating app, process a folder of photos; 修图 / 磨皮 / 精修 / 风景层次 / 调色 / 提取或套用风格 / 导出 / 批量 | `photo/COMMAND.md` |
| `arc` | `/dot arc <action> [args]`, actions `spaces` / `tabs` / `open` / `attach` / `snapshot` / `click` / `fill` / `press` / `wait` / `screenshot` / `extract` / `eval` / `close` / `sessions` / `config` | drives the user's Arc browser in a named Arc space, AppleScript for spaces and tabs, Chrome DevTools Protocol for the page, with the user's logged-in sessions and without touching the space or tab they are looking at; several agents can work side by side | open a page in Arc, in space X, read / click / fill / screenshot a page they are logged into, grab a page with their Arc login; 用 Arc 打开 / 在某个空间 / 看一下这个页面 / 用登录态抓页面 | `arc/COMMAND.md` |

## Steps

1. **Orient.** `SKILL_DIR` is the directory of this file (`~/.claude/skills/dot`, `~/.agents/skills/dot`, or `dot-skills/skills/dot` in a checkout). Every subcommand's files are under `$SKILL_DIR/<subcommand>/`.
2. **Pick the subcommand**, in this order:
   - The user named one (`/dot photo …`, `$dot photo …`): use it; the words after it are that subcommand's action and arguments.
   - Plain language: match the request against the "The user wants to" column. One match: take it without asking. Several or none: ask the user once, naming the candidates.
3. **Read `$SKILL_DIR/<subcommand>/COMMAND.md`** and follow it from its first step to its "Done when". Every relative path it names (`references/…`, `scripts/…`, `assets/…`) is relative to `$SKILL_DIR/<subcommand>/`.

## Done when

- The subcommand's own "Done when" holds, or the user knows exactly what blocks it.
- Nothing was written next to the user's files; the user's originals are untouched; no commit was made.
