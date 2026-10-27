"""Command line interface. Every command prints exactly one JSON line on stdout.

Exit codes: 0 ok, 2 bad arguments, 3 input cannot be decoded, 4 dependency missing, 5 processing error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from . import DotPhotoError, __version__
from .report import Timer, build, review, write

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(SKILL_DIR, "assets")
MEMORY_BUDGET_BYTES = 4 * 1024 ** 3
AUTO_MAX_PROCESS_PX = 24_000_000


class Ctx:
    def __init__(self, args, input_path: str | None):
        from .imageio import default_out_dir
        self.args = args
        self.input = os.path.abspath(input_path) if input_path else None
        self.out_dir = os.path.abspath(args.out) if getattr(args, "out", None) else (
            default_out_dir(self.input) if self.input else os.getcwd())
        self.debug = bool(getattr(args, "debug", False))
        self.quiet = bool(getattr(args, "quiet", False))
        self.seed = int(getattr(args, "seed", 0) or 0)
        self.max_analyze_px = int(getattr(args, "max_analyze_px", 4_000_000) or 4_000_000)
        self.max_process_px = int(getattr(args, "max_process_px", 0) or 0)
        self.warnings: list[str] = []
        self.reviews: list[dict] = []
        self.timer = Timer()
        self.log_path = os.path.join(self.out_dir, "log.txt")

    def ensure_out(self):
        os.makedirs(self.out_dir, exist_ok=True)

    def log(self, msg: str):
        if not self.quiet:
            print(msg, file=sys.stderr, flush=True)
        try:
            self.ensure_out()
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except Exception:
            pass

    def warn(self, msg: str):
        self.warnings.append(msg)
        self.log("warning: " + msg)

    def add_review(self, code: str, detail: str = "", suggest: str | None = None):
        if not any(r["code"] == code for r in self.reviews):
            self.reviews.append(review(code, detail, suggest))

    def debug_dir(self) -> str | None:
        if not self.debug:
            return None
        d = os.path.join(self.out_dir, "masks")
        os.makedirs(d, exist_ok=True)
        return d


# ---------------------------------------------------------------- shared steps

def load_full(ctx: Ctx):
    from .imageio import load
    img = load(ctx.input, workdir=ctx.out_dir if ctx.debug else None)
    ctx.log(f"decoded {ctx.input}: {img.width}x{img.height}, profile {img.source['source_profile']}, "
            f"orientation {img.source['orientation']}")
    for w in img.source.get("warnings", []):
        ctx.warn(w)
    h, w = img.rgb.shape[:2]
    limit = ctx.max_process_px
    if limit <= 0 and h * w * 3 * 4 * 8 > MEMORY_BUDGET_BYTES:
        limit = AUTO_MAX_PROCESS_PX
    if limit > 0 and h * w > limit:
        from .imageio import downscale
        img, s = downscale(img, limit)
        img.source["process_scale"] = s
        ctx.add_review("LARGE_IMAGE_DOWNSCALED", f"{w}x{h} -> {img.width}x{img.height}")
    ctx.timer.mark("decode")
    return img


def analyze_image(ctx: Ctx, img, *, faces=None):
    from .analyze import analyze, classify
    an = analyze(img, faces=faces, max_px=ctx.max_analyze_px)
    an["type"] = classify(an)
    ctx.timer.mark("analyze")
    ctx.log(f"analyzed: type {an['type']['value']} ({an['type']['confidence']}), {len(an['faces'])} face(s), "
            f"skin {an['skin']['coverage']:.1%}, sky {an['sky_coverage']:.1%}")
    return an


def faces_from_analysis(an: dict, select=None):
    from .masks import Face
    faces = [Face(box=f["box"], eyes=f.get("eyes", []), confidence=f.get("confidence", 0), kind=f.get("kind", "frontal"))
             for f in an.get("faces", [])]
    return pick_faces(faces, select)


def pick_faces(faces, select):
    """select: None (all), int N (N-th largest, 1-based) or 'x,y,w,h' (explicit box)."""
    if select in (None, "", "auto"):
        return faces
    if isinstance(select, str) and "," in select:
        from .masks import Face
        box = [float(v) for v in select.split(",")]
        if len(box) != 4:
            raise DotPhotoError("BAD_FACE", f"--face expects x,y,w,h, got '{select}'", "", 2)
        return [Face(box=box, confidence=1.0, kind="manual")]
    try:
        n = int(select)
    except (TypeError, ValueError):
        raise DotPhotoError("BAD_FACE", f"--face expects N or x,y,w,h, got '{select}'", "", 2)
    if n < 1 or n > len(faces):
        raise DotPhotoError("BAD_FACE", f"--face {n} but {len(faces)} face(s) detected", "", 2)
    return [faces[n - 1]]


def _keep_previous(path: str) -> None:
    """A re-run keeps the last round's file as <name>.prev.<ext> so both rounds can be compared."""
    if os.path.isfile(path):
        base, ext = os.path.splitext(path)
        prev = base + ".prev" + ext
        try:
            os.replace(path, prev)
        except OSError:
            pass


