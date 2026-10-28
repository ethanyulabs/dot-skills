"""Face detection, skin / luminosity / sky masks, haze transmission and depth bands.

Masks are float32 HxW in 0..1 at the resolution of the array they were computed from;
upscale() brings one to full size. Boxes are [x, y, w, h] in pixels of the same array.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

import cv2

from .color import f32, feather, gaussian, guided_filter, local_std, luma, rgb_to_hsv, rgb_to_ycrcb

SKIN_CR = (133.0, 173.0)
SKIN_CB = (77.0, 127.0)


@dataclass
class Face:
    box: list            # [x, y, w, h]
    eyes: list = field(default_factory=list)   # [[x, y, w, h], ...] absolute
    confidence: float = 0.0
    kind: str = "frontal"

    def to_json(self) -> dict:
        return {"box": [int(v) for v in self.box], "eyes": [[int(v) for v in e] for e in self.eyes],
                "confidence": round(float(self.confidence), 3), "kind": self.kind}

    def scaled(self, s: float) -> "Face":
        return Face([v * s for v in self.box], [[v * s for v in e] for e in self.eyes], self.confidence, self.kind)


def _cascade(name: str):
    path = os.path.join(cv2.data.haarcascades, name)
    if not os.path.isfile(path):
        return None
    c = cv2.CascadeClassifier(path)
    return None if c.empty() else c


def haar_available() -> bool:
    return _cascade("haarcascade_frontalface_default.xml") is not None


def box_dilate(box, factor: float, width: int, height: int, *, down_extra: float = 0.0) -> list:
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    nw, nh = w * factor, h * factor
    x0 = max(0, cx - nw / 2)
    y0 = max(0, cy - nh / 2)
    x1 = min(width, cx + nw / 2)
    y1 = min(height, cy + nh / 2 + h * down_extra)
    return [x0, y0, x1 - x0, y1 - y0]


def skin_fraction(rgb: np.ndarray, box=None) -> float:
    m = raw_skin(rgb)
    if box is not None:
        x, y, w, h = [int(round(v)) for v in box]
        m = m[y:y + h, x:x + w]
    return float(m.mean()) if m.size else 0.0


def raw_skin(rgb: np.ndarray) -> np.ndarray:
    ycc = rgb_to_ycrcb(rgb) * 255.0
    cr, cb = ycc[..., 1], ycc[..., 2]
    return ((cr >= SKIN_CR[0]) & (cr <= SKIN_CR[1]) & (cb >= SKIN_CB[0]) & (cb <= SKIN_CB[1])).astype(np.float32)


def detect_faces(rgb: np.ndarray) -> list[Face]:
    """Haar frontal, then profile. Boxes are filtered by size and skin content."""
    h, w = rgb.shape[:2]
    short = min(h, w)
    gray = (np.clip(luma(rgb), 0, 1) * 255).astype(np.uint8)
    gray = cv2.equalizeHist(gray)
    min_size = max(24, int(0.04 * short))
    found: list[Face] = []
    for name, kind, base_conf in (("haarcascade_frontalface_default.xml", "frontal", 0.9),
                                  ("haarcascade_profileface.xml", "profile", 0.7)):
        c = _cascade(name)
        if c is None:
            continue
        rects = c.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(min_size, min_size))
        for (x, y, fw, fh) in (rects if len(rects) else []):
            box = [float(x), float(y), float(fw), float(fh)]
            sf = skin_fraction(rgb, box)
            if sf < 0.25 or fh < 0.04 * short:
                continue
            found.append(Face(box=box, confidence=base_conf * min(1.0, 0.5 + sf), kind=kind))
        if found:
            break
    # drop boxes nested inside a bigger one
    found.sort(key=lambda f: f.box[2] * f.box[3], reverse=True)
    kept: list[Face] = []
    for f in found:
        fx, fy, fw, fh = f.box
        inside = any(fx >= k.box[0] - 2 and fy >= k.box[1] - 2 and fx + fw <= k.box[0] + k.box[2] + 2
                     and fy + fh <= k.box[1] + k.box[3] + 2 for k in kept)
        if not inside:
            kept.append(f)
    eye_c = _cascade("haarcascade_eye.xml")
    for f in kept:
        f.eyes = _detect_eyes(gray, f.box, eye_c)
    return kept


def _detect_eyes(gray: np.ndarray, box, eye_c) -> list:
    if eye_c is None:
        return []
    x, y, w, h = [int(round(v)) for v in box]
    roi = gray[y:y + int(h * 0.6), x:x + w]
    if roi.size == 0:
        return []
    rects = eye_c.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=6,
                                   minSize=(max(8, w // 10), max(8, w // 10)))
    eyes = []
    for (ex, ey, ew, eh) in (rects if len(rects) else []):
        eyes.append([float(x + ex), float(y + ey), float(ew), float(eh)])
    eyes.sort(key=lambda e: e[2] * e[3], reverse=True)
    return eyes[:2]


def eye_regions(faces: list[Face], height: int, width: int) -> np.ndarray:
    """1 where the eyes are (detected boxes, or a geometric guess inside each face)."""
    m = np.zeros((height, width), np.float32)
    for f in faces:
        x, y, w, h = f.box
        boxes = f.eyes
        if not boxes:
            boxes = [[x + w * 0.18, y + h * 0.28, w * 0.26, h * 0.16],
                     [x + w * 0.56, y + h * 0.28, w * 0.26, h * 0.16]]
        for (ex, ey, ew, eh) in boxes:
            cx, cy = ex + ew / 2, ey + eh / 2
            cv2.ellipse(m, (int(cx), int(cy)), (int(ew * 0.65), int(eh * 0.6)), 0, 0, 360, 1.0, -1)
    return m


def lip_region(rgb: np.ndarray, faces: list[Face], skin_cr_center: float) -> np.ndarray:
    """1 on redder-than-skin pixels in the lower third of each face box."""
    h, w = rgb.shape[:2]
    m = np.zeros((h, w), np.float32)
    if not faces:
        return m
    cr = rgb_to_ycrcb(rgb)[..., 1] * 255.0
    for f in faces:
        x, y, fw, fh = [int(round(v)) for v in f.box]
        y0 = y + int(fh * 0.62)
        y1 = min(h, y + fh)
        x0, x1 = max(0, x + int(fw * 0.2)), min(w, x + int(fw * 0.8))
        if y1 <= y0 or x1 <= x0:
            continue
        sub = cr[y0:y1, x0:x1]
        m[y0:y1, x0:x1] = np.maximum(m[y0:y1, x0:x1], (sub > skin_cr_center + 12).astype(np.float32))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)


def skin_mask(rgb: np.ndarray, faces: list[Face], *, max_coverage: float = 0.45) -> tuple[np.ndarray, dict]:
    """Soft skin mask. With faces it is limited to the dilated face boxes and excludes eyes and lips.
    Without faces the whole-image skin mask is used, capped at max_coverage (then zeroed)."""
    h, w = rgb.shape[:2]
    short = min(h, w)
    raw = raw_skin(rgb)
    info = {"faces": len(faces), "raw_coverage": float(raw.mean())}
    if faces:
        region = np.zeros((h, w), np.float32)
        for f in faces:
            x, y, bw, bh = [int(round(v)) for v in box_dilate(f.box, 1.6, w, h, down_extra=0.6)]
            region[y:y + bh, x:x + bw] = 1.0
        m = raw * region
        ycc = rgb_to_ycrcb(rgb)[..., 1] * 255.0
        cr_center = float(np.median(ycc[m > 0.5])) if np.any(m > 0.5) else 150.0
        m = m * (1.0 - eye_regions(faces, h, w)) * (1.0 - lip_region(rgb, faces, cr_center))
    else:
        m = raw
        if float(m.mean()) > max_coverage:
            info["capped"] = True
            m = np.zeros_like(m)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    m = feather(m, max(1.0, short / 150.0))
    info["coverage"] = float(m.mean())
    return np.clip(m, 0, 1).astype(np.float32), info


def luminosity_masks(rgb: np.ndarray) -> dict:
    L = np.clip(luma(rgb), 0, 1)
    lights = L * L
    darks = (1 - L) * (1 - L)
    mids = np.clip(1 - lights - darks, 0, 1)
    return {"lights": lights.astype(np.float32), "darks": darks.astype(np.float32), "mids": mids.astype(np.float32)}


def sky_mask(rgb: np.ndarray) -> np.ndarray:
    """Low-texture bright blue/cyan/gray regions connected to the top edge."""
    h, w = rgb.shape[:2]
    hsv = rgb_to_hsv(rgb)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    L = luma(rgb)
    tex = local_std(L, 3)
    bluish = (H >= 170) & (H <= 265)
    grayish = S < 0.12
    cand = (V > 0.35) & (S < 0.65) & (bluish | grayish) & (tex < 0.035)
    rows = np.arange(h)[:, None]
    cand &= rows < int(h * 0.8)
    cand8 = cand.astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    cand8 = cv2.morphologyEx(cand8, cv2.MORPH_OPEN, k)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cand8, connectivity=8)
    keep = np.zeros((h, w), np.float32)
    top_labels = set(np.unique(labels[0:max(1, h // 50), :]).tolist())
    for i in range(1, n):
        if i in top_labels and stats[i, cv2.CC_STAT_AREA] >= 0.005 * h * w:
            keep[labels == i] = 1.0
    if keep.sum() == 0:
        return keep
    r = max(2, int(min(h, w) / 50))
    refined = guided_filter(L, keep, r, 1e-3)
    return np.clip(refined, 0, 1).astype(np.float32)


def dark_channel(rgb: np.ndarray, patch: int = 15) -> np.ndarray:
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (patch, patch))
    return cv2.erode(np.min(f32(rgb), axis=2), k)


def atmosphere(rgb: np.ndarray, dark: np.ndarray) -> np.ndarray:
    n = max(1, int(dark.size * 0.001))
    idx = np.argpartition(dark.ravel(), -n)[-n:]
    flat = rgb.reshape(-1, 3)[idx]
    A = flat.mean(axis=0)
    return np.clip(A, 0.5, 1.0).astype(np.float32)


def transmission(rgb: np.ndarray, A: np.ndarray, *, omega: float = 0.95, patch: int = 15,
                 t0: float = 0.1) -> np.ndarray:
    norm = f32(rgb) / np.maximum(A, 1e-3)[None, None, :]
    t = 1.0 - omega * dark_channel(np.clip(norm, 0, 1), patch)
    r = max(4, int(min(rgb.shape[:2]) / 25))
    t = guided_filter(luma(rgb), t.astype(np.float32), r, 1e-3)
    return np.clip(t, t0, 1.0).astype(np.float32)


def depth_bands(t: np.ndarray, sky: np.ndarray) -> dict:
    """far / mid / near soft masks from transmission and the sky mask; they sum to 1."""
    h, w = t.shape
    short = min(h, w)
    far = np.maximum(sky, (t < 0.5).astype(np.float32))
    rows = (np.arange(h)[:, None] >= int(h * 2 / 3)).astype(np.float32)
    near = (t > 0.8).astype(np.float32) * np.repeat(rows, w, axis=1) * (1 - sky)
    far = feather(far, short / 60)
    near = feather(near, short / 60) * (1 - far)
    mid = np.clip(1 - far - near, 0, 1)
    s = np.maximum(far + mid + near, 1e-6)
    return {"far": (far / s).astype(np.float32), "mid": (mid / s).astype(np.float32),
            "near": (near / s).astype(np.float32)}


def upscale(mask: np.ndarray, height: int, width: int) -> np.ndarray:
    if mask.shape[0] == height and mask.shape[1] == width:
        return mask
    return cv2.resize(f32(mask), (int(width), int(height)), interpolation=cv2.INTER_LINEAR).astype(np.float32)


def radial_falloff(height: int, width: int) -> np.ndarray:
    """0 at center, 1 at the corners."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    r = np.sqrt(((x - cx) / cx) ** 2 + ((y - cy) / cy) ** 2) / np.sqrt(2)
    return np.clip(r, 0, 1).astype(np.float32)


def vertical_gradient(height: int, width: int, top: float = 1.0, bottom_row: int | None = None) -> np.ndarray:
    """top..0 falling linearly from row 0 to bottom_row (default 55% of height)."""
    br = bottom_row if bottom_row is not None else int(height * 0.55)
    g = np.zeros((height, width), np.float32)
    rows = np.arange(height, dtype=np.float32)
    g[:] = np.clip(top * (1 - rows / max(1, br)), 0, 1)[:, None]
    return g
