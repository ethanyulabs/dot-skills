"""Landscape depth: black/white points, luminosity zones, dark-channel dehaze, far/mid/near
bands (negative clarity far, texture near), CLAHE mid-frequency contrast in the midtones,
a graduated darkening of the sky and an optional Orton glow.
"""
from __future__ import annotations

import os

import numpy as np

import cv2

from . import masks as M
from .color import apply_lut_luma, f32, gaussian, guided_filter, identity_lut, luma
from .imageio import WorkImage, downscale, save_png

MASK_MAX_PX = 4_000_000


def dehaze(rgb: np.ndarray, strength: float, *, t: np.ndarray | None = None, A: np.ndarray | None = None,
           sky: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """He et al. dark channel prior. strength 0..1 scales omega (0.95 at 1.0)."""
    rgb = f32(rgb)
    s = float(np.clip(strength, 0.0, 1.0))
    if s <= 0:
        return rgb, {"omega": 0.0}
    if A is None or t is None:
        dark = M.dark_channel(rgb, 15)
        A = M.atmosphere(rgb, dark)
        t = M.transmission(rgb, A, omega=0.95 * s)
    J = (rgb - A[None, None, :]) / t[..., None] + A[None, None, :]
    J = np.clip(J, 0, 1).astype(np.float32)
    if sky is not None:
        J = rgb + (J - rgb) * (1 - 0.5 * sky)[..., None]
    return J.astype(np.float32), {"omega": round(0.95 * s, 3), "A": [round(float(v), 3) for v in A],
                                  "t_mean": round(float(t.mean()), 3)}


def _horizon_row(sky: np.ndarray) -> int | None:
    rows = sky.mean(axis=1)
    idx = np.where(rows > 0.3)[0]
    if idx.size == 0:
        return None
    return int(idx.max())


def _edge_strength(L: np.ndarray, band: np.ndarray) -> float:
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3)
    g = np.sqrt(gx * gx + gy * gy)
    return float(g[band > 0].mean()) if band.any() else 0.0


