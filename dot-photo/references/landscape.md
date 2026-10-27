# landscape: depth and layering

## Inputs

| Input | Used for | When missing |
|---|---|---|
| photo | the scene | ask |
| `--black`, `--white` | percentiles that become pure black and white (default 0.5 / 99.5; together they clip 1 % of pixels) | defaults |
| `--dehaze` | 0..1, dark-channel dehaze strength (ω = 0.95 × value); the sky gets half of it | 0.15 |
| `--far-clarity`, `--near-texture` | negative clarity on the far band (sky and low-transmission areas), texture on the near band (high transmission, lower third) | −15 / 20 |
| `--clahe`, `--clahe-tile` | CLAHE clip limit (0 = off) and tile grid, applied to the midtones outside the sky at 60 % | 2.5 / 8 |
| `--sky on\|off`, `--sky-darken` | sky mask and a top-to-horizon graduated darkening | on / 0.15 |
| `--orton` | glow blend 0..0.15 | 0 |
| `--style` / `--strength` | a look applied first (default `neutral`) | `neutral` |

## Steps

1. `dphoto landscape <photo> [options]`. Read `summary.metrics`: `black_point`, `white_point`, `clip_fraction`, `sky_coverage`, `horizon_row`, `transmission_mean`, `halo_ratio`, `ground_texture_before/after`.
2. Open `compare.jpg` and `focus.jpg`. The focus region is the horizon band (or the center when no sky was found); `focus.jpg` shows it at true 1:1, which is where a halo is visible. Checklist: bright rim along ridges or the skyline (halo), banding in a smooth sky, blocked shadows, greens gone neon, the sky darkened into a gray lid.
3. Adjust at most twice:
   - halo along the horizon, `HALO_RISK` → `--clahe 1.5` or `--far-clarity -5`
   - sky banding or a heavy top → `--sky-darken 0.08`; a false sky mask (a white wall, snow) → `--sky off`
   - still flat → `--dehaze 0.3` and `--near-texture 30`; very hazy scenes take `--dehaze 0.5`, more than that looks fake
   - blocked shadows after the black point → `--black 0.1`; `CLIP_HIGH` means the user's percentiles clip more than 1 %
   - a dreamy look was asked for → `--orton 0.1`
4. Report: the parameters used, sky coverage and horizon, the halo ratio, and what you saw in the crop.

## Done when

- Outputs exist, `compare.jpg` was looked at, and the report states the parameters and the horizon/halo check.

## How it works

Black and white points are set on luma with proportional RGB scaling (no channel clipping, no color shift). Sky = low-texture, bright, blue/cyan/gray pixels connected to the top edge, refined by a guided filter. Transmission from the dark channel prior (patch 15, guided-filter refinement, floor 0.1); the far band is sky ∪ t < 0.5, the near band t > 0.8 in the lower third, mid is the rest, all feathered. Far gets negative clarity (guided-filter high-pass at short/40), near gets texture (2 px high-pass). CLAHE runs on 16-bit luma and is applied as a ratio weighted by the midtone mask and (1 − sky). The sky darkening is multiplicative, strongest at the top edge and zero at the horizon row. Orton = screen blend of a short/60 blur at the given opacity. The halo metric is the Sobel edge energy in a band around the horizon, after / before; above 1.8 the run is flagged.

Recipe for Lightroom: Blacks/Whites to the histogram ends, Dehaze +10..+30, a linear gradient on the sky at −0.3 EV, a luminosity-masked Clarity +10..+30 on the midtones, Texture +20 on the foreground, Clarity −10 on the far hills.