def write_processed(ctx: Ctx, before, after, *, faces_json, focus=None, extra=None, label="AFTER"):
    from .compare import default_focus, make_compare, make_focus
    from .imageio import save_jpeg, save_tiff16
    ctx.ensure_out()
    for name in ("compare.jpg", "focus.jpg", "report.json"):
        _keep_previous(os.path.join(ctx.out_dir, name))
    arts = {}
    arts["processed"] = save_tiff16(after.rgb, os.path.join(ctx.out_dir, "processed.tif"))["path"]
    arts["processed_jpg"] = save_jpeg(after.rgb, os.path.join(ctx.out_dir, "processed.jpg"), quality=95,
                                      exif=after.exif, strip_gps=True)["path"]
    focus = focus or default_focus(before.rgb, faces_json)
    cmp_info = make_compare(before.rgb, after.rgb, os.path.join(ctx.out_dir, "compare.jpg"),
                            focus=focus, extra=extra, labels=("BEFORE", label))
    arts["compare"] = cmp_info["path"]
    arts["focus"] = make_focus(before.rgb, after.rgb, os.path.join(ctx.out_dir, "focus.jpg"), focus=focus,
                               labels=("BEFORE", label))["path"]
    ctx.timer.mark("write")
    ctx.log(f"wrote {arts['processed']}, compare.jpg (focus at {cmp_info['focus_zoom']:.0%}), focus.jpg (100%)")
    return arts, cmp_info


def finish(ctx: Ctx, action: str, *, artifacts: dict, summary: dict, extra: dict | None = None,
           write_report: bool = True):
    base, report = build(action, ctx.input, ctx.out_dir if write_report else None, artifacts=artifacts,
                         summary=summary, warnings=ctx.warnings, needs_review=ctx.reviews,
                         timing=ctx.timer.total(), extra=extra)
    if write_report:
        ctx.ensure_out()
        artifacts["report"] = write(report, ctx.out_dir)
        base["artifacts"] = artifacts
        ctx.log(f"{action} done in {base['timing_ms']['total']} ms; needs_review: "
                f"{[r['code'] for r in ctx.reviews] or 'none'}")
    return base


