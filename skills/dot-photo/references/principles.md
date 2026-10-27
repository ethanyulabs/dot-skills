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
- Output directory: `~/.dot/photo/output/<stem>-<hash>/` (Home directory, below) unless `--out DIR` is given; a file that already lives in one of those directories (`processed.tif`, an export) is re-processed into that same directory. It holds `source.json` (the original path(s), size, mtime, sha1), `analysis.json`, `style.json`, `processed.tif` (16-bit sRGB with an sRGB profile), `processed.jpg` (quality 95, EXIF kept, GPS removed), `compare.jpg`, `focus.jpg`, `export/`, `report.json`, `log.txt` (one line per stage, also on stderr unless `--quiet`), and `masks/` when `--debug` was given. A re-run into the same directory overwrites the outputs but first renames the previous `compare.jpg`, `focus.jpg` and `report.json` to `*.prev.*`, so round 1 and round 2 can be compared; use a different `--out` when more rounds must be kept.
- `report.json` is the stdout line plus the bulky sections: `analysis` always, `style` and `style_info` when a style ran, `type_info` after `run`. `summary.params_used` is what actually ran, after any auto settings: for `portrait` and `landscape` the stage's options plus `style {name, strength, mode}`; for `run` one entry per stage (`style`, `portrait` or `landscape`, `export`). Quote it in the report. `summary.exports` lists every export file with size, ppi, `exif_stripped`, `upscale`, `crop_box_in_source` and, for dating, the face placement.
- `needs_review` is a list of `{code, message, suggest}`; `code` is English, `message` and `suggest` are Chinese and can be quoted in the report as they are. It is the script saying "look before you trust this": each item must be checked on the images and answered in the report. Codes: `NO_FACE`, `MULTI_FACE`, `SKIN_LOW_COVERAGE`, `SKIN_HIGH_COVERAGE`, `TEXTURE_RETAINED_LOW`, `BLEMISH_COUNT_HIGH`, `CLIP_HIGH`, `HALO_RISK`, `STYLE_LOW_CONFIDENCE`, `DATING_FACE_TOO_SMALL`, `DATING_UPSCALE_HIGH`, `PRINT_UPSCALE_HIGH`, `LARGE_IMAGE_DOWNSCALED`, `TYPE_UNCERTAIN`, `GUIDED_FILTER_FALLBACK`.
- Folder input: see the next section.
- `compare.jpg` (at most 1800 px wide): top row whole image before | after; second row the focus region (the largest face at 1.4×, the horizon band for landscapes, the center otherwise) scaled to fit, its label shows the zoom (`focus 63%`), also in `summary.focus_zoom`; third row, when exports were made, one thumbnail per export with the face box and the dating safe area drawn in yellow. `focus.jpg` is the same focus region at true 1:1 pixels, an 800 px window before | after: pores, hair and halos are judged there, never on the scaled row. Open both with the Read tool.

## Folder input

Every command that takes a photo except `style extract` and `compare` also takes a folder: `dphoto run <folder> [options]` runs `run` with those options on every photo in it, one after another, and prints one JSON line for the whole batch.

