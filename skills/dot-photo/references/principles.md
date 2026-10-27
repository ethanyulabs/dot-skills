# Principles (hold for every action)

## Step 0: orient

1. `SKILL_DIR` is the directory of this skill (the folder that holds `SKILL.md`). Resolve it from the path the skill was loaded from; it is `~/.claude/skills/dot-photo` or `~/.agents/skills/dot-photo` on most installs, or the checkout under `dot-skills/skills/dot-photo`.
2. Define the command:

   ```bash
   dphoto() { uv run --script "$SKILL_DIR/scripts/dphoto.py" "$@"; }
   ```

   The function lives only in the shell that defined it. An agent whose tool runs each command in a fresh shell must either define it at the start of every command or write the full form: `uv run --script "$SKILL_DIR/scripts/dphoto.py" <command> …`. `--script` keeps uv from picking up a `pyproject.toml` in the user's working directory. If `uv` is missing, say so and give the install line (`curl -LsSf https://astral.sh/uv/install.sh | sh`, or `brew install uv`); without uv the script also runs under any Python 3.11–3.13 that has `pillow pillow-heif numpy opencv-contrib-python-headless<5` installed (`python3 -I scripts/dphoto.py …`).
3. Run `dphoto selftest`. The first run resolves and downloads the dependencies (about 100 MB, one to two minutes); tell the user before it happens. `"ok": true` with `"haar": true` and `"heif": true` is the expected result. `"ximgproc": false` only makes the guided filter slower. Exit code 4 means a dependency problem; show the `hint`.

## Output contract

- Every command prints exactly one JSON line on stdout. Progress and tracebacks go to stderr and to `<out>/log.txt`. Parse stdout, never scrape stderr.
- Exit codes: 0 ok (also when `needs_review` is non-empty), 2 bad arguments, 3 the input could not be decoded, 4 dependency missing, 5 processing error. On failure the line is `{"ok": false, "error": {"code", "message", "hint"}}`; relay `message` and `hint`.
- Output directory: `<photo dir>/<stem>.dot-photo/` unless `--out DIR` is given. It holds `analysis.json`, `style.json`, `processed.tif` (16-bit sRGB with an sRGB profile), `processed.jpg` (quality 95, EXIF kept, GPS removed), `compare.jpg`, `focus.jpg`, `export/`, `report.json`, `log.txt` (one line per stage, also on stderr unless `--quiet`), and `masks/` when `--debug` was given. A re-run into the same directory overwrites the outputs but first renames the previous `compare.jpg`, `focus.jpg` and `report.json` to `*.prev.*`, so round 1 and round 2 can be compared; use a different `--out` when more rounds must be kept.
- `report.json` is the stdout line plus the bulky sections: `analysis` always, `style` and `style_info` when a style ran, `type_info` after `run`. `summary.params_used` is what actually ran, after any auto settings: for `portrait` and `landscape` the stage's options plus `style {name, strength, mode}`; for `run` one entry per stage (`style`, `portrait` or `landscape`, `export`). Quote it in the report. `summary.exports` lists every export file with size, ppi, `exif_stripped`, `upscale`, `crop_box_in_source` and, for dating, the face placement.
- `needs_review` is a list of `{code, message, suggest}`; `code` is English, `message` and `suggest` are Chinese and can be quoted in the report as they are. It is the script saying "look before you trust this": each item must be checked on the images and answered in the report. Codes: `NO_FACE`, `MULTI_FACE`, `SKIN_LOW_COVERAGE`, `SKIN_HIGH_COVERAGE`, `TEXTURE_RETAINED_LOW`, `BLEMISH_COUNT_HIGH`, `CLIP_HIGH`, `HALO_RISK`, `STYLE_LOW_CONFIDENCE`, `DATING_FACE_TOO_SMALL`, `DATING_UPSCALE_HIGH`, `PRINT_UPSCALE_HIGH`, `LARGE_IMAGE_DOWNSCALED`, `TYPE_UNCERTAIN`, `GUIDED_FILTER_FALLBACK`.
- `compare.jpg` (at most 1800 px wide): top row whole image before | after; second row the focus region (the largest face at 1.4×, the horizon band for landscapes, the center otherwise) scaled to fit, its label shows the zoom (`focus 63%`), also in `summary.focus_zoom`; third row, when exports were made, one thumbnail per export with the face box and the dating safe area drawn in yellow. `focus.jpg` is the same focus region at true 1:1 pixels, an 800 px window before | after: pores, hair and halos are judged there, never on the scaled row. Open both with the Read tool.

## Global options

`--out DIR`, `--max-analyze-px N` (statistics and detection run on a copy of at most N pixels, default 4 MP), `--max-process-px N` (0 = full size; images whose working set would exceed about 4 GB are reduced to 24 MP automatically and flagged `LARGE_IMAGE_DOWNSCALED`), `--debug` (writes `masks/*.png`), `--seed N` (grain), `--quiet`.

## What the script decides and what you decide

| Decision | Who |
|---|---|
| decoding, orientation, ICC → sRGB, statistics, parameter mapping, face / skin / sky masks, crops, sharpening | the script |
| photo type at confidence ≥ 0.75 | the script; you repeat its reasons |
| photo type below 0.75 or `unknown` | you ask the user once (give the reasons); if they do not answer, use `suggested_type` and say so in the report |
| whether the skin looks plastic, whether a halo appeared, whether a crop cut the head | you, on `compare.jpg`, with `references/review-checklist.md` |
| the strength after the first look | you: at most two re-runs, each a named option change |
| style fields with confidence below the threshold | you tell the user which ones were not inferred; never invent values |
| removing moles, changing the original, where outputs go | the user (defaults: keep moles, never touch the original, `<stem>.dot-photo/`) |

## Inputs

JPEG, PNG, TIFF (8 and 16 bit), HEIC/HEIF. EXIF orientation is applied; embedded ICC profiles (Display P3 from phones, Adobe RGB) are converted to sRGB; a HEIC that carries only an nclx P3 tag is converted with a fixed matrix. `summary.source_profile` reports what was found: the ICC description (`Display P3`, `sRGB IEC61966-2.1`, …), `Display P3 (nclx)`, or `untagged`, which means no profile at all and the pixels were taken as sRGB; an untagged HEIC adds a warning because phone originals are normally tagged, so mention it to the user. Load warnings appear in `warnings`. RAW files are not supported: ask the user for a JPEG/HEIC/TIFF export from their RAW converter.

## Manual fallback

If the script cannot run at all (no uv, no Python, a broken wheel), do not hand-write image code. Tell the user what blocks the script, what to install, and offer the parameter recipe from the action's reference file for use in Lightroom / Photoshop / their own tool.

## Acceptance (for whoever edits this skill)

1. `python3 ~/.claude/skills/skill-creator/scripts/quick_validate.py <SKILL_DIR>` passes.
2. `uv run --script <SKILL_DIR>/scripts/run_tests.py` is green.
3. One portrait and one landscape through `dphoto run`, their `compare.jpg` opened and judged with the checklist, every export present, the report in Chinese with absolute paths.