def write_json(ctx: Ctx, name: str, obj) -> str:
    ctx.ensure_out()
    path = os.path.join(ctx.out_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    return os.path.abspath(path)


# ---------------------------------------------------------------- commands

def cmd_selftest(args) -> dict:
    import numpy
    import PIL

    import cv2
    from .color import has_ximgproc
    from .imageio import HAS_HEIF
    from .masks import haar_available
    ok_ximg = has_ximgproc()
    ok_haar = haar_available()
    try:
        from PIL import ImageCms
        ImageCms.createProfile("sRGB")
        ok_cms = True
    except Exception:
        ok_cms = False
    presets = sorted(os.path.splitext(f)[0] for f in os.listdir(os.path.join(ASSETS, "presets", "styles")))
    problems = []
    if not ok_haar:
        problems.append("Haar cascades missing (opencv-contrib-python-headless)")
    if not ok_cms:
        problems.append("Pillow ImageCms unavailable")
    out = {
        "ok": not problems, "action": "selftest", "version": __version__,
        "python": sys.version.split()[0], "opencv": cv2.__version__, "numpy": numpy.__version__,
        "pillow": PIL.__version__, "ximgproc": ok_ximg, "haar": ok_haar, "heif": HAS_HEIF, "imagecms": ok_cms,
        "presets": presets, "assets": ASSETS, "problems": problems,
    }
    if not ok_ximg:
        out["warnings"] = ["cv2.ximgproc missing: guided filter falls back to numpy (slower)"]
    if problems:
        raise DotPhotoError("DEPENDENCY_MISSING", "; ".join(problems),
                            "re-run `uv run --script scripts/dphoto.py selftest` after `uv cache clean`", 4)
    return out


def cmd_info(args) -> dict:
    ctx = Ctx(args, args.image)
    ctx.quiet = True
    from .imageio import load
    img = load(ctx.input, max_px=ctx.max_analyze_px)
    an = analyze_image(ctx, img)
    src = img.source
    return {
        "ok": True, "action": "info", "version": __version__, "input": ctx.input,
        "size": src["original_size"], "format": src["format"], "orientation": src["orientation"],
        "source_profile": src["source_profile"], "bit_depth": src["bit_depth"],
        "faces": an["faces"], "skin_coverage": an["skin"]["coverage"], "sky_coverage": an["sky_coverage"],
        "suggested_type": an["type"], "warnings": src.get("warnings", []),
        "default_out_dir": ctx.out_dir,
    }


def cmd_analyze(args) -> dict:
    ctx = Ctx(args, args.image)
    img = load_full(ctx)
    an = analyze_image(ctx, img)
    path = write_json(ctx, "analysis.json", an)
    return finish(ctx, "analyze", artifacts={"analysis": path},
                  summary={"size": [img.width, img.height], "type": an["type"], "faces": an["faces"],
                           "skin_coverage": an["skin"]["coverage"], "luma_percentiles": an["luma_percentiles"]},
                  extra={"analysis": an})


def cmd_style_extract(args) -> dict:
    from . import style as S
    ctx = Ctx(args, args.image)
    img = load_full(ctx)
    an = analyze_image(ctx, img)
    name = args.name or os.path.splitext(os.path.basename(ctx.input))[0]
    st = S.extract(an, name=name, min_confidence=args.min_confidence, source_image=ctx.input)
    errors = S.validate(st)
    if errors:
        raise DotPhotoError("STYLE_INVALID", "extracted style failed validation: " + "; ".join(errors[:3]), "", 5)
    ctx.timer.mark("extract")
    if st["confidence"].get("overall", 0) < 0.5:
        ctx.add_review("STYLE_LOW_CONFIDENCE", f"overall {st['confidence']['overall']}")
    a_path = write_json(ctx, "analysis.json", an)
    s_path = S.save(st, os.path.join(ctx.out_dir, "style.json"))
    low = sorted(k for k, v in st["confidence"].items() if k != "overall" and v < args.min_confidence)
    return finish(ctx, "style.extract", artifacts={"style": s_path, "analysis": a_path},
                  summary={"size": [img.width, img.height], "type": an["type"], "name": name,
                           "tone": st["tone"], "color": st["color"], "effects": st["effects"],
                           "hsl": st["hsl"], "grade": st["grade"],
                           "confidence_overall": st["confidence"]["overall"], "low_confidence_fields": low},
                  extra={"style": st})


def cmd_style_apply(args) -> dict:
    from . import style as S
    ctx = Ctx(args, args.image)
    st = S.resolve(args.style)
    img = load_full(ctx)
    an = analyze_image(ctx, img)
    out, info = S.apply(img, st, strength=args.strength, mode=args.mode, target_analysis=an, seed=ctx.seed)
    ctx.timer.mark("style")
    used = dict(st)
    used["source"] = dict(st.get("source", {}), applied_strength=args.strength, applied_mode=args.mode,
                          applied_to=ctx.input)
    s_path = S.save(used, os.path.join(ctx.out_dir, "style.json"))
    a_path = write_json(ctx, "analysis.json", an)
    arts, cmp_info = write_processed(ctx, img, out, faces_json=an["faces"])
    arts.update({"style": s_path, "analysis": a_path})
    return finish(ctx, "style.apply", artifacts=arts,
                  summary={"size": [img.width, img.height], "type": an["type"], "style": st["name"],
                           "mode": info["mode"], "strength": info["strength"],
                           "matched_fields": info["matched_fields"], "params_used": info["params_used"],
                           "focus": cmp_info["focus"]},
                  extra={"style": used})


def _portrait_step(ctx: Ctx, img, an, args):
    from .portrait import retouch
    faces = faces_from_analysis(an, getattr(args, "face", None))
    if not faces:
        ctx.add_review("NO_FACE")
    elif len(faces) > 1 and getattr(args, "face", None) in (None, "", "auto"):
        ctx.add_review("MULTI_FACE", f"{len(faces)} faces")
    out, info = retouch(img, faces=faces, skin_strength=args.skin_strength, blemish=args.blemish == "on",
                        remove_moles=bool(args.remove_moles), eye_sharpen=args.eye_sharpen,
                        guided_radius=args.guided_radius, debug_dir=ctx.debug_dir())
    for code, detail in info.get("reviews", []):
        ctx.add_review(code, detail)
    for w in info.get("warnings", []):
        ctx.warn(w)
    ctx.timer.mark("portrait")
    return out, info, faces


def cmd_portrait(args) -> dict:
    from . import style as S
    ctx = Ctx(args, args.image)
    img = load_full(ctx)
    an = analyze_image(ctx, img)
    styled = img
    style_info = None
    if args.style and args.style != "none":
        st = S.resolve(args.style)
        styled, style_info = S.apply(img, st, strength=args.strength, mode="params", seed=ctx.seed)
        ctx.timer.mark("style")
    out, info, faces = _portrait_step(ctx, styled, an, args)
    faces_json = [f.to_json() for f in faces]
    arts, cmp_info = write_processed(ctx, img, out, faces_json=faces_json)
    arts["analysis"] = write_json(ctx, "analysis.json", an)
    summary = {"size": [img.width, img.height], "type": an["type"], "faces": faces_json,
               "skin_coverage": info["skin_coverage"],
               "params_used": dict(info["params_used"], style=(
                   {"name": args.style, "strength": args.strength, "mode": "params"} if style_info else None)),
               "metrics": info["metrics"], "focus": cmp_info["focus"], "focus_zoom": cmp_info["focus_zoom"],
               "style": args.style if style_info else None}
    return finish(ctx, "portrait", artifacts=arts, summary=summary, extra={"style_info": style_info, "analysis": an})


def _landscape_params(args) -> dict:
    return {"black": args.black, "white": args.white, "far_clarity": args.far_clarity,
            "near_texture": args.near_texture, "dehaze": args.dehaze, "clahe": args.clahe,
            "clahe_tile": args.clahe_tile, "orton": args.orton, "sky": args.sky == "on",
            "sky_darken": args.sky_darken}


def _landscape_step(ctx: Ctx, img, args):
    from .landscape import enhance
    out, info = enhance(img, params=_landscape_params(args), debug_dir=ctx.debug_dir())
    for code, detail in info.get("reviews", []):
        ctx.add_review(code, detail)
    ctx.timer.mark("landscape")
    return out, info


def cmd_landscape(args) -> dict:
    from . import style as S
    ctx = Ctx(args, args.image)
    img = load_full(ctx)
    an = analyze_image(ctx, img)
    styled = img
    style_info = None
    if args.style and args.style != "none":
        st = S.resolve(args.style)
        styled, style_info = S.apply(img, st, strength=args.strength, mode="params", seed=ctx.seed)
        ctx.timer.mark("style")
    out, info = _landscape_step(ctx, styled, args)
    arts, cmp_info = write_processed(ctx, img, out, faces_json=[], focus=info.get("focus"))
    arts["analysis"] = write_json(ctx, "analysis.json", an)
    summary = {"size": [img.width, img.height], "type": an["type"],
               "params_used": dict(info["params_used"], style=(
                   {"name": args.style, "strength": args.strength, "mode": "params"} if style_info else None)),
               "metrics": info["metrics"], "focus": cmp_info["focus"], "focus_zoom": cmp_info["focus_zoom"],
               "style": args.style if style_info else None}
    return finish(ctx, "landscape", artifacts=arts, summary=summary, extra={"style_info": style_info, "analysis": an})


def _export_step(ctx: Ctx, img, an, args, *, already_retouched: bool):
    from .export import export, load_presets
    presets = load_presets(getattr(args, "presets", None))
    targets = [t.strip() for t in (args.for_ or "print,web,dating").split(",") if t.strip()]
    faces = faces_from_analysis(an, getattr(args, "face", None))
    results, info = export(img, targets=targets, presets=presets, faces=faces, paper=args.paper,
                           finish=args.finish, fit=args.fit, out_dir=os.path.join(ctx.out_dir, "export"),
                           exif=img.exif, tiff16=bool(getattr(args, "tiff16", False)),
                           dating_retouch=(args.dating_retouch if args.dating_retouch != "auto" else
                                           ("off" if already_retouched else "on")) == "on",
                           seed=ctx.seed)
    for code, detail in info.get("reviews", []):
        ctx.add_review(code, detail)
    ctx.timer.mark("export")
    return results, info


def is_processed_input(path: str) -> bool:
    """processed.tif / processed.jpg written by an earlier action (already retouched)."""
    base = os.path.basename(path).lower()
    return base.startswith("processed.") or ".dot-photo" in path


def cmd_export(args) -> dict:
    ctx = Ctx(args, args.image)
    img = load_full(ctx)
    an = analyze_image(ctx, img)
    results, info = _export_step(ctx, img, an, args, already_retouched=is_processed_input(ctx.input))
    exports = {r["target"]: r["path"] for r in results}
    extra = [{"label": r["target"], "rgb": r["preview"], "rects": r.get("rects", [])} for r in results if "preview" in r]
    from .compare import make_compare
    ctx.ensure_out()
    cmp_info = make_compare(img.rgb, img.rgb, os.path.join(ctx.out_dir, "compare.jpg"), faces=an["faces"],
                            extra=extra, labels=("SOURCE", "SOURCE"))
    arts = {"exports": exports, "compare": cmp_info["path"]}
    summary = {"size": [img.width, img.height], "type": an["type"], "faces": an["faces"],
               "targets": info["targets"], "params_used": info["params_used"],
               "exports": [{k: v for k, v in r.items() if k not in ("preview", "rects")} for r in results]}
    return finish(ctx, "export", artifacts=arts, summary=summary)


def cmd_run(args) -> dict:
    from . import style as S
    ctx = Ctx(args, args.image)
    img = load_full(ctx)
    an = analyze_image(ctx, img)
    ptype = args.type if args.type != "auto" else an["type"]["value"]
    if args.type == "auto" and an["type"]["confidence"] < 0.75:
        ctx.add_review("TYPE_UNCERTAIN", f"{an['type']['value']} {an['type']['confidence']}")
    if ptype == "unknown":
        ptype = "generic"
    style_name = args.style or {"portrait": "clean-portrait", "landscape": "neutral"}.get(ptype, "neutral")
    st = S.resolve(style_name) if style_name != "none" else None
    cur = img
    style_info = None
    if st is not None:
        mode = args.mode if st.get("stats") else "params"
        cur, style_info = S.apply(img, st, strength=args.strength, mode=mode, target_analysis=an, seed=ctx.seed)
        ctx.timer.mark("style")
    type_info = None
    faces_json = an["faces"]
    focus = None
    if ptype == "portrait":
        cur, type_info, faces = _portrait_step(ctx, cur, an, args)
        faces_json = [f.to_json() for f in faces]
    elif ptype == "landscape":
        cur, type_info = _landscape_step(ctx, cur, args)
        focus = type_info.get("focus")
    results, exp_info = _export_step(ctx, cur, an, args, already_retouched=(ptype == "portrait"))
    exports = {r["target"]: r["path"] for r in results}
    extra = [{"label": r["target"], "rgb": r["preview"], "rects": r.get("rects", [])} for r in results if "preview" in r]
    arts, cmp_info = write_processed(ctx, img, cur, faces_json=faces_json, focus=focus, extra=extra)
    arts["exports"] = exports
    arts["analysis"] = write_json(ctx, "analysis.json", an)
    if st is not None:
        used = dict(st)
        used["source"] = dict(st.get("source", {}), applied_strength=args.strength, applied_to=ctx.input)
        arts["style"] = S.save(used, os.path.join(ctx.out_dir, "style.json"))
    params_used = {
        "style": ({"name": style_name, "strength": args.strength, "mode": style_info["mode"],
                   "matched_fields": style_info["matched_fields"]} if style_info else None),
        ptype: type_info["params_used"] if type_info else None,
        "export": exp_info["params_used"],
    }
    summary = {"size": [img.width, img.height], "source_profile": img.source["source_profile"],
               "orientation_applied": img.source["orientation"], "type": dict(an["type"], used=ptype),
               "faces": faces_json, "skin_coverage": an["skin"]["coverage"], "style": style_name,
               "params_used": params_used,
               "style_params": style_info["params_used"] if style_info else None,
               "type_params": type_info["params_used"] if type_info else None,
               "metrics": type_info["metrics"] if type_info else {},
               "exports": [{k: v for k, v in r.items() if k not in ("preview", "rects")} for r in results],
               "focus": cmp_info["focus"], "focus_zoom": cmp_info["focus_zoom"]}
    return finish(ctx, "run", artifacts=arts, summary=summary,
                  extra={"analysis": an, "style": st, "style_info": style_info, "type_info": type_info})


def cmd_compare(args) -> dict:
    from .compare import make_compare
    from .imageio import load
    a = load(args.before)
    b = load(args.after)
    if a.rgb.shape != b.rgb.shape:
        raise DotPhotoError("SIZE_MISMATCH", "before and after differ in size", "", 2)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.after)), "compare.jpg")
    focus = None
    if args.focus and "," in args.focus:
        focus = [float(v) for v in args.focus.split(",")]
    faces = None
    if args.focus in ("face", "auto", None):
        from .masks import detect_faces
        from .imageio import downscale
        small, s = downscale(a, 4_000_000)
        faces = [f.scaled(1 / s).to_json() for f in detect_faces(small.rgb)]
    info = make_compare(a.rgb, b.rgb, out, focus=focus, faces=faces)
    return {"ok": True, "action": "compare", "version": __version__, "artifacts": {"compare": info["path"]},
            "summary": {"focus": info["focus"]}}


