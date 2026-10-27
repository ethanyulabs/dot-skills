"""Portrait retouching: blemish removal by inpainting, texture-preserving skin smoothing by
frequency separation (only the low band is smoothed, the high band is put back unchanged),
and a little eye sharpening. The amount is a plain alpha blend inside the skin mask.
"""
from __future__ import annotations

import json
import os

import numpy as np

import cv2

from . import masks as M
from .color import f32, feather, gaussian, guided_filter, has_ximgproc, local_std, luma, rgb_to_lab, unsharp
from .imageio import WorkImage, downscale, save_png, to_uint8

MASK_MAX_PX = 4_000_000


def auto_radius(short_side: int) -> int:
    return int(np.clip(round(short_side / 1000.0 * 4), 3, 8))


def detect_blemishes(rgb: np.ndarray, skin: np.ndarray, r: int, scale2: float) -> dict:
    """Small dark or red spots inside the skin mask. The local reference is a median filter, so
    a spot does not drag the reference down the way an edge-preserving filter would.
    Blemish: area in [3, 400]*scale2 and (area < 150*scale2 or low contrast).
    Mole: area >= 150*scale2 with contrast >= 0.25 (kept unless asked to remove)."""
    L = luma(rgb)
    lab = rgb_to_lab(rgb)
    a = lab[..., 1]
    rr = max(4, r * 4)
    k = 2 * rr + 1
    L8 = to_uint8(L)
    low = cv2.medianBlur(L8, k).astype(np.float32) / 255.0
    diff = low - L                               # positive where darker than surroundings
    a8 = np.clip(a + 128.0, 0, 255).astype(np.uint8)
    a_low = cv2.medianBlur(a8, k).astype(np.float32) - 128.0
    red = a - a_low                              # positive where redder than surroundings
    sel = skin > 0.5
    if not sel.any():
        return {"blemish": np.zeros(L.shape, np.uint8), "moles": np.zeros(L.shape, np.uint8),
                "n_blemish": 0, "n_mole": 0, "blobs": [], "threshold": 0.0}
    sigma_tex = float((L - gaussian(L, 1.5))[sel].std())
    thr = max(4.0 * sigma_tex, 0.06)
    cand = ((diff > thr) | (red > 8.0)) & sel
    cand8 = cand.astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand8, connectivity=8)
    blemish = np.zeros(L.shape, np.uint8)
    moles = np.zeros(L.shape, np.uint8)
    n_blemish = n_mole = 0
    blobs = []
    for i in range(1, n):
        area = float(stats[i, cv2.CC_STAT_AREA])
        x, y, w, h = [int(v) for v in stats[i, :4]]
        if area < 3 * scale2 or area > 400 * scale2:
            continue
        if area / max(1.0, float(w * h)) < 0.45:   # elongated: wrinkle / hair, not a spot
            continue
        comp = labels == i
        contrast = float(diff[comp].mean())
        blob = {"box": [x, y, w, h], "area": area, "contrast": round(contrast, 3)}
        if area >= 150 * scale2 and contrast >= 0.25:
            moles[comp] = 1
            n_mole += 1
            blobs.append(dict(blob, kind="mole"))
            continue
        blemish[comp] = 1
        n_blemish += 1
        blobs.append(dict(blob, kind="blemish"))
    return {"blemish": blemish, "moles": moles, "n_blemish": n_blemish, "n_mole": n_mole, "blobs": blobs,
            "threshold": round(thr, 4)}


def inpaint_spots(rgb: np.ndarray, spots: np.ndarray, r: int) -> np.ndarray:
    """Inpaint each spot inside its own ROI and paste only the delta back (float precision)."""
    if spots.max() == 0:
        return rgb
    out = f32(rgb).copy()
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    dil = cv2.dilate(spots, k)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dil, connectivity=8)
    h, w = rgb.shape[:2]
    margin = 6 * r + 4
    for i in range(1, n):
        x, y, bw, bh = [int(v) for v in stats[i, :4]]
        x0, y0 = max(0, x - margin), max(0, y - margin)
        x1, y1 = min(w, x + bw + margin), min(h, y + bh + margin)
        roi = out[y0:y1, x0:x1]
        m = (labels[y0:y1, x0:x1] == i).astype(np.uint8)
        roi8 = to_uint8(roi)
        filled = cv2.inpaint(roi8, m, max(3, r), cv2.INPAINT_TELEA).astype(np.float32) / 255.0
        soft = feather(m.astype(np.float32), max(1.0, r * 0.5))
        out[y0:y1, x0:x1] = roi + (filled - roi) * soft[..., None]
    return np.clip(out, 0, 1).astype(np.float32)