def enhance(img: WorkImage, *, params: dict, debug_dir: str | None = None) -> tuple[WorkImage, dict]:
    p = params
    rgb = f32(img.rgb).copy()
    h, w = rgb.shape[:2]
    short = min(h, w)
    reviews: list[tuple[str, str]] = []

    # 1. black / white points
    L = luma(rgb)
    lo, hi = np.percentile(L, [p["black"], p["white"]])
    lo, hi = float(lo), float(hi)
    if hi - lo > 0.05:
        lut = np.clip((identity_lut() - lo) / (hi - lo), 0, 1).astype(np.float32)
        rgb = apply_lut_luma(rgb, lut)
    clip_frac = (p["black"] + (100.0 - p["white"])) / 100.0
    if clip_frac > 0.0105:
        reviews.append(("CLIP_HIGH", f"{clip_frac:.1%}"))

    # 2. masks on a reduced copy
    small, s = downscale(img.copy_with(rgb), MASK_MAX_PX)
    sm = small.rgb
    sky_s = M.sky_mask(sm) if p.get("sky", True) else np.zeros(sm.shape[:2], np.float32)
    dark_s = M.dark_channel(sm, 15)
    A = M.atmosphere(sm, dark_s)
    omega = 0.95 * float(np.clip(p["dehaze"], 0, 1)) if p["dehaze"] > 0 else 0.95
    t_s = M.transmission(sm, A, omega=omega)
    bands_s = M.depth_bands(t_s, sky_s)
    sky = M.upscale(sky_s, h, w)
    t = M.upscale(t_s, h, w)
    far, mid, near = (M.upscale(bands_s[k], h, w) for k in ("far", "mid", "near"))
    lum = M.luminosity_masks(rgb)
    horizon = _horizon_row(sky_s)
    horizon_full = int(horizon / s) if horizon is not None else None

    L_before_small = luma(sm)
    band_s = np.zeros(sm.shape[:2], np.float32)
    if horizon is not None:
        k = max(3, int(min(sm.shape[:2]) / 60))
        y0, y1 = max(0, horizon - k), min(sm.shape[0], horizon + k)
        band_s[y0:y1] = 1.0
    edge_before = _edge_strength(L_before_small, band_s)
    ground_sel = np.zeros(sm.shape[:2], bool)
    if horizon is not None:
        ground_sel[min(sm.shape[0] - 1, horizon + 5):] = True
    else:
        ground_sel[sm.shape[0] // 2:] = True
    tex_before = float((L_before_small - gaussian(L_before_small, 2.0))[ground_sel].std()) if ground_sel.any() else 0.0

    # 3. dehaze
    dinfo = {"omega": 0.0}
    if p["dehaze"] > 0:
        rgb, dinfo = dehaze(rgb, p["dehaze"], t=t, A=A, sky=sky)

    # 4. far: negative clarity; near: texture
    if abs(p["far_clarity"]) > 1e-6:
        L = luma(rgb)
        hp = L - guided_filter(L, L, max(2, int(short / 40)), 0.04)
        rgb = np.clip(rgb + (p["far_clarity"] / 100.0 * 0.5 * hp * far)[..., None], 0, 1)
    if abs(p["near_texture"]) > 1e-6:
        L = luma(rgb)
        hp = L - gaussian(L, max(1.5, 2.0 * short / 1500))
        rgb = np.clip(rgb + (p["near_texture"] / 100.0 * 0.4 * hp * near)[..., None], 0, 1)

    # 5. CLAHE in the midtones (never on the sky)
    if p["clahe"] > 0:
        L = luma(rgb)
        clahe = cv2.createCLAHE(clipLimit=float(p["clahe"]), tileGridSize=(int(p["clahe_tile"]), int(p["clahe_tile"])))
        L16 = np.clip(L * 65535, 0, 65535).astype(np.uint16)
        Lc = clahe.apply(L16).astype(np.float32) / 65535.0
        ratio = Lc / np.maximum(L, 1e-3)
        wgt = lum["mids"] * (1 - sky) * 0.6
        factor = 1 + (ratio - 1) * wgt
        rgb = np.clip(rgb * factor[..., None], 0, 1).astype(np.float32)

    # 6. graduated sky darkening
    if p.get("sky", True) and p["sky_darken"] > 0 and sky.max() > 0:
        grad = M.vertical_gradient(h, w, 1.0, horizon_full if horizon_full else int(h * 0.55))
        rgb = np.clip(rgb - (p["sky_darken"] * grad * sky)[..., None] * rgb, 0, 1).astype(np.float32)

    # 7. Orton glow
    o = float(np.clip(p.get("orton", 0.0), 0.0, 0.15))
    if o > 0:
        blur = gaussian(rgb, short / 60)
        screen = 1 - (1 - rgb) * (1 - blur)
        rgb = np.clip(rgb * (1 - o) + screen * o, 0, 1).astype(np.float32)

    # metrics
    small_after, _ = downscale(img.copy_with(rgb), MASK_MAX_PX)
    L_after_small = luma(small_after.rgb)
    edge_after = _edge_strength(L_after_small, band_s)
    halo_ratio = edge_after / edge_before if edge_before > 1e-6 else 1.0
    if horizon is not None and halo_ratio > 1.8:
        reviews.append(("HALO_RISK", f"x{halo_ratio:.2f}"))
    tex_after = float((L_after_small - gaussian(L_after_small, 2.0))[ground_sel].std()) if ground_sel.any() else 0.0

    if horizon_full is not None:
        focus = [w * 0.3, max(0, horizon_full - h * 0.125), w * 0.4, min(h, h * 0.25)]
    else:
        focus = [w * 0.375, h * 0.375, w * 0.25, h * 0.25]

    if debug_dir:
        save_png(sky, os.path.join(debug_dir, "sky.png"))
        save_png(t, os.path.join(debug_dir, "transmission.png"))
        for k, m in (("far", far), ("mid", mid), ("near", near)):
            save_png(m, os.path.join(debug_dir, f"depth_{k}.png"))

    info = {
        "params_used": {k: p[k] for k in ("black", "white", "far_clarity", "near_texture", "dehaze", "clahe",
                                           "clahe_tile", "orton", "sky", "sky_darken")},
        "metrics": {"black_point": round(lo, 4), "white_point": round(hi, 4), "clip_fraction": round(clip_frac, 4),
                    "sky_coverage": round(float(sky.mean()), 4), "horizon_row": horizon_full,
                    "transmission_mean": round(float(t.mean()), 3), "dehaze": dinfo,
                    "halo_ratio": round(halo_ratio, 3),
                    "ground_texture_before": round(tex_before, 5), "ground_texture_after": round(tex_after, 5)},
        "focus": [round(float(v), 1) for v in focus],
        "reviews": reviews,
    }
    return img.copy_with(rgb), info
