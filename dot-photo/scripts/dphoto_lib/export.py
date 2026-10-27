"""print / web / dating output versions. Specs live in assets/presets/export.json."""
from __future__ import annotations

import copy
import json
import os

import numpy as np

from . import DotPhotoError
from .color import f32, resize, unsharp
from .imageio import save_jpeg, save_tiff16

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PRESETS = os.path.join(SKILL_DIR, "assets", "presets", "export.json")
KNOWN_TARGETS = ("print", "web", "dating")


def load_presets(path: str | None = None) -> dict:
    p = path or DEFAULT_PRESETS
    if not os.path.isfile(p):
        raise DotPhotoError("PRESETS_NOT_FOUND", f"no export presets at {p}", "", 2)
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- geometry

def cover_crop(rgb: np.ndarray, out_w: int, out_h: int, anchor=None, *, anchor_frac=(0.5, 0.5)) -> tuple[np.ndarray, dict]:
    """Scale to cover out_w x out_h and crop so that `anchor` (x, y in source px) lands at
    anchor_frac of the output when possible. Returns (crop, transform) with transform
    {scale, dx, dy} mapping source px -> output px as p_out = p_src*scale - (dx, dy)."""
    h, w = rgb.shape[:2]
    scale = max(out_w / w, out_h / h)
    rw, rh = max(out_w, round(w * scale)), max(out_h, round(h * scale))
    big = resize(rgb, rw, rh) if (rw, rh) != (w, h) else f32(rgb)
    if anchor is None:
        ax, ay = rw / 2, rh / 2
    else:
        ax, ay = anchor[0] * scale, anchor[1] * scale
    dx = int(round(np.clip(ax - anchor_frac[0] * out_w, 0, rw - out_w)))
    dy = int(round(np.clip(ay - anchor_frac[1] * out_h, 0, rh - out_h)))
    crop = big[dy:dy + out_h, dx:dx + out_w]
    return np.ascontiguousarray(crop), {"scale": scale, "dx": dx, "dy": dy}


def crop_box(rgb: np.ndarray, box) -> tuple[np.ndarray, dict]:
    h, w = rgb.shape[:2]
    x, y, bw, bh = box
    x0, y0 = int(round(max(0, x))), int(round(max(0, y)))
    x1, y1 = int(round(min(w, x + bw))), int(round(min(h, y + bh)))
    return np.ascontiguousarray(rgb[y0:y1, x0:x1]), {"scale": 1.0, "dx": x0, "dy": y0}


def pad_fit(rgb: np.ndarray, out_w: int, out_h: int, color=(1.0, 1.0, 1.0)) -> tuple[np.ndarray, dict]:
    h, w = rgb.shape[:2]
    scale = min(out_w / w, out_h / h)
    rw, rh = max(1, round(w * scale)), max(1, round(h * scale))
    small = resize(rgb, rw, rh)
    canvas = np.empty((out_h, out_w, 3), np.float32)
    canvas[:] = np.array(color, np.float32)
    ox, oy = (out_w - rw) // 2, (out_h - rh) // 2
    canvas[oy:oy + rh, ox:ox + rw] = small
    return canvas, {"scale": scale, "dx": -ox, "dy": -oy}


def map_box(box, tr: dict) -> list:
    x, y, w, h = box
    s = tr["scale"]
    return [x * s - tr["dx"], y * s - tr["dy"], w * s, h * s]


def source_box(tr: dict, out_w: int, out_h: int) -> list:
    """The source-pixel rectangle that ended up in the output (negative = padding)."""
    s = tr["scale"]
    return [round(tr["dx"] / s, 1), round(tr["dy"] / s, 1), round(out_w / s, 1), round(out_h / s, 1)]


def _largest(faces):
    return max(faces, key=lambda f: f.box[2] * f.box[3]) if faces else None


def _face_center(face):
    x, y, w, h = face.box
    return (x + w / 2, y + h / 2)


# ---------------------------------------------------------------- targets

