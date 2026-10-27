# portrait: blemishes out, texture kept

## Inputs

| Input | Used for | When missing |
|---|---|---|
| photo | the face(s) to retouch | ask |
| `--skin-strength` | alpha of the low-band smoothing inside the skin mask, 0..0.85 (default 0.55; dating export uses 0.35) | 0.55 |
| `--blemish on\|off` | spot detection + inpainting | on |
| `--remove-moles` | also inpaint large high-contrast spots (moles); off by default because moles are identity | ask only if the user mentions moles; otherwise keep |
| `--eye-sharpen` | unsharp mask on the eye regions, 0..1 | 0.3 |
| `--face N` or `--face x,y,w,h` | which face when several are detected, or a manual box when none is | all detected faces |
| `--style` / `--strength` | a look applied before retouching (default `clean-portrait`; `none` skips) | `clean-portrait` |

## Steps

1. `dphoto info <photo>` when you are not sure a face will be found. `faces` lists boxes and eyes in full-resolution pixels; `suggested_type` should be `portrait`.
2. `dphoto portrait <photo> [options]`. Read `summary.faces`, `summary.skin_coverage`, `summary.metrics` (`texture_retained`, `blemishes_removed`, `moles_kept`, `skin_delta_e_mean`) and `needs_review`.
3. Open `compare.jpg` and `focus.jpg` (Read). Go through `references/review-checklist.md`, portrait section. `focus.jpg` is the face at true 1:1: pores and fine hair must still be there after; blotches, spots and uneven tone should be calmer, not gone. The second row of `compare.jpg` is the same region scaled to fit (its label shows the zoom) and only tells you about edges, eyes and overall smoothness.
4. Adjust at most twice:
   - plastic skin, pores gone, eyebrow or hairline edges soft → `--skin-strength` down by 0.15
   - still blotchy and the user asked for a clean result → `--skin-strength` up by 0.10 (never above 0.7 without saying so)
   - a freckle field, beard stubble or plain skin texture was treated as blemishes (`BLEMISH_COUNT_HIGH`, > 40 spots): compare `focus.jpg` with the before side; when no spot in the original was worth removing, re-run with `--blemish off` (the rest of the result stays the same), otherwise accept and say what was removed
   - `NO_FACE`: the mask fell back to whole-image skin detection (capped at 45 % of the frame, else disabled). Ask the user for a face box (`--face x,y,w,h`, pixels of the original) or whether the whole-image mask is acceptable.
   - `MULTI_FACE`: all faces were retouched; offer `--face N` (faces are numbered by size, 1 = largest).
   - `SKIN_LOW_COVERAGE` (< 4 %) usually means heavy shadow or a strong color cast on the face; `SKIN_HIGH_COVERAGE` (> 45 %) means background or clothing in skin tones got into the mask: check the whole-image row for softened background.
5. Report with the template: faces found, strength used, spots removed, moles kept, texture retained, and your verdict from the 100 % crop.

## Done when

- `processed.tif`, `processed.jpg`, `compare.jpg`, `report.json` exist and `compare.jpg` was looked at.
- Every `needs_review` item is answered in the report.
- The user knows the strength that was used and how to move it.

## How it works (for the recipe and for judgment)

Skin mask: YCrCb thresholds (Cr 133..173, Cb 77..127) inside each face box dilated 1.6× (plus 0.6× downward for the neck), eyes (Haar eye boxes or a geometric guess) and lips (redder than the skin center by 12 Cr in the lower third of the face) removed, opened, closed, feathered by short-side/150. Blemishes: spots darker than a median-filtered reference by more than 4 × the skin's own fine-texture sigma (floor 0.06) or redder in a* by 8, area 3..400 × (short/1000)², roundish; area ≥ 150 × (short/1000)² with contrast ≥ 0.25 is a mole. Spots are inpainted (Telea) in their own ROI. Frequency separation: low = guided filter (radius 3..8 px scaled with resolution, eps 0.01), high = image − low; the low band is smoothed again with a 5× radius guided filter and blended in by `skin × strength`; the high band is added back unchanged, which is what keeps pores. Eye sharpening is an unsharp mask limited to the eye regions.

Recipe for Photoshop: frequency separation with Gaussian radius ≈ short side / 250 px, heal spots on the high layer, blur-and-blend the low layer inside a skin selection at 40–70 % opacity, sharpen the eyes.
