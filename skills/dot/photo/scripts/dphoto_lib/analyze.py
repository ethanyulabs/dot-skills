"""Image statistics that drive style extraction and type classification.

analyze() works on a downsized copy (<= max_px pixels) and reports every measurement on the
0..1 / Lab scale documented in references/style-schema.md. Face boxes are returned in the
coordinates of the full-resolution image.
"""
from __future__ import annotations

import numpy as np

import cv2

from . import masks as M
from .color import gaussian, local_std, luma, rgb_to_hsv, rgb_to_lab, rgb_to_ycrcb
from .imageio import WorkImage, downscale

HSL_BINS = {
    "red": (345.0, 15.0), "orange": (15.0, 45.0), "yellow": (45.0, 75.0), "green": (75.0, 165.0),
    "aqua": (165.0, 195.0), "blue": (195.0, 255.0), "purple": (255.0, 285.0), "magenta": (285.0, 345.0),
}
HSL_CENTERS = {"red": 0.0, "orange": 30.0, "yellow": 60.0, "green": 120.0, "aqua": 180.0,
               "blue": 225.0, "purple": 270.0, "magenta": 315.0}
PERCENTILES = [0.5, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.5]


def hue_bin_mask(H: np.ndarray, name: str) -> np.ndarray:
    lo, hi = HSL_BINS[name]
    if lo > hi:  # wraps around 360
        return (H >= lo) | (H < hi)
    return (H >= lo) & (H < hi)


def hue_soft_weight(H: np.ndarray, name: str, falloff: float = 15.0) -> np.ndarray:
    """1 inside the bin, linear falloff over `falloff` degrees outside."""
    lo, hi = HSL_BINS[name]
    center = HSL_CENTERS[name]
    half = ((hi - lo) % 360) / 2.0
    d = np.abs((H - center + 180.0) % 360.0 - 180.0)
    return np.clip(1.0 - (d - half) / falloff, 0.0, 1.0).astype(np.float32)


def _circular_mean_deg(H: np.ndarray) -> float:
    if H.size == 0:
        return 0.0
    r = np.deg2rad(H)
    return float(np.rad2deg(np.arctan2(np.sin(r).mean(), np.cos(r).mean())) % 360.0)


