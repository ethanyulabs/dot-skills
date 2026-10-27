"""Folder input: run one command over every photo under a directory.

Each photo goes to <output root>/<stem>-<hash8>/ (the home's output/, or --out DIR); batch.json, log.txt and
contact*.jpg (a before | after row per photo, pixel-writing actions only) go to the run directory:
--out DIR itself, or <home>/runs/<stamp>-<folder>/ (a fresh one per run).
"""
from __future__ import annotations

import copy
import gc
import glob
import json
import os
import shutil
import tempfile
import traceback
from collections import Counter

from PIL import Image, ImageDraw

from . import DotPhotoError, __version__
from .cli import Ctx, _keep_previous
from .report import _default

ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".hif"}
PIXEL_ACTIONS = {"run", "portrait", "landscape", "style.apply", "export"}
ROWS_PER_PAGE = 12
ROW_H, HEADER_H, GAP, SHEET_W = 220, 44, 8, 1800
THUMB_PX = 400_000

YELLOW, RED, GRAY, WHITE = (255, 220, 0), (255, 80, 80), (150, 150, 150), (255, 255, 255)


# ---------------------------------------------------------------- scan

def _skip_dir(name: str, full: str, exclude: set[str]) -> bool:
    return name.startswith(".") or name == "dot-photo" or name.endswith(".dot-photo") or full in exclude


def _is_photo(name: str) -> bool:
    low = name.lower()
    return (not name.startswith(".") and not low.startswith("processed.")
            and os.path.splitext(low)[1] in ALLOWED_SUFFIXES)


def scan(root: str, *, recursive: bool = True, exclude_dirs=()) -> list[str]:
    """Sorted absolute paths of every photo under root. Hidden entries, dot-photo output dirs and
    processed.* files are skipped."""
    root = os.path.abspath(root)
    exclude = {os.path.abspath(d) for d in exclude_dirs}
    found = []
    for dp, dirnames, filenames in os.walk(root):
        if recursive:
            dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d, os.path.join(dp, d), exclude))
        else:
            dirnames[:] = []
        found.extend(os.path.join(dp, f) for f in filenames if _is_photo(f))
    return sorted(found)


def plan_out_dirs(files: list[str], out_root: str) -> tuple[dict[str, str], dict[str, dict]]:
    """<out_root>/<stem>-<hash8>/ per photo (same content, same directory). Files that cannot be hashed
    are returned separately as {path: error} and skipped by the loop."""
    from .imageio import content_sha1
    plan, failed = {}, {}
    for p in files:
        stem = os.path.splitext(os.path.basename(p))[0]
        try:
            plan[p] = os.path.join(out_root, f"{stem}-{content_sha1(p)[:8]}")
        except DotPhotoError as e:
            failed[p] = e.to_json()
        except OSError as e:
            failed[p] = {"code": "HASH_FAILED", "message": f"cannot read {p}: {e}", "hint": ""}
    return plan, failed


# ---------------------------------------------------------------- loop

def _photo_record(path: str, rel: str, out_dir: str, res: dict | None, status: str) -> dict:
    rec = {"input": path, "rel": rel, "out_dir": out_dir, "status": status, "type": None,
           "needs_review": [], "error": None}
    if res is None:
        return rec
    summary = res.get("summary") or {}
    rec["type"] = summary.get("type") or res.get("suggested_type")
    rec["needs_review"] = [r["code"] for r in res.get("needs_review", [])]
    rec["error"] = res.get("error")
    return rec


def _progress(i: int, n: int, rec: dict) -> str:
    head = f"[{i}/{n}] {rec['rel']} "
    if rec["status"] == "skipped":
        return head + "skipped (report.json exists)"
    if rec["status"] == "failed":
        return head + f"FAILED {rec['error']['code']}: {rec['error'].get('message', '')}"
    t = rec["type"] or {}
    label = t.get("used") or t.get("value")
    parts = [f"ok ({label})" if label else "ok"]
    if rec["needs_review"]:
        parts.append("review: " + ",".join(rec["needs_review"]))
    return head + " ".join(parts)


