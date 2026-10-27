# run: analyze → style → portrait | landscape → export

## Inputs

| Input | Used for | When missing |
|---|---|---|
| photo | everything | ask |
| `--type auto\|portrait\|landscape\|generic` | which processing stage runs; `generic` = style and exports only | auto (the classifier) |
| `--style`, `--strength`, `--mode` | the look; default `clean-portrait` for portraits, `neutral` for landscapes; `none` skips | by type |
| any `portrait`, `landscape`, `export` option | passed through to that stage | stage defaults: portrait skin-strength 0.55, blemish on, moles kept, eye-sharpen 0.3; landscape black 0.5 / white 99.5, dehaze 0.15, far-clarity −15, near-texture 20, clahe 2.5, sky on, sky-darken 0.15, orton 0; export `--for print,web,dating`, paper 4x6, finish matte, fit crop |

## Steps

1. If the request leaves the type unclear, `dphoto info <photo>` first and read `suggested_type` with its reasons. Confidence < 0.75 or `unknown`: ask the user once ("脚本认为是 X，理由 …，按 X 处理吗？"). No answer: continue with the suggestion and say so.
2. `dphoto run <photo> [--type T] [options]`. `summary.type.used` is the stage that ran; `TYPE_UNCERTAIN` in `needs_review` means it ran on a low-confidence guess. `summary.params_used` has one entry per stage (`style` with name, strength and mode; `portrait` or `landscape`; `export`). The exports are made from the processed result, so dating variants show `retouched: false` after a portrait run: the skin pass already happened.
3. Open `compare.jpg` and `focus.jpg` and apply the checklist section for the type that ran, then the export row.
4. Adjust at most twice by re-running `run` with the changed option (the exports are regenerated from the corrected result), or run the single action when only one stage needs a change (`portrait` for strength, `export` for a crop).
5. Report with the template: type and confidence, style, stage parameters, metrics, every export, every review item.

## Done when

- The stage for the type ran, every requested export exists, `compare.jpg` was looked at, and the report covers type, style, stage parameters and the export list.
