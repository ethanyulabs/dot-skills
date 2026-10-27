# style.json: fields and the analysis → parameter mapping

Schema: `assets/schema/style.schema.json` (`"schema": "dot-photo/style/1"`). Every numeric field is on the Lightroom JPEG slider scale, −100..100, except `tone.exposure` (EV, −2..2), `grade.*.hue` (0..360 degrees) and `grade.*.sat` / `effects.grain` (0..100). Unknown keys and out-of-range values are rejected. Fields left out mean 0.

| Section | Fields | Meaning in `apply` |
|---|---|---|
| `tone` | `exposure`, `contrast`, `highlights`, `shadows`, `whites`, `blacks` | exposure in linear light; blacks/whites move the end points; contrast is a monotone S-curve; highlights/shadows act through luminosity masks (lights = L², darks = (1−L)²). All tone work scales RGB by a luma ratio, so hue does not drift. |
| `color` | `temperature`, `tint`, `vibrance`, `saturation` | channel gains (+100 temperature = R×1.25, B×0.75; +100 tint = G×0.8); saturation scales S; vibrance lifts low-S pixels more and protects the orange (skin) band |
| `curve` | `rgb`, `r`, `g`, `b`: lists of `[in, out]` on 0..255, or null | monotone cubic through the points; `rgb` on luma, the others per channel |
| `hsl` | per band `red, orange, yellow, green, aqua, blue, purple, magenta`: `hue`, `sat`, `lum` | soft hue windows (bin ± 15°); hue ±100 → ±30°, sat ±100 → S × 0..2, lum ±100 → V × 0.5..1.5 |
| `grade` | `shadows`, `midtones`, `highlights`: `{hue, sat}`; `balance` (unused, kept for Lightroom parity) | Lab a/b offset of up to 12 in the hue direction, weighted by the zone mask |
| `effects` | `clarity`, `texture`, `dehaze`, `vignette`, `grain` | clarity = local contrast at radius short/40 (guided filter); texture at 2 px; dehaze > 0 = dark channel prior, < 0 adds haze; vignette < 0 darkens corners; grain = monochrome noise, more in the shadows, seeded |
| `stats` | the analysis of the reference (extracted styles only) | lets `hybrid` / `match` compute reference-minus-target deltas |
| `confidence` | `overall` plus one entry per field path | fields below `--min-confidence` were written as 0 |
| `notes` | strings | which fields were not inferred and why |

## Analysis statistics (`analysis.json`, computed on a ≤ 4 MP copy)

`luma_percentiles` (Lab L / 100 at 0.5, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.5), `neutral_lab_mean` (a*, b* of near-neutral pixels, |a|,|b| < 12, 0.2 < L < 0.85; `fallback` when under 2 % of the frame), `chroma_mean` / `chroma_median`, `hsl_hist` (per band: fraction, mean S, mean V, circular mean H; only S > 0.12, 0.08 < V < 0.97), `skin` (YCrCb Cr 133..173, Cb 77..127, inside dilated face boxes when faces exist), `local_contrast` (std of L minus a short/50 blur, midtones), `texture_energy` (std of L minus a 2 px blur), `noise_sigma` (Laplacian median on flat areas), `haze.dark_channel_mean` / `_top`, `vignette_ratio` (corner L / center L), `grade_lab` (a*, b* per zone), `sky_coverage`, `faces`.

## Mapping (`extract`; constants in `assets/presets/analysis-priors.json`)

| Field | Formula | Confidence |
|---|---|---|
| `tone.exposure` | log2(lin(0.45) / lin(p50)); 0.50 for portraits | 0.7; 0.4 when p95 − p5 > 0.85 |
| `tone.blacks` | (p1 − 0.015) × 600 | 0.7 |
| `tone.whites` | (p99 − 0.97) × 600 | 0.6; 0.3 when p99 ≥ 0.995 |
| `tone.contrast` | mean of ((p95−p5) − 0.72)/0.22 × 50 and ((p75−p25) − 0.32)/0.15 × 25 | 0.6 |
| `tone.shadows` | ((p10−p1)/(p50−p1) − 0.22) × 300 | 0.4 |
| `tone.highlights` | −(0.22 − (p99−p90)/(p99−p50)) × 300 | 0.4 |
| `color.temperature` / `tint` | neutral b* × 6 / a* × 6; with a detected face, blended half-and-half with (skin b* − 18) × 6 / (skin a* − 14) × 6 | 0.8 × min(1, coverage/0.05); 0.3 on fallback |
| `color.saturation` | (chroma_mean − 25) / 25 × 50 | 0.6 |
| `color.vibrance` | (chroma_median / chroma_mean − 0.80) × 250, never negative when saturation is already negative | 0.3 |
| `hsl.<band>.sat` | (S − prior_S) / prior_S × 60, bands with ≥ 1 % of pixels | min(1, frac/0.05) × 0.7 |
| `hsl.<band>.lum` | (V − prior_V) × 200 | same |
| `hsl.<band>.hue` | hue offset from the band center, ±30 cap; only orange, green, blue | same |
| `grade.<zone>` | hue = atan2(b*, a*); sat = min(100, chroma × 4); chroma < 1.5 → 0 | 0.5; 0.2 when the zone holds < 5 % of pixels |
| `effects.clarity` | (local_contrast − 0.040)/0.040 × 50 | 0.5 |
| `effects.texture` | (texture_energy − 0.010)/0.010 × 40 | 0.4; 0.2 when noise_sigma > 0.012 |
| `effects.dehaze` | max(0, (0.25 − dark_channel_mean) × 200) | 0.2 |
| `effects.vignette` | (vignette_ratio − 1) × 150 | 0.6 |
| `effects.grain` | clamp((noise_sigma − 0.004)/0.020 × 100, 0, 100) | 0.5 |
| `curve` | identity at extract; `--mode match` builds it from the p1…p99 quantiles of reference vs target | 0 / 0.8 |
| `confidence.overall` | mean of the above, weighted by 1 + |value|/20 | — |

Mapping is deliberately linear and readable: a reviewer can recompute any field from `analysis.json`.
