# style: extract a look from a photo, apply a look to a photo

## Inputs

| Input | Used for | When missing |
|---|---|---|
| reference photo (`extract`) | statistics → `style.json` | ask for the photo whose look they want |
| target photo (`apply`), or a folder (the look goes on every photo in it; `references/principles.md`, Folder input) | the photo that receives the look | ask |
| `--style <file\|preset\|user style>` (`apply`) | a `style.json`, a built-in preset (`neutral`, `clean-portrait`, `film-warm`, `dating-safe`) or a user style saved under `~/.dot/photo/styles/` (`dphoto style list` shows both) | if they described a look in words, pick the nearest preset and say so; if they named another photo, run `extract` on it first; if they named a look they saved earlier, `style list` |
| `--strength` | 0..1 scales every parameter (default 1.0) | 1.0 |
| `--mode` | `hybrid` (default): exposure, contrast, blacks, whites, temperature, tint are computed as reference-minus-target so the target lands where the reference is; HSL, grade, effects as stored. `params`: everything as stored (what a hand-written preset expects). `match`: hybrid plus a tone curve from quantile matching | `hybrid` for extracted styles, `params` for presets (presets carry no `stats`, so `hybrid` falls back to `params` by itself) |
| `--name [--force]`, `--min-confidence` (`extract`) | `--name N` is the style's name and also saves it as the user style `~/.dot/photo/styles/N.json` (refused when N exists unless `--force`, or when N is a preset name or `none`); the confidence floor below which a field is written as 0 | without `--name` the style is named after the photo and written only to the output directory; 0.35. Use `--name` whenever the user wants to keep or reuse the look |

## Steps: extract

1. `dphoto style extract <reference> [--name N]`. Read `summary`: `tone`, `color`, `effects`, `hsl`, `grade`, `confidence_overall`, `low_confidence_fields`.
2. Describe the look in words from those numbers (`references/style-schema.md` has the meaning and scale of every field): warm or cool, lifted or crushed blacks, which hue bands are muted, what the shadows and highlights are tinted. Numbers go in a short table, not in prose.
3. List the fields in `low_confidence_fields` as "not inferred" and why (the notes in `style.json` give the reason). `STYLE_LOW_CONFIDENCE` in `needs_review` means the overall confidence is below 0.5: say that the file captures white balance and tone better than color grading, and offer to tune by hand.
4. Tell the user where `style.json` is and that it can be edited by hand (any field, same scale as Lightroom's JPEG sliders) and reused with `apply`. With `--name`, also give the user-style path (`artifacts.style_user`) and say that `--style <name>` now works from anywhere; `style list` shows every saved look.

### Done when

- `style.json` exists, validates (the script refuses to write an invalid one), and the user has a description of the look plus the list of fields that were not inferred. If they wanted to keep the look, it is saved under a name (`summary.saved_as`).

## Steps: apply

1. `dphoto style apply <target> --style <file|preset> [--strength S] [--mode M]`.
2. Open `compare.jpg` (Read tool). Checklist items for styles: skin went orange or gray; sky banding; blacks or whites clipped; the look is much stronger than the reference. When it is too strong, re-run with `--strength 0.6`; when white balance overshoots on a `hybrid` run, re-run with `--mode params`.
3. Report: the style name, mode, strength, `matched_fields` (what was computed against the target rather than copied), and the paths.

### Done when

- `processed.tif`, `processed.jpg`, `compare.jpg`, `report.json` exist; you looked at `compare.jpg`; the report names mode and strength.

## Recipe for other tools

The style file maps one-to-one onto Lightroom / Camera Raw sliders (`tone.*`, `color.*`, `hsl.<band>.*`, `grade.*`, `effects.*`). To reproduce a look by hand, read the numbers out of `style.json`; `exposure` is in EV, every other field is the ±100 slider scale.
