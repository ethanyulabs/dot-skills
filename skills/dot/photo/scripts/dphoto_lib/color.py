"""Color math shared by every stage.

All image arrays are float32, HxWx3, RGB order, gamma-encoded sRGB in 0..1 unless a
function says otherwise. OpenCV conversions on float32 input give: Lab L in 0..100 and
a/b in about -127..127; HSV H in 0..360, S and V in 0..1; YCrCb in 0..1 with Cr/Cb
centered on 0.5.
"""
from __future__ import annotations

import numpy as np

import cv2

try:  # ximgproc lives in opencv-contrib; a plain opencv build lacks it
    _HAS_XIMGPROC = hasattr(cv2, "ximgproc")
except Exception:  # pragma: no cover
    _HAS_XIMGPROC = False

LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def has_ximgproc() -> bool:
    return _HAS_XIMGPROC


def f32(a) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.float32)


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    x = np.clip(f32(x), 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(f32(x), 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def luma(rgb: np.ndarray) -> np.ndarray:
    """Rec. 709 luma in gamma space, HxW float32 0..1."""
    return f32(rgb) @ LUMA_WEIGHTS


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(f32(rgb), cv2.COLOR_RGB2Lab)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    return np.clip(cv2.cvtColor(f32(lab), cv2.COLOR_Lab2RGB), 0.0, 1.0)


def rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(f32(rgb), cv2.COLOR_RGB2HSV)


def hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    return np.clip(cv2.cvtColor(f32(hsv), cv2.COLOR_HSV2RGB), 0.0, 1.0)


def rgb_to_ycrcb(rgb: np.ndarray) -> np.ndarray:
    """Y, Cr, Cb in 0..1 (Cr/Cb centered on 0.5). Multiply by 255 for the 8-bit scale."""
    return cv2.cvtColor(f32(rgb), cv2.COLOR_RGB2YCrCb)


# Display P3 (D65) -> sRGB, linear light. Used for HEIC files tagged P3 without an ICC.
P3_TO_SRGB = np.array(
    [[1.2249401, -0.2249404, 0.0],
     [-0.0420569, 1.0420571, 0.0],
     [-0.0196376, -0.0786361, 1.0982735]],
    dtype=np.float32,
)


def p3_to_srgb(rgb: np.ndarray) -> np.ndarray:
    lin = srgb_to_linear(rgb)  # P3 uses the sRGB transfer curve
    out = lin @ P3_TO_SRGB.T
    return linear_to_srgb(np.clip(out, 0.0, 1.0))


# ---------------------------------------------------------------- curves / LUTs

def _pchip_slopes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Monotone cubic (Fritsch-Carlson) slopes."""
    h = np.diff(x)
    d = np.diff(y) / np.where(h == 0, 1e-9, h)
    m = np.zeros_like(y)
    if len(y) == 2:
        m[:] = d[0]
        return m
    for k in range(1, len(y) - 1):
        if d[k - 1] * d[k] <= 0:
            m[k] = 0.0
        else:
            w1 = 2 * h[k] + h[k - 1]
            w2 = h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
    m[0] = d[0]
    m[-1] = d[-1]
    return m


def build_curve_lut(points, n: int = 4096) -> np.ndarray:
    """points: [[in, out], ...] on the 0..255 scale (any order). Returns LUT of n floats in 0..1
    indexed by input*(n-1). Interpolation is monotone cubic, so the curve never reverses."""
    pts = sorted((float(a), float(b)) for a, b in points)
    if len(pts) < 2:
        pts = [(0.0, 0.0), (255.0, 255.0)]
    x = np.array([p[0] for p in pts]) / 255.0
    y = np.array([p[1] for p in pts]) / 255.0
    # enforce strictly increasing x and monotone y
    x = np.maximum.accumulate(x + np.arange(len(x)) * 1e-9)
    y = np.maximum.accumulate(y)
    m = _pchip_slopes(x, y)
    xs = np.linspace(0.0, 1.0, n)
    idx = np.clip(np.searchsorted(x, xs, side="right") - 1, 0, len(x) - 2)
    h = x[idx + 1] - x[idx]
    t = (xs - x[idx]) / np.where(h == 0, 1e-9, h)
    t2, t3 = t * t, t * t * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    out = h00 * y[idx] + h10 * h * m[idx] + h01 * y[idx + 1] + h11 * h * m[idx + 1]
    out[xs < x[0]] = y[0]
    out[xs > x[-1]] = y[-1]
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def identity_lut(n: int = 4096) -> np.ndarray:
    return np.linspace(0.0, 1.0, n, dtype=np.float32)


def compose_luts(*luts: np.ndarray) -> np.ndarray:
    out = identity_lut(len(luts[0]))
    for lut in luts:
        out = lookup(out, lut)
    return out


def lookup(values: np.ndarray, lut: np.ndarray) -> np.ndarray:
    n = len(lut)
    return np.interp(np.clip(values, 0.0, 1.0), np.linspace(0.0, 1.0, n), lut).astype(np.float32)


def s_curve_lut(contrast: float, n: int = 4096) -> np.ndarray:
    """contrast in -100..100. Positive steepens the midtones around 0.5; stays monotone."""
    c = float(np.clip(contrast, -100, 100)) / 100.0 * 0.4
    x = identity_lut(n)
    y = x + c * 4.0 * (x - 0.5) * x * (1.0 - x)
    return np.clip(y, 0.0, 1.0).astype(np.float32)


def blacks_whites_lut(blacks: float, whites: float, n: int = 4096) -> np.ndarray:
    """Lightroom-like Blacks/Whites in -100..100. Negative blacks crush, positive lift the
    black point; positive whites extend the white point, negative compress the top."""
    x = identity_lut(n)
    b = float(np.clip(blacks, -100, 100)) / 100.0
    w = float(np.clip(whites, -100, 100)) / 100.0
    if b < 0:
        bp = -b * 0.08
        y = (x - bp) / (1.0 - bp)
    else:
        y = x + b * 0.08 * (1.0 - x) ** 3
    y = np.clip(y, 0.0, 1.0)
    if w > 0:
        wp = 1.0 - w * 0.08
        y = y / wp
    else:
        y = y - (-w) * 0.08 * y ** 3
    return np.clip(y, 0.0, 1.0).astype(np.float32)


def apply_lut_luma(rgb: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Apply a tone LUT to the luma and scale RGB proportionally so hue is preserved.
    Channels that would exceed 1 are blended toward the target gray."""
    rgb = f32(rgb)
    L = luma(rgb)
    Ln = lookup(L, lut)
    ratio = Ln / np.maximum(L, 1e-4)
    out = rgb * ratio[..., None]
    over = out.max(axis=2) - 1.0
    mask = over > 0
    if np.any(mask):
        # pull the over-range pixels toward the neutral target luma
        k = np.clip(over / np.maximum(out.max(axis=2) - Ln, 1e-4), 0.0, 1.0)
        out = out * (1 - k[..., None]) + Ln[..., None] * k[..., None]
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def temperature_tint_gains(temperature: float, tint: float) -> np.ndarray:
    """Channel gains for Lightroom-like JPEG scale (-100..100). Positive temperature warms
    (more red, less blue); positive tint adds magenta (less green)."""
    t = float(np.clip(temperature, -100, 100)) / 100.0
    g = float(np.clip(tint, -100, 100)) / 100.0
    gains = np.array([1.0 + 0.25 * t, 1.0 - 0.20 * g, 1.0 - 0.25 * t], dtype=np.float32)
    return np.clip(gains, 0.3, 3.0)


# ---------------------------------------------------------------- filters

def box(a: np.ndarray, r: int) -> np.ndarray:
    k = 2 * int(r) + 1
    return cv2.blur(f32(a), (k, k), borderType=cv2.BORDER_REFLECT)


def gaussian(a: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return f32(a).copy()
    return cv2.GaussianBlur(f32(a), (0, 0), sigmaX=float(sigma), borderType=cv2.BORDER_REFLECT)


def _guided_filter_np(guide: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """Gray-guide guided filter (He et al.) built on cv2.blur; works for 1 or 3 channel src."""
    I = luma(guide) if guide.ndim == 3 else f32(guide)
    mean_I = box(I, r)
    var_I = box(I * I, r) - mean_I * mean_I
    srcs = [src] if src.ndim == 2 else [src[..., c] for c in range(src.shape[2])]
    outs = []
    for p in srcs:
        p = f32(p)
        mean_p = box(p, r)
        cov_Ip = box(I * p, r) - mean_I * mean_p
        a = cov_Ip / (var_I + eps)
        b = mean_p - a * mean_I
        outs.append(box(a, r) * I + box(b, r))
    if src.ndim == 2:
        return outs[0].astype(np.float32)
    return np.stack(outs, axis=2).astype(np.float32)


def guided_filter(guide: np.ndarray, src: np.ndarray, radius: int, eps: float) -> np.ndarray:
    """Edge-preserving smoothing of src guided by guide (float32 0..1, eps on the same scale).
    Uses cv2.ximgproc when available, otherwise the numpy fallback."""
    guide = f32(guide)
    src = f32(src)
    radius = max(1, int(radius))
    if _HAS_XIMGPROC:
        try:
            return cv2.ximgproc.guidedFilter(guide, src, radius, float(eps))
        except cv2.error:  # pragma: no cover - fall through to numpy
            pass
    return _guided_filter_np(guide, src, radius, eps)


def local_std(a: np.ndarray, r: int) -> np.ndarray:
    a = f32(a)
    m = box(a, r)
    v = box(a * a, r) - m * m
    return np.sqrt(np.maximum(v, 0.0)).astype(np.float32)


def unsharp(rgb: np.ndarray, radius: float, amount: float, threshold: float = 0.0) -> np.ndarray:
    """USM on luma; threshold on the 0..255 scale like Photoshop."""
    rgb = f32(rgb)
    if amount <= 0 or radius <= 0:
        return rgb.copy()
    L = luma(rgb)
    hp = L - gaussian(L, radius)
    if threshold > 0:
        t = threshold / 255.0
        hp = np.where(np.abs(hp) < t, 0.0, hp - np.sign(hp) * t)
    return np.clip(rgb + (amount * hp)[..., None], 0.0, 1.0).astype(np.float32)


def resize(a: np.ndarray, width: int, height: int) -> np.ndarray:
    a = f32(a)
    h, w = a.shape[:2]
    interp = cv2.INTER_AREA if (width * height) < (w * h) else cv2.INTER_LANCZOS4
    out = cv2.resize(a, (int(width), int(height)), interpolation=interp)
    return out.astype(np.float32)


def feather(mask: np.ndarray, px: float) -> np.ndarray:
    return np.clip(gaussian(mask, px), 0.0, 1.0) if px > 0 else f32(mask)
