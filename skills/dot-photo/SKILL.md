---
name: dot-photo
description: Photo style processing in five actions, run by a bundled Python script (uv) on JPEG / PNG / TIFF / HEIC, one photo or a whole folder (batch), with ~/.dot/photo for user styles, defaults and outputs. style extracts a JSON style file (tone, white balance, HSL, grade, effects) from a reference photo and applies one to another photo; portrait removes skin blemishes and smooths skin while keeping pores and texture (frequency separation inside a skin mask, eyes and lips excluded); landscape builds depth (black and white points, dehaze, far/near bands, midtone local contrast); export writes print (300 ppi), web (2048 px, no EXIF) and dating-app (1:1 and 4:5, face-anchored, natural look) versions; run chains analysis, type processing and all exports. Trigger on /dot-photo, $dot-photo, 修图, 批量修图, 磨皮, 人像精修, 去瑕疵, 风景调色, 风景层次, 照片风格, 提取风格, 套用风格, 导出打印, 网页版照片, 交友软件头像, 约会软件照片, "retouch this photo", "smooth the skin", "export for print", "dating profile photo", "process this folder", even if they don't name this skill.
license: MIT
metadata:
  version: "0.3.0"
  compatibility: "Needs uv (https://docs.astral.sh/uv/) and a network connection the first time: scripts/dphoto.py declares its dependencies inline (pillow, pillow-heif, numpy, opencv-contrib-python-headless 4.x) and uv downloads about 100 MB into its cache. macOS, Linux and Windows; HEIC decoding falls back to sips on macOS."
---

# dot-photo: analyze the style → process by type → export every version

Usage: `/dot-photo <action> <photo|folder> [options]` (Codex: `$dot-photo …`), or plain language such as "把这张人像磨一下皮", "这张风景层次拉一下", "把 A 的风格套到 B 上", "出一版打印的和一版交友软件用的", "把这个文件夹里的照片都处理一下". Without an action, step 2 picks one from the request. A folder instead of a photo runs the action on every photo in it (recursive by default, `--no-recursive` to stay at the top level, `--skip-existing` to resume), one after another; `style extract` and `compare` take one photo only. The user's home `~/.dot/photo/` (`DOT_HOME` moves the `~/.dot` root) holds their saved styles, their default parameters (`config.json`, managed with `config`) and every output.