- Scan: recursive by default (`--no-recursive` stays at the top level); files sorted by path; extensions `.jpg .jpeg .png .tif .tiff .heic .heif .hif` (any case). Skipped: hidden files and directories, directories named `dot-photo` or ending in `.dot-photo` (outputs of versions before 0.3), `processed.*` files, the `--out` directory, the dot-photo home itself. No photo found → `NO_PHOTOS`, exit 2.
- Output: every photo goes to `<output root>/<stem>-<hash>/`, exactly what the single-photo command writes; the output root is `~/.dot/photo/output/` or `--out DIR`. The run's own files, `batch.json`, `log.txt` (one progress line per photo, also on stderr unless `--quiet`) and for pixel-writing actions `contact.jpg` (`contact-2.jpg`, … above 12 photos), go to the run directory: a fresh `~/.dot/photo/runs/<YYYYMMDD-HHMMSS>-<folder>/` per run (`-2`, `-3` when the name is taken), or `--out DIR` itself, where a re-run renames the previous `batch.json` and `contact*.jpg` to `*.prev.*`. The stdout line names both: `out_dir` is the run directory, `output_root` the photos' root. Two copies of the same photo under different names are the same content, so they share one directory: the second one renames the first one's `compare.jpg` / `focus.jpg` / `report.json` to `*.prev.*`, and `source.json` lists both paths. `--skip-existing` skips every photo whose output directory already has `report.json` (failed photos have none, so they are retried; `info` never writes one).
- One failed photo does not stop the batch: it is recorded with its `error` and the next photo runs. The stdout line is `{"ok", "action", "batch": true, "input", "out_dir", "output_root", "config_applied", "artifacts": {"contact": [paths], "batch", "log"}, "summary": {"total", "ok", "failed", "skipped", "needs_review_counts": {code: n}, "photos": [{"input", "rel", "out_dir", "status": "ok" | "failed" | "skipped", "type", "needs_review": [codes], "error"}]}, "warnings", "timing_ms"}`. `batch.json` is the same with each photo's full stdout object under `result`. Exit 0 unless every photo failed, which gives exit 5 and `error.code` `ALL_FAILED`; skipped photos count as earlier successes.
- `contact.jpg` (1800 px wide, 12 rows per page): one row per photo, the title line with the relative path, the type used and its confidence, the `needs_review` codes in yellow, or `FAILED <code>` in red; below it the original and the result (`processed.jpg`, or `export/web.jpg` after `export`) side by side at 220 px high. It shows composition, tone and failures; fine detail is judged on that photo's own `focus.jpg`.
- Photo types: the batch never stops to ask. A photo below confidence 0.75 runs on `suggested_type` and is flagged `TYPE_UNCERTAIN`; list those photos in the report and offer to re-run them singly with `--type`.
- Memory: photos are processed one at a time, so the batch needs no more than the largest photo. A HEIC that falls back to `sips` leaves its decoded PNG in a temporary directory per photo, as in single-photo mode.

## Home directory

`~/.dot/<skill>/` is where every dot-* skill keeps the user's own things; this skill uses `~/.dot/photo/`. The environment variable `DOT_HOME` moves the `~/.dot` root (`DOT_HOME=/tmp/x` → `/tmp/x/photo/`). `dphoto config show` prints every path below.

```
~/.dot/photo/
├── config.json              the user's default parameters (below)
├── styles/<name>.json       user styles: `style extract --name <name>` writes them, `--style <name>` uses them
├── output/<stem>-<hash>/    one directory per photo content (sha1 of the file, first 8 hex) + source.json
└── runs/<stamp>-<folder>/   batch.json, contact*.jpg, log.txt of one folder run
```

- Naming by content: the same file processed from any path lands in the same directory (re-runs keep `*.prev.*`), two different photos never share one, and nothing is written next to the originals. `source.json` says which path(s) a directory came from. A photo renamed or moved keeps its directory; a photo re-edited elsewhere (new content) gets a new one.
- Styles: `--style` resolves a path first, then a built-in preset, then a user style. A user style cannot take a preset's name or `none` (`STYLE_NAME_RESERVED`), cannot contain path separators (`STYLE_NAME_INVALID`), and is not overwritten without `--force` (`STYLE_EXISTS`). `style list` shows both groups and marks user files that fail validation.
- `config.json` (`{"schema": "dot-photo/config/1", "defaults": {"portrait": {...}, "landscape": {...}, "export": {...}, "run": {...}}}`): keys are the command-line option names, values the option's type (`"skin-strength": 0.4`, `"blemish": "off"`, `"for": "print,web"`, `"tiff16": true`). Precedence: an option given on the command line > `config.json` > the built-in default. `portrait`, `landscape` and `export` each take their own section; `run` takes all four, its own `style` / `strength` / `type` / `mode` coming from the `run` section only. Common options (`--out`, `--quiet`, `--seed`, …) cannot be set in the config. Unknown sections, unknown keys and bad values are reported in `warnings` and ignored; a broken `config.json` is ignored with a warning by the processing commands and refused (`CONFIG_INVALID`, exit 2) by `config show/set/unset`, so a bad file is never overwritten. Every result carries `config_applied`: the section → key → value pairs the config contributed to that command (listed even when the command line overrode them). Flags without a value (`remove-moles`, `tiff16`) set to `true` in the config cannot be turned off from the command line; `config unset` them.
- `config set <section> key=value …` validates each key and value against the command's options (`CONFIG_BAD_SECTION`, `CONFIG_BAD_KEY`, `CONFIG_BAD_VALUE`, exit 2) and prints the section; `config unset <section> [key]` removes one key or the whole section. Use them when the user says "always", "from now on", 以后都这样: save the option you just agreed on, and tell them it is in `config.json`.