# ---------------------------------------------------------------- parser

def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--out", help="output directory (default <photo dir>/<stem>.dot-photo/)")
    p.add_argument("--max-analyze-px", type=int, default=4_000_000)
    p.add_argument("--max-process-px", type=int, default=0, help="0 = full size (auto-limited by memory)")
    p.add_argument("--debug", action="store_true", help="write masks/ and extra previews")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--quiet", action="store_true")
    return p


def _add_portrait_args(p, *, with_style=True):
    if with_style:
        p.add_argument("--style", default="clean-portrait", help="style file or preset; 'none' to skip")
        p.add_argument("--strength", type=float, default=1.0)
    p.add_argument("--skin-strength", type=float, default=0.55)
    p.add_argument("--blemish", choices=["on", "off"], default="on")
    p.add_argument("--remove-moles", action="store_true")
    p.add_argument("--eye-sharpen", type=float, default=0.3)
    p.add_argument("--face", default=None, help="N (N-th largest) or x,y,w,h")
    p.add_argument("--guided-radius", default="auto")


def _add_landscape_args(p, *, with_style=True):
    if with_style:
        p.add_argument("--style", default="neutral", help="style file or preset; 'none' to skip")
        p.add_argument("--strength", type=float, default=1.0)
    p.add_argument("--black", type=float, default=0.5, help="black point percentile")
    p.add_argument("--white", type=float, default=99.5, help="white point percentile")
    p.add_argument("--far-clarity", type=float, default=-15)
    p.add_argument("--near-texture", type=float, default=20)
    p.add_argument("--dehaze", type=float, default=0.15, help="0..1")
    p.add_argument("--clahe", type=float, default=2.5, help="clip limit, 0 = off")
    p.add_argument("--clahe-tile", type=int, default=8)
    p.add_argument("--orton", type=float, default=0.0, help="0..0.15")
    p.add_argument("--sky", choices=["on", "off"], default="on")
    p.add_argument("--sky-darken", type=float, default=0.15)


