"""compare.jpg: before/after whole image, a 100% focus crop, and optional extra thumbnails."""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .color import f32, resize
from .imageio import to_uint8


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except Exception:  # pragma: no cover
        return ImageFont.load_default()


def _label(im: Image.Image, text: str, size: int = 18) -> None:
    d = ImageDraw.Draw(im)
    f = _font(size)
    pad = 4
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.rectangle([4, 4, 4 + tw + 2 * pad, 4 + th + 2 * pad], fill=(0, 0, 0))
    d.text((4 + pad, 4 + pad - bbox[1]), text, fill=(255, 255, 255), font=f)


def _fit(rgb: np.ndarray, max_w: int, max_h: int | None = None) -> np.ndarray:
    h, w = rgb.shape[:2]
    s = min(max_w / w, (max_h / h) if max_h else 1e9, 1.0)
    if s >= 1.0:
        return f32(rgb)
    return resize(rgb, max(1, round(w * s)), max(1, round(h * s)))


def crop(rgb: np.ndarray, box) -> np.ndarray:
    h, w = rgb.shape[:2]
    x, y, bw, bh = [int(round(v)) for v in box]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + bw), min(h, y + bh)
    if x1 <= x0 or y1 <= y0:
        return f32(rgb)
    return f32(rgb[y0:y1, x0:x1])


def default_focus(rgb: np.ndarray, faces: list | None) -> list:
    h, w = rgb.shape[:2]
    if faces:
        f = max(faces, key=lambda f: f["box"][2] * f["box"][3]) if isinstance(faces[0], dict) else \
            max(faces, key=lambda f: f.box[2] * f.box[3])
        box = f["box"] if isinstance(f, dict) else f.box
        x, y, bw, bh = box
        cx, cy = x + bw / 2, y + bh / 2
        nw, nh = bw * 1.4, bh * 1.4
        return [max(0, cx - nw / 2), max(0, cy - nh / 2), min(w, nw), min(h, nh)]
    cw, ch = w * 0.25, h * 0.25
    return [(w - cw) / 2, (h - ch) / 2, cw, ch]


def make_compare(before: np.ndarray, after: np.ndarray, out_path: str, *, focus: list | None = None,
                 faces: list | None = None, extra: list | None = None, max_width: int = 1800,
                 labels=("BEFORE", "AFTER"), quality: int = 88) -> dict:
    """extra: [{"label": str, "rgb": array, "rects": [[x, y, w, h], ...]}] rendered as a third row."""
    before, after = f32(before), f32(after)
    half = max_width // 2 - 4
    top_b = Image.fromarray(to_uint8(_fit(before, half)))
    top_a = Image.fromarray(to_uint8(_fit(after, half)))
    _label(top_b, labels[0])
    _label(top_a, labels[1])

    focus = focus or default_focus(before, faces)
    cb, ca = crop(before, focus), crop(after, focus)
    zoom = min(1.0, min(800, half) / max(1, cb.shape[1]))
    cb, ca = _fit(cb, min(800, half)), _fit(ca, min(800, half))
    bot_b = Image.fromarray(to_uint8(cb))
    bot_a = Image.fromarray(to_uint8(ca))
    _label(bot_b, f"{labels[0]} focus {zoom:.0%}")
    _label(bot_a, f"{labels[1]} focus {zoom:.0%}")

    rows = [(top_b, top_a), (bot_b, bot_a)]
    extra_row = []
    if extra:
        n = max(1, len(extra))
        cell = max(120, (max_width - 8 * (n - 1)) // n)
        for item in extra:
            rgb = f32(item["rgb"])
            scale = min(cell / rgb.shape[1], 420 / rgb.shape[0], 1.0)
            th = Image.fromarray(to_uint8(resize(rgb, max(1, round(rgb.shape[1] * scale)), max(1, round(rgb.shape[0] * scale)))))
            d = ImageDraw.Draw(th)
            for rect in item.get("rects", []):
                x, y, bw, bh = [v * scale for v in rect[:4]]
                d.rectangle([x, y, x + bw, y + bh], outline=(255, 220, 0), width=2)
            _label(th, item.get("label", ""), 14)
            extra_row.append(th)

    width = max(sum(im.width for im in r) + 8 for r in rows)
    if extra_row:
        width = max(width, sum(im.width for im in extra_row) + 8 * (len(extra_row) - 1))
    height = sum(max(im.height for im in r) + 8 for r in rows)
    if extra_row:
        height += max(im.height for im in extra_row) + 8
    canvas = Image.new("RGB", (width, height), (24, 24, 24))
    y = 0
    for r in rows:
        x = 0
        for im in r:
            canvas.paste(im, (x, y))
            x += im.width + 8
        y += max(im.height for im in r) + 8
    if extra_row:
        x = 0
        for im in extra_row:
            canvas.paste(im, (x, y))
            x += im.width + 8
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    canvas.save(out_path, "JPEG", quality=quality)
    return {"path": os.path.abspath(out_path), "size": [canvas.width, canvas.height],
            "focus": [round(float(v), 1) for v in focus], "focus_zoom": round(zoom, 3)}


def make_focus(before: np.ndarray, after: np.ndarray, out_path: str, *, focus: list, side: int = 800,
               labels=("BEFORE", "AFTER"), quality: int = 92) -> dict:
    """focus.jpg: true 1:1 pixels, a side x side window centered on the focus region, before | after."""
    before, after = f32(before), f32(after)
    h, w = before.shape[:2]
    x, y, bw, bh = focus
    cx, cy = x + bw / 2, y + bh / 2
    sw, sh = min(side, w), min(side, h)
    x0 = int(round(np.clip(cx - sw / 2, 0, w - sw)))
    y0 = int(round(np.clip(cy - sh / 2, 0, h - sh)))
    box = [x0, y0, sw, sh]
    ims = []
    for src, lab in ((before, labels[0]), (after, labels[1])):
        im = Image.fromarray(to_uint8(crop(src, box)))
        _label(im, f"{lab} 100%")
        ims.append(im)
    canvas = Image.new("RGB", (ims[0].width + ims[1].width + 8, max(ims[0].height, ims[1].height)), (24, 24, 24))
    canvas.paste(ims[0], (0, 0))
    canvas.paste(ims[1], (ims[0].width + 8, 0))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    canvas.save(out_path, "JPEG", quality=quality)
    return {"path": os.path.abspath(out_path), "box": box}