def sharpen_eyes(rgb: np.ndarray, faces: list, amount: float, radius: float = 1.0) -> np.ndarray:
    if amount <= 0 or not faces:
        return f32(rgb)
    h, w = rgb.shape[:2]
    m = feather(M.eye_regions(faces, h, w), max(2.0, min(h, w) / 300))
    if m.max() == 0:
        return f32(rgb)
    sharp = unsharp(rgb, radius, amount, threshold=1.0)
    return np.clip(rgb + (sharp - rgb) * m[..., None], 0, 1).astype(np.float32)


def retouch(img: WorkImage, *, faces: list, skin_strength: float = 0.55, blemish: bool = True,
            remove_moles: bool = False, eye_sharpen: float = 0.3, guided_radius="auto",
            debug_dir: str | None = None) -> tuple[WorkImage, dict]:
    rgb = f32(img.rgb)
    h, w = rgb.shape[:2]
    short = min(h, w)
    alpha = float(np.clip(skin_strength, 0.0, 0.85))
    r = auto_radius(short) if guided_radius in (None, "auto") else int(guided_radius)
    eps = 0.01
    r_smooth = 5 * r
    scale2 = (short / 1000.0) ** 2
    reviews: list[tuple[str, str]] = []
    warnings: list[str] = []
    if not has_ximgproc():
        reviews.append(("GUIDED_FILTER_FALLBACK", ""))

    # masks on a reduced copy, then upscaled
    small, s = downscale(img, MASK_MAX_PX)
    faces_small = [f.scaled(s) for f in faces]
    skin_small, sinfo = M.skin_mask(small.rgb, faces_small)
    skin = M.upscale(skin_small, h, w)
    coverage = float(skin.mean())
    if faces and coverage < 0.04:
        reviews.append(("SKIN_LOW_COVERAGE", f"{coverage:.1%}"))
    if coverage > 0.45:
        reviews.append(("SKIN_HIGH_COVERAGE", f"{coverage:.1%}"))
    if not faces and sinfo.get("capped"):
        warnings.append("no face and skin-like pixels exceed 45% of the frame: skin mask disabled")

    out = rgb
    n_blemish = n_mole = n_mole_removed = 0
    blobs = []
    if blemish and coverage > 0:
        det = detect_blemishes(out, skin, r, scale2)
        n_blemish, n_mole, blobs = det["n_blemish"], det["n_mole"], det["blobs"]
        spots = det["blemish"]
        if remove_moles and n_mole:
            spots = np.maximum(spots, det["moles"])
            n_mole_removed = n_mole
        if n_blemish > 40:
            reviews.append(("BLEMISH_COUNT_HIGH", str(n_blemish)))
        out = inpaint_spots(out, spots, r)
        if debug_dir:
            save_png(spots.astype(np.float32), os.path.join(debug_dir, "blemish.png"))
            save_png(det["moles"].astype(np.float32), os.path.join(debug_dir, "moles.png"))

    # frequency separation: smooth only the low band inside the skin mask
    texture_retained = 1.0
    if coverage > 0 and alpha > 0:
        low = guided_filter(out, out, r, eps)
        high = out - low
        smooth = guided_filter(low, low, r_smooth, 0.02)
        m = (skin * alpha).astype(np.float32)
        result = np.clip(out + (smooth - low) * m[..., None], 0, 1).astype(np.float32)
        sel = skin > 0.5
        if sel.any():
            high_after = result - guided_filter(result, result, r, eps)
            texture_retained = float(np.clip(high_after[sel].std() / max(high[sel].std(), 1e-6), 0, 1.5))
        out = result
        if texture_retained < 0.6:
            reviews.append(("TEXTURE_RETAINED_LOW", f"{texture_retained:.2f}"))

    out = sharpen_eyes(out, faces, eye_sharpen, radius=max(0.8, short / 2500))

    sel = skin > 0.5
    delta_e = 0.0
    if sel.any():
        d = rgb_to_lab(out) - rgb_to_lab(rgb)
        delta_e = float(np.sqrt((d ** 2).sum(axis=2))[sel].mean())

    if debug_dir:
        save_png(skin, os.path.join(debug_dir, "skin.png"))
        with open(os.path.join(debug_dir, "faces.json"), "w", encoding="utf-8") as fh:
            json.dump([f.to_json() for f in faces], fh, indent=2)

    info = {
        "skin_coverage": round(coverage, 4),
        "params_used": {"skin_strength": alpha, "guided_radius": r, "eps": eps, "smooth_radius": r_smooth,
                        "blemish": bool(blemish), "remove_moles": bool(remove_moles), "eye_sharpen": float(eye_sharpen),
                        "faces": len(faces)},
        "metrics": {"texture_retained": round(texture_retained, 3), "blemishes_removed": n_blemish,
                    "moles_kept": n_mole - n_mole_removed, "moles_removed": n_mole_removed,
                    "skin_delta_e_mean": round(delta_e, 2)},
        "blobs": blobs[:60],
        "reviews": reviews, "warnings": warnings,
    }
    return img.copy_with(out), info