def analyze(img: WorkImage, *, faces: list[M.Face] | None = None, max_px: int = 4_000_000,
            with_sky: bool = True) -> dict:
    small, scale = downscale(img, max_px)
    rgb = small.rgb
    h, w = rgb.shape[:2]
    short = min(h, w)

    if faces is None:
        faces = M.detect_faces(rgb)
    lab = rgb_to_lab(rgb)
    L = np.clip(lab[..., 0] / 100.0, 0, 1)
    a, b = lab[..., 1], lab[..., 2]

    pct = np.percentile(L, PERCENTILES)
    luma_p = {f"p{str(p).replace('.', '_')}": round(float(v), 4) for p, v in zip(PERCENTILES, pct)}

    neutral_sel = (np.abs(a) < 12) & (np.abs(b) < 12) & (L > 0.2) & (L < 0.85)
    coverage = float(neutral_sel.mean())
    neutral_fallback = coverage < 0.02
    if neutral_fallback:
        na, nb = float(np.median(a)), float(np.median(b))
    else:
        na, nb = float(a[neutral_sel].mean()), float(b[neutral_sel].mean())

    chroma = np.hypot(a, b)
    hsv = rgb_to_hsv(rgb)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sel = (S > 0.12) & (V > 0.08) & (V < 0.97)
    hsl_hist = {}
    for name in HSL_BINS:
        m = sel & hue_bin_mask(H, name)
        n = int(m.sum())
        if n == 0:
            hsl_hist[name] = {"frac": 0.0, "s": 0.0, "v": 0.0, "h": HSL_CENTERS[name]}
            continue
        hsl_hist[name] = {"frac": round(n / H.size, 4), "s": round(float(S[m].mean()), 4),
                          "v": round(float(V[m].mean()), 4), "h": round(_circular_mean_deg(H[m]), 1)}

    raw_skin = M.raw_skin(rgb)
    if faces:
        region = np.zeros((h, w), np.float32)
        for f in faces:
            x, y, bw, bh = [int(round(v)) for v in M.box_dilate(f.box, 1.6, w, h, down_extra=0.6)]
            region[y:y + bh, x:x + bw] = 1.0
        skin_sel = (raw_skin * region) > 0.5
    else:
        skin_sel = raw_skin > 0.5
    skin_cov = float(skin_sel.mean())
    if skin_cov > 0.002:
        ycc = rgb_to_ycrcb(rgb) * 255.0
        skin = {"present": True, "coverage": round(skin_cov, 4),
                "cr": round(float(ycc[..., 1][skin_sel].mean()), 1),
                "cb": round(float(ycc[..., 2][skin_sel].mean()), 1),
                "lab_mean": [round(float(lab[..., i][skin_sel].mean()), 2) for i in range(3)]}
    else:
        skin = {"present": False, "coverage": round(skin_cov, 4), "cr": None, "cb": None, "lab_mean": None}

    hp = L - gaussian(L, short / 50.0)
    mids = (L > 0.2) & (L < 0.8)
    local_contrast = float(hp[mids].std()) if mids.any() else float(hp.std())
    texture_energy = float((L - gaussian(L, 2.0)).std())

    lap = cv2.Laplacian(L, cv2.CV_32F, ksize=3)
    flat = local_std(L, 3) < 0.02
    src = np.abs(lap[flat]) if flat.sum() > 1000 else np.abs(lap)
    noise_sigma = float(1.4826 * np.median(src) / np.sqrt(20.0))

    patch = max(5, int(round(15 * short / 1500)) | 1)
    dark = M.dark_channel(rgb, patch)
    haze = {"dark_channel_mean": round(float(dark.mean()), 4),
            "dark_channel_top": round(float(dark[: h // 3].mean()), 4)}

    c = int(0.10 * short)
    corners = np.concatenate([L[:c, :c].ravel(), L[:c, -c:].ravel(), L[-c:, :c].ravel(), L[-c:, -c:].ravel()])
    cy0, cy1 = int(h * 0.35), int(h * 0.65)
    cx0, cx1 = int(w * 0.35), int(w * 0.65)
    center = L[cy0:cy1, cx0:cx1]
    vignette_ratio = float(corners.mean() / max(center.mean(), 1e-3))

    zones = {"shadows": L < 0.33, "midtones": (L >= 0.33) & (L <= 0.66), "highlights": L > 0.66}
    grade_lab = {}
    for z, zm in zones.items():
        n = int(zm.sum())
        grade_lab[z] = {"frac": round(n / L.size, 4),
                        "a": round(float(a[zm].mean()), 3) if n else 0.0,
                        "b": round(float(b[zm].mean()), 3) if n else 0.0}

    sky_cov = float(M.sky_mask(rgb).mean()) if with_sky else 0.0

    full_faces = [f.scaled(1.0 / scale).to_json() for f in faces]
    return {
        "size": [img.width, img.height],
        "analysis_scale": round(scale, 5),
        "faces": full_faces,
        "luma_percentiles": luma_p,
        "luma_mean": round(float(L.mean()), 4),
        "neutral_lab_mean": {"a": round(na, 3), "b": round(nb, 3), "coverage": round(coverage, 4),
                             "fallback": neutral_fallback},
        "chroma_mean": round(float(chroma.mean()), 3),
        "chroma_median": round(float(np.median(chroma)), 3),
        "hsl_hist": hsl_hist,
        "skin": skin,
        "local_contrast": round(local_contrast, 5),
        "texture_energy": round(texture_energy, 5),
        "noise_sigma": round(noise_sigma, 5),
        "haze": haze,
        "vignette_ratio": round(vignette_ratio, 4),
        "grade_lab": grade_lab,
        "sky_coverage": round(sky_cov, 4),
    }


def classify(analysis: dict) -> dict:
    """portrait / landscape / unknown with a confidence and the reasons, from analysis only."""
    w, h = analysis["size"]
    short = min(w, h)
    faces = analysis.get("faces", [])
    skin_cov = analysis.get("skin", {}).get("coverage", 0.0)
    sky = analysis.get("sky_coverage", 0.0)
    aspect = max(w, h) / max(1, short)
    reasons = []
    if faces:
        biggest = max(faces, key=lambda f: f["box"][2] * f["box"][3])
        frac = biggest["box"][3] / short
        reasons.append(f"{len(faces)} face(s), largest {frac:.0%} of short side")
        reasons.append(f"skin {skin_cov:.0%} of pixels")
        if frac >= 0.12:
            conf = 0.85 + (0.1 if skin_cov > 0.05 else 0.0)
            return {"value": "portrait", "confidence": round(min(conf, 0.98), 2), "reasons": reasons}
        return {"value": "portrait", "confidence": 0.6, "reasons": reasons + ["face is small"]}
    reasons.append("no face detected")
    reasons.append(f"sky {sky:.0%}, skin {skin_cov:.0%}, aspect {aspect:.2f}")
    if sky >= 0.15:
        conf = 0.75 + (0.1 if aspect >= 1.3 else 0.0)
        return {"value": "landscape", "confidence": round(conf, 2), "reasons": reasons}
    if aspect >= 1.3 and skin_cov < 0.03:
        return {"value": "landscape", "confidence": 0.7, "reasons": reasons}
    if skin_cov > 0.08:
        return {"value": "unknown", "confidence": 0.5, "reasons": reasons + ["skin without a detected face"]}
    return {"value": "unknown", "confidence": 0.4, "reasons": reasons}
