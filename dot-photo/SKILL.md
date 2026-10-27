---
name: dot-photo
description: Photo style processing in five actions, run by a bundled Python script (uv, zero install) on JPEG / PNG / TIFF / HEIC. style extracts a JSON style file (tone, white balance, HSL, color grade, effects, with per-field confidence) from a reference photo and applies one to another photo; portrait removes skin blemishes and smooths skin while keeping pores and texture (frequency separation inside a skin mask, eyes and lips excluded); landscape builds depth (black and white points, dehaze, far/near bands, midtone local contrast, graduated sky); export writes print (300 ppi), web (2048 px, no EXIF) and dating-app (1:1 and 4:5, face-anchored, natural look) versions; run chains analysis, type processing and all exports. Trigger on /dot-photo, $dot-photo, 修图, 磨皮, 人像精修, 去瑕疵, 风景调色, 风景层次, 照片风格, 提取风格, 套用风格, 导出打印, 网页版照片, 交友软件头像, 约会软件照片, "retouch this photo", "smooth the skin", "apply this look", "export for print", "dating profile photo", even if they don't name this skill.
license: MIT
metadata:
  version: "0.1.0"
  compatibility: "Needs uv (https://docs.astral.sh/uv/) and a network connection the first time: scripts/dphoto.py declares its dependencies inline (pillow, pillow-heif, numpy, opencv-contrib-python-headless 4.x) and uv downloads about 100 MB into its cache. macOS, Linux and Windows; HEIC decoding falls back to sips on macOS."
---

# dot-photo: analyze the style → process by type → export every version

Usage: `/dot-photo <action> <photo> [options]` (Codex: `$dot-photo …`), or plain language such as "把这张人像磨一下皮", "这张风景层次拉一下", "把 A 的风格套到 B 上", "出一版打印的和一版交友软件用的". Without an action, step 2 picks one from the request.

The script does every deterministic step (decode, color management, statistics, masks, filters, crops, writes); you read its JSON, look at `compare.jpg`, decide the strength, and report in Chinese. The rules that hold for every action are in `references/principles.md`. Nothing here modifies the original photo: every output goes to `<photo dir>/<stem>.dot-photo/` (or `--out`).

## Actions

| Action | Invocation | What it does | Read |
|---|---|---|---|
| `style` | `/dot-photo style extract <photo> [--name N]` / `/dot-photo style apply <photo> --style <file\|preset> [--strength 0..1] [--mode hybrid\|params\|match]` | extract: analyze the photo and write `style.json` with per-field confidence; apply: put a style file or a built-in preset (`neutral`, `clean-portrait`, `film-warm`, `dating-safe`) on another photo, matching tone and white balance against that photo's own analysis in `hybrid` mode | `references/style.md` |
| `portrait` | `/dot-photo portrait <photo> [--skin-strength 0.55] [--blemish on\|off] [--remove-moles] [--eye-sharpen 0.3] [--face N\|x,y,w,h] [--style clean-portrait\|none]` | face detection → skin mask (eyes, lips excluded) → blemish inpainting (moles kept) → low-band smoothing with the high band put back untouched → eye sharpening | `references/portrait.md` |
| `landscape` | `/dot-photo landscape <photo> [--black 0.5 --white 99.5] [--dehaze 0.15] [--far-clarity -15 --near-texture 20] [--clahe 2.5] [--sky on --sky-darken 0.15] [--orton 0] [--style neutral\|none]` | black/white points → sky and depth masks → dehaze → far negative clarity, near texture → CLAHE in the midtones → graduated sky → optional Orton glow | `references/landscape.md` |
| `export` | `/dot-photo export <photo\|processed.tif> [--for print,web,dating] [--paper 4x6\|5x7\|8x10\|A4] [--finish matte\|glossy] [--fit crop\|pad] [--tiff16]` | print at 300 ppi with output sharpening, web at 2048 px without EXIF, dating 1:1 and 4:5 with the face anchored and a natural look; specs in `assets/presets/export.json` | `references/export.md` |
| `run` | `/dot-photo run <photo> [--type auto\|portrait\|landscape\|generic] [--style …] [--for …]` plus any portrait / landscape / export option | analyze → classify → style → portrait or landscape → every export, one report | `references/run.md` |

Every action that changes pixels writes `processed.tif` (16-bit sRGB), `processed.jpg`, `compare.jpg`, `focus.jpg` (1:1), `report.json` and prints one JSON line (`references/principles.md`, Output contract).

## Steps

1. **Orient.** Read `references/principles.md` and follow its Step 0: set `SKILL_DIR`, define `dphoto` as `uv run --script <SKILL_DIR>/scripts/dphoto.py`, run `dphoto selftest`. The first run downloads dependencies; tell the user it takes a minute or two.
2. **Pick the action**, in this order:
   - The user named one (`/dot-photo portrait …`): use it.
   - Plain language:

     | The user wants to | Action |
     |---|---|
     | smooth skin, remove blemishes, retouch a face, 磨皮 / 精修 / 去痘 | `portrait` |
     | more depth or layering in a landscape, dehaze, 层次 / 通透 | `landscape` |
     | copy the look of one photo onto another, save a look, 提取风格 / 套用风格 / 调色 | `style` |
     | a print, web or dating-app version, 打印 / 发网上 / 头像 | `export` |
     | "do the whole thing", several of the above, or they just hand over a photo | `run` |

   - Unsure which photo type: `dphoto info <photo>` and read `suggested_type`; below confidence 0.75 ask the user once, with the reasons the script gives.
3. **Follow that action's file** from its first step to its "Done when", reading the references it names when it names them.
4. **Verify by looking.** Whenever the action wrote `compare.jpg`, open it and `focus.jpg` (true 1:1) with the Read tool and go through `references/review-checklist.md`. Then accept, re-run with adjusted options, or ask the user. At most two re-runs; a re-run may change several options, and the report names every option that changed and why (`--blemish off --skin-strength 0.4`). Never report a result you have not looked at.
5. **Report in Chinese** with `assets/templates/report.zh-CN.md`: every artifact as an absolute path, the options used, which calls were the script's, which were yours, and every `needs_review` item with what you did about it.

## Done when

- The action's own "Done when" holds, or the user knows exactly what blocks it.
- Every `compare.jpg` the run produced was opened with Read and the report contains a conclusion drawn from the image, not only from the JSON.
- `needs_review` in `report.json` is empty, or each item is answered in the report.
- The original photo is untouched; nothing was deleted or uploaded; no commit was made.
