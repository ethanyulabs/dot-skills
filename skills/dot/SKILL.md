---
name: dot
description: Personal toolbox, one subcommand per directory, run as /dot subcommand action … (Codex $dot …); a request without a subcommand is matched to one. photo processes JPEG / PNG / TIFF / HEIC photos, one or a whole folder, with a bundled uv Python script, outputs and user defaults in ~/.dot/photo, as style (extract and apply a JSON style), portrait (skin retouch that keeps pores), landscape (depth, dehaze), export (print 300 ppi, web 2048 px, dating-app 1:1 and 4:5) and run (all of it). Trigger on /dot, $dot, 修图, 批量修图, 磨皮, 人像精修, 去瑕疵, 风景调色, 风景层次, 提取风格, 套用风格, 导出打印, 交友软件头像, "retouch this photo", "apply this look", "export for print", "process this folder", even if they don't name this skill.
license: MIT
metadata:
  version: "0.4.0"
  compatibility: "Any agent that can read files and run shell commands. Each subcommand states its own requirements at the top of its COMMAND.md (photo needs uv and a network connection on first run)."
---

# dot: one entry, one directory per subcommand

Usage: `/dot <subcommand> <action> [args]` (Codex: `$dot <subcommand> …`), or plain language such as "把这张人像磨一下皮", "把这个文件夹里的照片都处理一下". Without a subcommand, step 2 picks one from the request. Every subcommand lives in its own directory under this skill, with `COMMAND.md` as its entry: the same Usage / Actions / Steps / Done when shape as a SKILL.md, without frontmatter. The user's own things (saved presets, default parameters, outputs) live under `~/.dot/<subcommand>/`, never next to their files; `DOT_HOME` moves the `~/.dot` root.

## Subcommands

| Subcommand | Invocation | What it does | The user wants to | Read |
|---|---|---|---|---|
| `photo` | `/dot photo <action> <photo\|folder> [options]`, actions `style` / `portrait` / `landscape` / `export` / `run` / `config` | photo style processing by a bundled uv Python script: extract and apply a JSON style, portrait skin retouch that keeps texture, landscape depth, print / web / dating-app exports, one photo or a whole folder | retouch, smooth skin, remove blemishes, add depth to a landscape, copy a look, save a look, export for print / web / a dating app, process a folder of photos; 修图 / 磨皮 / 精修 / 风景层次 / 调色 / 提取或套用风格 / 导出 / 批量 | `photo/COMMAND.md` |

## Steps

1. **Orient.** `SKILL_DIR` is the directory of this file (`~/.claude/skills/dot`, `~/.agents/skills/dot`, or `dot-skills/skills/dot` in a checkout). Every subcommand's files are under `$SKILL_DIR/<subcommand>/`.
2. **Pick the subcommand**, in this order:
   - The user named one (`/dot photo …`, `$dot photo …`): use it; the words after it are that subcommand's action and arguments.
   - Plain language: match the request against the "The user wants to" column. One match: take it without asking. Several or none: ask the user once, naming the candidates.
3. **Read `$SKILL_DIR/<subcommand>/COMMAND.md`** and follow it from its first step to its "Done when". Every relative path it names (`references/…`, `scripts/…`, `assets/…`) is relative to `$SKILL_DIR/<subcommand>/`.

## Done when

- The subcommand's own "Done when" holds, or the user knows exactly what blocks it.
- Nothing was written next to the user's files; the user's originals are untouched; no commit was made.

## Adding a subcommand (for whoever edits this skill)

1. Create `skills/dot/<sub>/COMMAND.md` with Usage, an Actions table, Steps and Done when; put its `references/`, `scripts/` and `assets/` beside it, and keep its user data under `~/.dot/<sub>/`. Do not put a `SKILL.md` in that directory: skill installers treat a nested `SKILL.md` as a separate skill or shadow it.
2. Add one row to the Subcommands table above, and one row to the table in the repository `README.md`.
3. Add one sentence for it to the `description` in the frontmatter: at most 250 characters, with up to 8 trigger words; the whole description must stay under 1024 characters (the validator's limit).
4. `python3 ~/.claude/skills/skill-creator/scripts/quick_validate.py skills/dot` passes, and the subcommand's own tests are green.