def export_print(rgb, *, spec: dict, paper: str, finish: str, fit: str, out_dir: str, exif, faces, tiff16: bool):
    if paper not in spec["papers"]:
        raise DotPhotoError("BAD_PAPER", f"unknown paper '{paper}'", f"choices: {', '.join(spec['papers'])}", 2)
    if finish not in spec["sharpen"]:
        raise DotPhotoError("BAD_FINISH", f"unknown finish '{finish}'", f"choices: {', '.join(spec['sharpen'])}", 2)
    ppi = int(spec["ppi"])
    pw, ph = spec["papers"][paper]
    h, w = rgb.shape[:2]
    if (w >= h) != (pw >= ph):
        pw, ph = ph, pw
    out_w, out_h = int(round(pw * ppi)), int(round(ph * ppi))
    face = _largest(faces)
    if fit == "pad":
        out, tr = pad_fit(rgb, out_w, out_h, tuple(spec.get("pad_color", (1, 1, 1))))
    else:
        out, tr = cover_crop(rgb, out_w, out_h, _face_center(face) if face else None)
    sh = spec["sharpen"][finish]
    out = unsharp(out, sh["radius"], sh["amount"], sh["threshold"])
    name = f"print_{paper}_{finish}"
    path = os.path.join(out_dir, name + ".jpg")
    info = save_jpeg(out, path, quality=int(spec["quality"]), ppi=ppi, exif=exif,
                     strip_exif=not spec.get("keep_exif", True), strip_gps=spec.get("strip_gps", True),
                     embed_srgb=spec.get("embed_icc", True), subsampling=spec.get("subsampling", 0))
    upscale = round(float(tr["scale"]), 3)
    res = {"target": "print", "name": name, "path": info["path"], "size": info["size"], "ppi": ppi,
           "quality": info["quality"], "exif_stripped": info["exif_stripped"], "paper": paper, "finish": finish,
           "fit": fit, "upscale": upscale, "crop_box_in_source": source_box(tr, out_w, out_h),
           "preview": out, "rects": []}
    if face:
        res["face_box_in_output"] = [round(v, 1) for v in map_box(face.box, tr)]
        res["rects"] = [res["face_box_in_output"]]
    if tiff16:
        res["tiff"] = save_tiff16(out, os.path.join(out_dir, name + ".tif"), ppi=ppi)["path"]
    return res


def export_web(rgb, *, spec: dict, out_dir: str, exif):
    h, w = rgb.shape[:2]
    long_edge = int(spec["long_edge"])
    scale = min(1.0, long_edge / max(h, w))
    out = resize(rgb, max(1, round(w * scale)), max(1, round(h * scale))) if scale < 1 else f32(rgb)
    sh = spec["sharpen"]
    out = unsharp(out, sh["radius"], sh["amount"], sh["threshold"])
    path = os.path.join(out_dir, "web.jpg")
    info = save_jpeg(out, path, quality=int(spec["quality"]), exif=exif, strip_exif=spec.get("strip_exif", True),
                     embed_srgb=spec.get("embed_icc", True))
    return {"target": "web", "name": "web", "path": info["path"], "size": info["size"], "ppi": None,
            "quality": info["quality"], "exif_stripped": info["exif_stripped"], "preview": out, "rects": []}


def _dating_crop(rgb, face, out_w, out_h, spec) -> tuple[np.ndarray, dict, dict]:
    """Face-anchored crop for a dating card; returns (crop, transform, notes)."""
    h, w = rgb.shape[:2]
    aspect = out_w / out_h
    notes = {}
    if face is None:
        out, tr = cover_crop(rgb, out_w, out_h, None)
        notes["anchor"] = "center"
        return out, tr, notes
    fx, fy = _face_center(face)
    fh = face.box[3]
    crop_h = fh / spec["face_height_frac"]
    # avoid heavy upscaling: enlarge the crop until the upscale stays within max_upscale
    min_crop_h = out_h / float(spec.get("max_upscale", 1.67))
    crop_h = max(crop_h, min_crop_h)
    bounded = crop_h > min(h, w / aspect)
    crop_h = min(crop_h, h, w / aspect)
    crop_w = crop_h * aspect
    x0 = float(np.clip(fx - crop_w / 2, 0, w - crop_w))
    y0 = float(np.clip(fy - spec["face_center_y"] * crop_h, 0, h - crop_h))
    region, tr0 = crop_box(rgb, [x0, y0, crop_w, crop_h])
    out, tr1 = cover_crop(region, out_w, out_h, None)
    tr = {"scale": tr1["scale"], "dx": tr0["dx"] * tr1["scale"] + tr1["dx"], "dy": tr0["dy"] * tr1["scale"] + tr1["dy"]}
    notes["anchor"] = "face"
    notes["face_height_frac"] = round(fh / crop_h, 3)
    notes["upscale"] = round(out_h / crop_h, 3)
    notes["bounded_by_image"] = bool(bounded)  # the photo is too small for the 30 % face rule
    return out, tr, notes


