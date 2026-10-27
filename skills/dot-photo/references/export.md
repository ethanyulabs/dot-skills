# export: print / web / dating versions

## Inputs

Options left out come from the user's `config.json` before the defaults below (`config_applied` in the result names them; `references/principles.md`, Home directory).

| Input | Used for | When missing |
|---|---|---|
| photo or `processed.tif` from an earlier action, or a folder (every photo in it; `references/principles.md`, Folder input) | the source pixels; `processed.*` is treated as already retouched (no second skin pass for dating). Inside `run` the exports are always made from the processed result, so the dating variants report `retouched: false` there: the skin pass already happened in the portrait stage | ask |
| `--for` | comma list of `print`, `web`, `dating` | all three |
| `--paper`, `--finish`, `--fit` | print size (`4x6`, `5x7`, `8x10`, `A4`), paper surface (sharpening preset), crop or pad | 4x6, matte, crop |
| `--tiff16` | also write a 16-bit TIFF for the lab | off |
| `--face N\|x,y,w,h` | which face anchors the print crop and the dating crop | largest detected |
| `--dating-retouch auto\|on\|off` | light skin pass (strength 0.35) for the dating variants | auto: on for a raw photo, off for `processed.*` |
| `--presets <file>` | another spec table | `assets/presets/export.json` |

## Specs (edit `assets/presets/export.json` to change them)

| Target | Size | Color / file | Metadata | Sharpening | Notes |
|---|---|---|---|---|---|
| print | paper × 300 ppi for every paper, orientation follows the photo (4x6 → 1800×1200 or 1200×1800, A4 → 3507×2481 or 2481×3507) | sRGB, JPEG q92 4:4:4, optional 16-bit TIFF | EXIF kept, GPS removed | matte r1.0 a0.8 / glossy r0.7 a0.55 | labs want sRGB unless they say Adobe RGB. Small photos are upscaled to reach the size: `upscale` is reported, above 1.5× the run is flagged `PRINT_UPSCALE_HIGH`. The crop is anchored on the largest face, else centered; `crop_box_in_source` gives the source rectangle that was kept |
| web | long edge 2048, never upscaled | sRGB JPEG q80 | all EXIF removed | r0.5 a0.5 | Facebook 2048, Instagram 1080 wide (it downsizes) |
| dating_1x1 / dating_4x5 | 1080×1080, 1080×1350 | sRGB JPEG q88 | all EXIF removed | r0.6 a0.4 | third-party measurements, no official specs: Tinder cards show about 0.7:1 of the image, Hinge/Bumble are happy with 1:1 or 4:5 ≥ 1080 px |

Dating look: the `dating-safe` style (warm +7, soft highlights, no grain, vignette ≥ −10, grade saturation ≤ 15), eye sharpening 0.25, light skin pass only when the input is a raw photo. Crop: the largest face's center lands at 38 % of the height and the face is 30 % of the height when the photo is large enough. Two things bend that rule, both reported under `crop`: a small face would need more than 1.67× upscaling, so the crop grows and the face share drops (below 18 % → `DATING_FACE_TOO_SMALL`; still above 1.67× → `DATING_UPSCALE_HIGH`); a large face in a small photo cannot get the 30 % frame, so the crop is clamped to the image (`bounded_by_image: true`), the face share rises and the center moves toward wherever the photo allows. `face_center_frac`, `face_height_frac` and `face_in_safe_area` (the whole face box inside the 0.7:1 centered safe area) say what actually happened; hair the original already cut off is not a crop problem, but say so in the report.

## Steps

1. `dphoto export <source> [--for …] [--paper …] [--finish …]`.
2. Open `compare.jpg`: the third row shows each export with the face box and, for dating, the safe area in yellow. Check: head not cut, face inside the safe area, print crop not losing the subject, web version not soft.
3. `NO_FACE` on a portrait: give `--face x,y,w,h`. `DATING_FACE_TOO_SMALL` / `DATING_UPSCALE_HIGH`: the original is too small or the face too small for a card; say so and suggest another photo.
4. Report every file with size, ppi where relevant, upscale when above 1, and whether EXIF was removed (`summary.exports`).

## Done when

- Every requested target exists under `export/`, `compare.jpg` was looked at, and the report lists size, ppi and metadata per file.