## Global options

`DOT_HOME` (environment; the root above `photo/`), `--out DIR` (for a folder: the root for the photos and the run files), `--no-recursive` and `--skip-existing` (folder only), `--max-analyze-px N` (statistics and detection run on a copy of at most N pixels, default 4 MP), `--max-process-px N` (0 = full size; images whose working set would exceed about 4 GB are reduced to 24 MP automatically and flagged `LARGE_IMAGE_DOWNSCALED`), `--debug` (writes `masks/*.png`), `--seed N` (grain), `--quiet`.

## What the script decides and what you decide

| Decision | Who |
|---|---|
| decoding, orientation, ICC → sRGB, statistics, parameter mapping, face / skin / sky masks, crops, sharpening | the script |
| photo type at confidence ≥ 0.75 | the script; you repeat its reasons |
| photo type below 0.75 or `unknown` | you ask the user once (give the reasons); if they do not answer, use `suggested_type` and say so in the report. In a folder run nothing is asked: the photo runs on `suggested_type`, the report lists it under `TYPE_UNCERTAIN` and offers a single re-run with `--type` |
| whether the skin looks plastic, whether a halo appeared, whether a crop cut the head | you, on `compare.jpg`, with `references/review-checklist.md` |
| the strength after the first look | you: at most two re-runs, each a named option change |
| style fields with confidence below the threshold | you tell the user which ones were not inferred; never invent values |
| removing moles, changing the original, where outputs go | the user (defaults: keep moles, never touch the original, `~/.dot/photo/output/<stem>-<hash>/`) |
| parameters the user wants every time | the user, through `config set`; you name them in the report as theirs (`config_applied`) |

## Inputs

JPEG, PNG, TIFF (8 and 16 bit), HEIC/HEIF. EXIF orientation is applied; embedded ICC profiles (Display P3 from phones, Adobe RGB) are converted to sRGB; a HEIC that carries only an nclx P3 tag is converted with a fixed matrix. `summary.source_profile` reports what was found: the ICC description (`Display P3`, `sRGB IEC61966-2.1`, …), `Display P3 (nclx)`, or `untagged`, which means no profile at all and the pixels were taken as sRGB; an untagged HEIC adds a warning because phone originals are normally tagged, so mention it to the user. Load warnings appear in `warnings`. RAW files are not supported: ask the user for a JPEG/HEIC/TIFF export from their RAW converter.

## Manual fallback

If the script cannot run at all (no uv, no Python, a broken wheel), do not hand-write image code. Tell the user what blocks the script, what to install, and offer the parameter recipe from the action's reference file for use in Lightroom / Photoshop / their own tool.

## Acceptance (for whoever edits this skill)

1. `python3 ~/.claude/skills/skill-creator/scripts/quick_validate.py <SKILL_DIR>` passes.
2. `uv run --script <SKILL_DIR>/scripts/run_tests.py` is green.
3. One portrait and one landscape through `dphoto run`, their `compare.jpg` opened and judged with the checklist, every export present, the report in Chinese with absolute paths.