def _add_export_args(p):
    p.add_argument("--for", dest="for_", default="print,web,dating", help="comma list: print,web,dating")
    p.add_argument("--paper", default="4x6")
    p.add_argument("--finish", choices=["matte", "glossy"], default="matte")
    p.add_argument("--fit", choices=["crop", "pad"], default="crop")
    p.add_argument("--presets", default=None, help="alternative export.json")
    p.add_argument("--tiff16", action="store_true", help="also write 16-bit TIFF for print")
    p.add_argument("--dating-retouch", choices=["auto", "on", "off"], default="auto")


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    p = argparse.ArgumentParser(prog="dphoto", description="dot-photo image processing")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", parents=[common]).set_defaults(func=cmd_selftest)
    s = sub.add_parser("info", parents=[common]); s.add_argument("image"); s.set_defaults(func=cmd_info)
    s = sub.add_parser("analyze", parents=[common]); s.add_argument("image"); s.set_defaults(func=cmd_analyze)

    st = sub.add_parser("style")
    st_sub = st.add_subparsers(dest="style_cmd", required=True)
    e = st_sub.add_parser("extract", parents=[common])
    e.add_argument("image"); e.add_argument("--name", default=None)
    e.add_argument("--min-confidence", type=float, default=0.35)
    e.set_defaults(func=cmd_style_extract)
    a = st_sub.add_parser("apply", parents=[common])
    a.add_argument("image"); a.add_argument("--style", required=True)
    a.add_argument("--strength", type=float, default=1.0)
    a.add_argument("--mode", choices=["hybrid", "params", "match"], default="hybrid")
    a.set_defaults(func=cmd_style_apply)

    s = sub.add_parser("portrait", parents=[common]); s.add_argument("image")
    _add_portrait_args(s); s.set_defaults(func=cmd_portrait)
    s = sub.add_parser("landscape", parents=[common]); s.add_argument("image")
    _add_landscape_args(s); s.set_defaults(func=cmd_landscape)
    s = sub.add_parser("export", parents=[common]); s.add_argument("image")
    _add_export_args(s); s.add_argument("--face", default=None); s.set_defaults(func=cmd_export)

    r = sub.add_parser("run", parents=[common]); r.add_argument("image")
    r.add_argument("--type", choices=["auto", "portrait", "landscape", "generic"], default="auto")
    r.add_argument("--style", default=None, help="style file or preset (default by type); 'none' to skip")
    r.add_argument("--strength", type=float, default=1.0)
    r.add_argument("--mode", choices=["hybrid", "params", "match"], default="hybrid")
    _add_portrait_args(r, with_style=False); _add_landscape_args(r, with_style=False); _add_export_args(r)
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("compare", parents=[common])
    c.add_argument("before"); c.add_argument("after"); c.add_argument("--focus", default="auto")
    c.set_defaults(func=cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        code = int(e.code) if isinstance(e.code, int) else 0
        if code != 0:
            print(json.dumps({"ok": False, "action": "parse", "error": {"code": "BAD_ARGS", "message": "invalid arguments", "hint": "run with --help"}}))
            return 2
        return 0
    action = args.cmd if args.cmd != "style" else f"style.{args.style_cmd}"
    try:
        out = args.func(args)
        print(json.dumps(out, ensure_ascii=False, default=str))
        return 0
    except DotPhotoError as e:
        print(json.dumps({"ok": False, "action": action, "error": e.to_json()}, ensure_ascii=False))
        return e.exit_code
    except Exception as e:  # pragma: no cover - unexpected
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"ok": False, "action": action, "error": {"code": "INTERNAL", "message": f"{type(e).__name__}: {e}", "hint": "see stderr"}}, ensure_ascii=False))
        return 5