The script does every deterministic step (decode, color management, statistics, masks, filters, crops, writes); you read its JSON, look at `compare.jpg`, decide the strength, and report in Chinese. The rules that hold for every action are in `references/principles.md`. Nothing here modifies the original photo and nothing is written next to it: every output goes to `~/.dot/photo/output/<stem>-<hash>/` (`hash` = first 8 hex of the file's sha1, so two `IMG_0001.jpg` from different folders never collide and the same photo always lands in the same directory; `source.json` there records the original path), or to `--out DIR`. A folder run puts each photo there too and its `batch.json`, `log.txt` and contact sheet `contact.jpg` in `~/.dot/photo/runs/<stamp>-<folder>/` (`references/principles.md`, Folder input and Home directory).

## Actions

| Action | Invocation | What it does | Read |
|---|---|---|---|
| `style` | `/dot-photo style extract <photo> [--name N [--force]]` / `/dot-photo style apply <photo> --style <file\|preset\|user style> [--strength 0..1] [--mode hybrid\|params\|match]` / `/dot-photo style list` | extract: analyze the photo and write `style.json` with per-field confidence, and with `--name` save it as a user style in `~/.dot/photo/styles/`; apply: put a style file, a built-in preset (`neutral`, `clean-portrait`, `film-warm`, `dating-safe`) or a user style on another photo, matching tone and white balance against that photo's own analysis in `hybrid` mode; list: every preset and user style | `references/style.md` |
| `portrait` | `/dot-photo portrait <photo> [--skin-strength 0.55] [--blemish on\|off] [--remove-moles] [--eye-sharpen 0.3] [--face N\|x,y,w,h] [--style clean-portrait\|none]` | face detection → skin mask (eyes, lips excluded) → blemish inpainting (moles kept) → low-band smoothing with the high band put back untouched → eye sharpening | `references/portrait.md` |
| `landscape` | `/dot-photo landscape <photo> [--black 0.5 --white 99.5] [--dehaze 0.15] [--far-clarity -15 --near-texture 20] [--clahe 2.5] [--sky on --sky-darken 0.15] [--orton 0] [--style neutral\|none]` | black/white points → sky and depth masks → dehaze → far negative clarity, near texture → CLAHE in the midtones → graduated sky → optional Orton glow | `references/landscape.md` |
| `export` | `/dot-photo export <photo\|processed.tif> [--for print,web,dating] [--paper 4x6\|5x7\|8x10\|A4] [--finish matte\|glossy] [--fit crop\|pad] [--tiff16]` | print at 300 ppi with output sharpening, web at 2048 px without EXIF, dating 1:1 and 4:5 with the face anchored and a natural look; specs in `assets/presets/export.json` | `references/export.md` |
| `run` | `/dot-photo run <photo> [--type auto\|portrait\|landscape\|generic] [--style …] [--for …]` plus any portrait / landscape / export option | analyze → classify → style → portrait or landscape → every export, one report | `references/run.md` |
| `config` | `/dot-photo config show` / `config set <portrait\|landscape\|export\|run> key=value …` / `config unset <section> [key]` | the user's default parameters in `~/.dot/photo/config.json`, applied below the command line by every later `portrait` / `landscape` / `export` / `run` (`run` takes all four sections); `show` also prints every home path | `references/principles.md`, Home directory |

Every action that changes pixels writes `processed.tif` (16-bit sRGB), `processed.jpg`, `compare.jpg`, `focus.jpg` (1:1), `report.json` and prints one JSON line (`references/principles.md`, Output contract).

## Steps

1. **Orient.** Read `references/principles.md` and follow its Step 0: set `SKILL_DIR`, define `dphoto` as `uv run --script <SKILL_DIR>/scripts/dphoto.py`, run `dphoto selftest`. The first run downloads dependencies; tell the user it takes a minute or two. `selftest` also prints `dot_home`, `user_styles` and `config_ok`; when the user has defaults, `dphoto config show` tells you what every later command will apply, and each result's `config_applied` says which of them it used: name those in the report as the user's own defaults, not as your choices.
2. **Pick the action**, in this order:
   - The user named one (`/dot-photo portrait …`): use it.
   - Plain language:

     | The user wants to | Action |
     |---|---|
     | smooth skin, remove blemishes, retouch a face, 磨皮 / 精修 / 去痘 | `portrait` |
     | more depth or layering in a landscape, dehaze, 层次 / 通透 | `landscape` |
     | copy the look of one photo onto another, save a look, 提取风格 / 套用风格 / 调色 | `style` (`--name` when they want to keep the look) |
     | "always do it this way", "from now on", 以后都这样, 默认参数 | `config set` with the option they just approved |
     | a print, web or dating-app version, 打印 / 发网上 / 头像 | `export` |
     | "do the whole thing", several of the above, or they just hand over a photo | `run` |

   - Unsure which photo type: `dphoto info <photo>` and read `suggested_type`; below confidence 0.75 ask the user once, with the reasons the script gives.
3. **Follow that action's file** from its first step to its "Done when", reading the references it names when it names them.
4. **Verify by looking.** Whenever the action wrote `compare.jpg`, open it and `focus.jpg` (true 1:1) with the Read tool and go through `references/review-checklist.md`. Then accept, re-run with adjusted options, or ask the user. At most two re-runs; a re-run may change several options, and the report names every option that changed and why (`--blemish off --skin-strength 0.4`). Never report a result you have not looked at.
   For a folder: open every page of `contact.jpg` (`contact-2.jpg`, …) and go through the checklist's Contact sheet section; open the single `compare.jpg` / `focus.jpg` only for photos whose `needs_review` is not empty or whose row looks wrong on the sheet. Re-run a single photo with the single-photo command and `--out <its out_dir>`; the batch is not re-run for one photo.
5. **Report in Chinese** with `assets/templates/report.zh-CN.md`: every artifact as an absolute path, the options used, which calls were the script's, which were yours, and every `needs_review` item with what you did about it. A folder run uses the template's batch section: one table row per photo, the failed ones listed, the contact sheet paths.

## Done when

- The action's own "Done when" holds, or the user knows exactly what blocks it.
- Every `compare.jpg` the run produced was opened with Read and the report contains a conclusion drawn from the image, not only from the JSON. For a folder: every contact sheet page was opened, and the photos flagged there or in `needs_review` had their own `compare.jpg` opened.
- `needs_review` in `report.json` is empty, or each item is answered in the report. For a folder: every code in `summary.needs_review_counts` is answered once, with the photos it applies to.
- The original photo is untouched; nothing was deleted or uploaded; no commit was made.