def export_dating(rgb, *, spec: dict, out_dir: str, faces, exif, retouch: bool, seed: int) -> tuple[list, list]:
    from . import style as S
    from .portrait import retouch as do_retouch, sharpen_eyes
    from .imageio import WorkImage
    reviews: list[tuple[str, str]] = []
    base = WorkImage(rgb=f32(rgb))
    st = S.resolve(spec.get("style", "dating-safe"))
    forbid = spec.get("forbid", {})
    st = copy.deepcopy(st)
    st["effects"]["grain"] = min(st["effects"].get("grain", 0), forbid.get("grain_max", 0))
    st["effects"]["vignette"] = max(st["effects"].get("vignette", 0), forbid.get("vignette_min", -10))
    for z, g in st.get("grade", {}).items():
        if isinstance(g, dict) and "sat" in g:
            g["sat"] = min(g["sat"], forbid.get("grade_sat_max", 15))
    styled, _ = S.apply(base, st, strength=1.0, mode="params", seed=seed)
    face = _largest(faces)
    if faces and retouch:
        styled, _ = do_retouch(styled, faces=faces, skin_strength=float(spec.get("skin_strength", 0.35)),
                               blemish=True, remove_moles=False, eye_sharpen=float(spec.get("eye_sharpen", 0.25)))
    elif faces:
        styled = styled.copy_with(sharpen_eyes(styled.rgb, faces, float(spec.get("eye_sharpen", 0.25))))
    if face is None:
        reviews.append(("NO_FACE", "dating crop is centered"))
    results = []
    for vname, v in spec["variants"].items():
        out_w, out_h = int(v["size"][0]), int(v["size"][1])
        out, tr, notes = _dating_crop(styled.rgb, face, out_w, out_h, spec)
        sh = spec.get("sharpen")
        if sh:
            out = unsharp(out, sh["radius"], sh["amount"], sh["threshold"])
        name = f"dating_{vname}"
        path = os.path.join(out_dir, name + ".jpg")
        info = save_jpeg(out, path, quality=int(spec["quality"]), exif=exif, strip_exif=spec.get("strip_exif", True),
                         embed_srgb=spec.get("embed_icc", True))
        safe_w = spec.get("card_safe_aspect", 0.7) * out_h
        safe = [round((out_w - safe_w) / 2, 1), 0, round(safe_w, 1), out_h]
        res = {"target": name, "name": name, "path": info["path"], "size": info["size"], "ppi": None,
               "quality": info["quality"], "exif_stripped": info["exif_stripped"], "retouched": bool(faces and retouch),
               "style": st["name"], "crop": notes, "crop_box_in_source": source_box(tr, out_w, out_h),
               "safe_area": safe, "preview": out, "rects": [safe]}
        if face is not None:
            fb = map_box(face.box, tr)
            res["face_box_in_output"] = [round(float(x), 1) for x in fb]
            res["face_center_frac"] = [round((fb[0] + fb[2] / 2) / out_w, 3), round((fb[1] + fb[3] / 2) / out_h, 3)]
            res["face_height_frac"] = round(fb[3] / out_h, 3)
            res["face_in_safe_area"] = bool(fb[0] >= safe[0] - 1 and fb[0] + fb[2] <= safe[0] + safe[2] + 1)
            res["rects"].append(res["face_box_in_output"])
            if res["face_height_frac"] < spec.get("face_height_min_frac", 0.18):
                reviews.append(("DATING_FACE_TOO_SMALL", f"{vname}: {res['face_height_frac']:.0%}"))
        if notes.get("upscale", 1.0) > float(spec.get("max_upscale", 1.67)) + 0.01:
            reviews.append(("DATING_UPSCALE_HIGH", f"{vname}: x{notes['upscale']:.2f}"))
        results.append(res)
    return results, reviews


def export(img, *, targets: list[str], presets: dict, faces: list, paper: str = "4x6", finish: str = "matte",
           fit: str = "crop", out_dir: str, exif=None, tiff16: bool = False, dating_retouch: bool = True,
           seed: int = 0) -> tuple[list, dict]:
    bad = [t for t in targets if t not in KNOWN_TARGETS]
    if bad:
        raise DotPhotoError("BAD_TARGET", f"unknown export target(s): {', '.join(bad)}",
                            f"choices: {', '.join(KNOWN_TARGETS)}", 2)
    os.makedirs(out_dir, exist_ok=True)
    rgb = f32(img.rgb)
    results: list = []
    reviews: list = []
    if "print" in targets:
        r = export_print(rgb, spec=presets["print"], paper=paper, finish=finish, fit=fit, out_dir=out_dir,
                         exif=exif, faces=faces, tiff16=tiff16)
        results.append(r)
        if r["upscale"] > float(presets["print"].get("max_upscale", 1.5)):
            reviews.append(("PRINT_UPSCALE_HIGH", f"{paper}: x{r['upscale']:.2f}"))
    if "web" in targets:
        results.append(export_web(rgb, spec=presets["web"], out_dir=out_dir, exif=exif))
    if "dating" in targets:
        r, rv = export_dating(rgb, spec=presets["dating"], out_dir=out_dir, faces=faces, exif=exif,
                              retouch=dating_retouch, seed=seed)
        results.extend(r)
        reviews.extend(rv)
    info = {"targets": targets, "presets_version": presets.get("version"),
            "params_used": {"paper": paper, "finish": finish, "fit": fit, "tiff16": tiff16,
                            "dating_retouch": dating_retouch, "dating_style": presets["dating"].get("style")},
            "reviews": reviews}
    return results, info