def run_batch(args, action: str) -> dict:
    from .home import new_run_dir, output_root, photo_home
    root = os.path.abspath(args.image)
    if getattr(args, "out", None):
        batch_root = out_root = os.path.abspath(args.out)
    else:
        batch_root, out_root = None, output_root()
    files = scan(root, recursive=getattr(args, "recursive", True),
                 exclude_dirs={d for d in (batch_root, photo_home()) if d})
    if not files:
        raise DotPhotoError("NO_PHOTOS", f"no photos under {root}",
                            "allowed: jpg jpeg png tif tiff heic heif hif; hidden entries, dot-photo "
                            "directories, the dot-photo home and processed.* files are skipped", 2)
    if batch_root is None:
        batch_root = new_run_dir(root)
    bargs = copy.copy(args)
    bargs.out = batch_root
    bctx = Ctx(bargs, None)
    bctx.ensure_out()
    for name in ["batch.json", "contact.jpg"] + [os.path.basename(p) for p in glob.glob(os.path.join(batch_root, "contact-*.jpg"))]:
        _keep_previous(os.path.join(batch_root, name))
    plan, unhashable = plan_out_dirs(files, out_root)
    n = len(files)
    bctx.log(f"batch {action}: {n} photo(s) under {root} -> {out_root} (run files in {batch_root})")

    records, full = [], []
    for i, path in enumerate(files, 1):
        rel = os.path.relpath(path, root)
        if path in unhashable:
            res = {"ok": False, "action": action, "input": path, "error": unhashable[path]}
            rec = _photo_record(path, rel, None, res, "failed")
            records.append(rec)
            full.append({"input": path, "rel": rel, "out_dir": None, "status": "failed", "result": res})
            bctx.log(_progress(i, n, rec))
            continue
        out_dir = plan[path]
        if getattr(args, "skip_existing", False) and os.path.isfile(os.path.join(out_dir, "report.json")):
            rec = _photo_record(path, rel, out_dir, None, "skipped")
            records.append(rec)
            full.append({"input": path, "rel": rel, "out_dir": out_dir, "status": "skipped", "result": None})
            bctx.log(_progress(i, n, rec))
            continue
        sub = copy.copy(args)
        sub.image, sub.out, sub.quiet = path, out_dir, True
        try:
            res = args.func(sub)
        except DotPhotoError as e:
            res = {"ok": False, "action": action, "input": path, "error": e.to_json()}
        except Exception as e:  # keep going; the traceback lands in the batch log
            bctx.log(traceback.format_exc())
            res = {"ok": False, "action": action, "input": path,
                   "error": {"code": "INTERNAL", "message": f"{type(e).__name__}: {e}", "hint": "see log.txt"}}
        status = "ok" if res.get("ok") else "failed"
        rec = _photo_record(path, rel, out_dir, res, status)
        records.append(rec)
        full.append({"input": path, "rel": rel, "out_dir": out_dir, "status": status, "result": res})
        bctx.log(_progress(i, n, rec))
        gc.collect()
    bctx.timer.mark("process")

    contact: list[str] = []
    if action in PIXEL_ACTIONS:
        workdir = tempfile.mkdtemp(prefix="dot-photo-batch-")
        try:
            contact = make_contact_sheet(records, batch_root, workdir=workdir, warn=bctx.warn)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        bctx.timer.mark("contact")

    counts = Counter(code for r in records for code in r["needs_review"])
    n_ok = sum(r["status"] == "ok" for r in records)
    n_failed = sum(r["status"] == "failed" for r in records)
    n_skipped = sum(r["status"] == "skipped" for r in records)
    ok = n_failed < n  # only a batch in which every photo failed is a failure
    base = {
        "ok": ok, "action": action, "version": __version__, "batch": True, "input": root, "out_dir": batch_root,
        "output_root": out_root, "config_applied": bctx.config_applied,
        "artifacts": {"contact": contact, "batch": os.path.join(batch_root, "batch.json"), "log": bctx.log_path},
        "summary": {"total": n, "ok": n_ok, "failed": n_failed, "skipped": n_skipped,
                    "needs_review_counts": dict(sorted(counts.items())), "photos": records},
        "warnings": bctx.warnings, "needs_review": [], "timing_ms": bctx.timer.total(),
    }
    if not ok:
        base["error"] = {"code": "ALL_FAILED", "message": f"{n_failed} photo(s) failed, none succeeded",
                         "hint": "see batch.json and log.txt"}
    report = dict(base)
    report["summary"] = dict(base["summary"], photos=full)
    with open(base["artifacts"]["batch"], "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, default=_default)
    bctx.log(f"batch done: {n_ok} ok, {n_failed} failed, {n_skipped} skipped in {base['timing_ms']['total']} ms")
    return base


# ---------------------------------------------------------------- contact sheet

def _after_path(out_dir: str) -> str | None:
    for cand in (os.path.join(out_dir, "processed.jpg"), os.path.join(out_dir, "export", "web.jpg")):
        if os.path.isfile(cand):
            return cand
    return None


def _thumb(path: str, workdir: str):
    from .compare import _fit
    from .imageio import load, to_uint8
    img = load(path, max_px=THUMB_PX, workdir=workdir)
    half = (SHEET_W - GAP) // 2
    return Image.fromarray(to_uint8(_fit(img.rgb, half, ROW_H)))


def _row_title(rec: dict) -> list[tuple[str, tuple]]:
    parts = [(rec["rel"], WHITE)]
    if rec["status"] == "failed":
        parts.append((f"FAILED {rec['error']['code']}", RED))
        return parts
    if rec["status"] == "skipped":
        parts.append(("skipped", GRAY))
    t = rec.get("type") or {}
    if t:
        label = t.get("used") or t.get("value", "")
        conf = t.get("confidence")
        parts.append((f"{label} ({conf:.2f})" if conf is not None else label, WHITE))
    if rec["needs_review"]:
        parts.append((", ".join(rec["needs_review"]), YELLOW))
    return parts


def make_contact_sheet(records: list[dict], batch_root: str, *, workdir: str, warn=None) -> list[str]:
    """contact.jpg, contact-2.jpg, ...: one row per photo, before | after, ROWS_PER_PAGE rows per page."""
    from .compare import _font, _label
    font = _font(16)
    paths = []
    pages = [records[i:i + ROWS_PER_PAGE] for i in range(0, len(records), ROWS_PER_PAGE)]
    row_h = HEADER_H + ROW_H + GAP
    half = (SHEET_W - GAP) // 2
    for page_no, rows in enumerate(pages, 1):
        canvas = Image.new("RGB", (SHEET_W, row_h * len(rows)), (24, 24, 24))
        d = ImageDraw.Draw(canvas)
        for r, rec in enumerate(rows):
            y = r * row_h
            x = 6
            for text, color in _row_title(rec):
                d.text((x, y + 12), text, fill=color, font=font)
                x += d.textlength(text, font=font) + 18
            y += HEADER_H
            before = after = None
            if rec["status"] != "failed":
                try:
                    before = _thumb(rec["input"], workdir)
                    ap = _after_path(rec["out_dir"]) if rec["out_dir"] else None
                    after = _thumb(ap, workdir) if ap else before.copy()
                    _label(before, "BEFORE", 14)
                    _label(after, "AFTER" if ap else "AFTER (no output)", 14)
                except Exception as e:
                    if warn:
                        warn(f"contact sheet: {rec['rel']}: {type(e).__name__}: {e}")
                    before = after = None
            x0 = 0
            for im in (before, after):
                if im is None:
                    d.rectangle([x0, y, x0 + half, y + ROW_H], fill=(48, 48, 48))
                    x0 += half + GAP
                else:
                    canvas.paste(im, (x0, y))
                    x0 += im.width + GAP
        name = "contact.jpg" if page_no == 1 else f"contact-{page_no}.jpg"
        path = os.path.join(batch_root, name)
        canvas.save(path, "JPEG", quality=85)
        paths.append(os.path.abspath(path))
    return paths
