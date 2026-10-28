"""Style files: validation, extraction from an analysis, and application to an image.

A style is a plain dict in the shape of assets/schema/style.schema.json. Parameters use the
Lightroom JPEG scale (-100..100, exposure in EV). extract() maps analysis statistics to
parameters relative to a neutral reference (constants in assets/presets/analysis-priors.json);
apply() runs the fixed pipeline WB -> exposure -> blacks/whites -> contrast -> highlights/shadows
-> curve -> HSL -> grade -> effects.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import os

import numpy as np

from . import DotPhotoError, __version__
from . import masks as M
from .analyze import HSL_BINS, hue_soft_weight
from .color import (apply_lut_luma, blacks_whites_lut, build_curve_lut, compose_luts, f32, gaussian,
                    guided_filter, identity_lut, lab_to_rgb, linear_to_srgb, lookup, luma, rgb_to_hsv,
                    hsv_to_rgb, rgb_to_lab, s_curve_lut, srgb_to_linear, temperature_tint_gains)
from .imageio import WorkImage

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS = os.path.join(SKILL_DIR, "assets")
STYLES_DIR = os.path.join(ASSETS, "presets", "styles")
SCHEMA_PATH = os.path.join(ASSETS, "schema", "style.schema.json")
PRIORS_PATH = os.path.join(ASSETS, "presets", "analysis-priors.json")
SCHEMA_ID = "dot-photo/style/1"

TONE_KEYS = ["exposure", "contrast", "highlights", "shadows", "whites", "blacks"]
COLOR_KEYS = ["temperature", "tint", "vibrance", "saturation"]
EFFECT_KEYS = ["clarity", "texture", "dehaze", "vignette", "grain"]
MATCH_FIELDS = ["tone.exposure", "tone.contrast", "tone.blacks", "tone.whites", "color.temperature", "color.tint"]


# ---------------------------------------------------------------- io / schema

def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_priors(path: str | None = None) -> dict:
    return load_json(path or PRIORS_PATH)


def empty_style(name: str = "untitled") -> dict:
    return {
        "schema": SCHEMA_ID, "name": name, "source": {},
        "tone": {k: 0 for k in TONE_KEYS},
        "color": {k: 0 for k in COLOR_KEYS},
        "curve": {"rgb": None, "r": None, "g": None, "b": None},
        "hsl": {}, "grade": {},
        "effects": {k: 0 for k in EFFECT_KEYS},
        "stats": None, "confidence": {}, "notes": [],
    }


def _resolve_ref(schema_root: dict, node: dict) -> dict:
    if "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/")
        cur = schema_root
        for part in ref[2:].split("/"):
            cur = cur[part]
        return cur
    return node


def _type_ok(value, typ) -> bool:
    types = typ if isinstance(typ, list) else [typ]
    for t in types:
        if t == "object" and isinstance(value, dict):
            return True
        if t == "array" and isinstance(value, list):
            return True
        if t == "string" and isinstance(value, str):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "boolean" and isinstance(value, bool):
            return True
        if t == "null" and value is None:
            return True
    return False


def _validate(root: dict, node: dict, value, path: str, errors: list[str]) -> None:
    node = _resolve_ref(root, node)
    if "type" in node and not _type_ok(value, node["type"]):
        errors.append(f"{path}: expected {node['type']}, got {type(value).__name__}")
        return
    if "enum" in node and value not in node["enum"]:
        errors.append(f"{path}: must be one of {node['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{path}: {value} < minimum {node['minimum']}")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{path}: {value} > maximum {node['maximum']}")
    if isinstance(value, dict):
        props = node.get("properties", {})
        for req in node.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required '{req}'")
        for k, v in value.items():
            if k in props:
                _validate(root, props[k], v, f"{path}.{k}", errors)
            elif node.get("additionalProperties", True) is False:
                errors.append(f"{path}: unknown key '{k}'")
    if isinstance(value, list) and "items" in node:
        for i, v in enumerate(value):
            _validate(root, node["items"], v, f"{path}[{i}]", errors)


def validate(style: dict, schema_path: str = SCHEMA_PATH) -> list[str]:
    schema = load_json(schema_path)
    errors: list[str] = []
    _validate(schema, schema, style, "style", errors)
    return errors


def builtin_names() -> list[str]:
    return sorted(os.path.splitext(f)[0] for f in os.listdir(STYLES_DIR) if f.endswith(".json"))


def user_style_names() -> list[str]:
    from .home import styles_dir
    d = styles_dir()
    if not os.path.isdir(d):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d) if f.endswith(".json") and not f.startswith("."))


def is_reserved_name(name: str) -> bool:
    """Built-in preset names and 'none' (the 'skip the style' sentinel) cannot be user style names."""
    low = name.lower()
    return low == "none" or low in {n.lower() for n in builtin_names()}


def name_problem(name: str) -> str | None:
    if not name or not name.strip():
        return "empty name"
    if "/" in name or "\\" in name or os.sep in name:
        return "a style name cannot contain path separators"
    if name.startswith("."):
        return "a style name cannot start with '.'"
    return None


def resolve(name_or_path: str) -> dict:
    """A path to a style.json, the name of a built-in preset, or the name of a user style in
    the home's styles/ directory, in that order."""
    from .home import styles_dir
    if os.path.isfile(name_or_path):
        style, origin = load_json(name_or_path), "file"
    else:
        builtin = os.path.join(STYLES_DIR, f"{name_or_path}.json")
        user = os.path.join(styles_dir(), f"{name_or_path}.json")
        if os.path.isfile(builtin):
            style, origin = load_json(builtin), "builtin"
        elif os.path.isfile(user):
            try:
                style, origin = load_json(user), "user"
            except ValueError as e:
                raise DotPhotoError("STYLE_INVALID", f"user style '{name_or_path}' is not valid JSON: {e}",
                                    f"fix or delete {user}", 2)
        else:
            users = user_style_names()
            raise DotPhotoError("STYLE_NOT_FOUND", f"no style file or preset named '{name_or_path}'",
                                f"built-in: {', '.join(builtin_names())}; user ({styles_dir()}): "
                                f"{', '.join(users) if users else 'none'}; run `dphoto style list` to see all", 2)
    errors = validate(style)
    if errors:
        raise DotPhotoError("STYLE_INVALID", f"style '{name_or_path}' fails validation: " + "; ".join(errors[:5]),
                            "see references/style-schema.md", 2)
    base = empty_style(style.get("name", "untitled"))
    merged = _deep_merge(base, style)
    merged["source"]["resolved_from"] = origin
    return merged


def list_styles() -> dict:
    """Every built-in preset and every user style, with validity for the user ones."""
    from .home import styles_dir
    builtin = []
    for n in builtin_names():
        path = os.path.join(STYLES_DIR, f"{n}.json")
        st = load_json(path)
        builtin.append({"name": n, "path": path, "description": st.get("description", "")})
    user = []
    for n in user_style_names():
        path = os.path.join(styles_dir(), f"{n}.json")
        entry = {"name": n, "path": path, "description": "", "source_image": None, "valid": True}
        try:
            st = load_json(path)
            errors = validate(st)
            entry["description"] = st.get("description", "")
            entry["source_image"] = (st.get("source") or {}).get("image")
            if errors:
                entry.update(valid=False, error="; ".join(errors[:3]))
        except (OSError, ValueError) as e:
            entry.update(valid=False, error=f"not valid JSON: {e}")
        user.append(entry)
    return {"styles_dir": styles_dir(), "builtin": builtin, "user": user}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def save(style: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(style, fh, ensure_ascii=False, indent=2)
    return os.path.abspath(path)


def clamp(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return float(max(lo, min(hi, v)))


def _r(v: float, nd: int = 1) -> float:
    return round(float(v), nd)


# ---------------------------------------------------------------- extraction

def params_from_stats(st: dict, priors: dict, *, portrait: bool = False) -> tuple[dict, dict]:
    """Map analysis statistics to style parameters (relative to a neutral image) with confidences.
    Returns (params, confidence) where params has tone/color/hsl/grade/effects."""
    P = priors
    pct = st["luma_percentiles"]
    p1, p5, p10, p25, p50 = pct["p1"], pct["p5"], pct["p10"], pct["p25"], pct["p50"]
    p75, p90, p95, p99 = pct["p75"], pct["p90"], pct["p95"], pct["p99"]
    conf: dict = {}
    params = {"tone": {}, "color": {}, "hsl": {}, "grade": {}, "effects": {}}

    target = P["target_median_portrait"] if portrait else P["target_median"]
    lin_t = float(srgb_to_linear(np.array([target], np.float32))[0])
    lin_m = float(srgb_to_linear(np.array([max(p50, 1e-3)], np.float32))[0])
    params["tone"]["exposure"] = _r(clamp(math.log2(lin_t / max(lin_m, 1e-4)), -2, 2), 2)
    conf["tone.exposure"] = 0.4 if (p95 - p5) > 0.85 else 0.7

    params["tone"]["blacks"] = _r(clamp((p1 - P["black_point"]) * 600))
    conf["tone.blacks"] = 0.7
    params["tone"]["whites"] = _r(clamp((p99 - P["white_point"]) * 600))
    conf["tone.whites"] = 0.3 if p99 >= 0.995 else 0.6

    c1 = ((p95 - p5) - P["contrast_span_ref"]) / P["contrast_span_scale"] * 50
    c2 = ((p75 - p25) - P["iqr_ref"]) / P["iqr_scale"] * 25
    params["tone"]["contrast"] = _r(clamp((c1 + c2) / 2))
    conf["tone.contrast"] = 0.6

    r_s = (p10 - p1) / max(p50 - p1, 1e-3)
    params["tone"]["shadows"] = _r(clamp((r_s - P["shadow_ratio_ref"]) * 300))
    conf["tone.shadows"] = 0.4
    r_h = (p99 - p90) / max(p99 - p50, 1e-3)
    params["tone"]["highlights"] = _r(clamp(-(P["highlight_ratio_ref"] - r_h) * 300))
    conf["tone.highlights"] = 0.4

    neu = st["neutral_lab_mean"]
    cov = neu.get("coverage", 0.0)
    temp = neu["b"] * P["neutral_ab_scale"]
    tint = neu["a"] * P["neutral_ab_scale"]
    wb_conf = 0.8 * min(1.0, cov / 0.05) if not neu.get("fallback") else 0.3
    skin = st.get("skin", {})
    if portrait and skin.get("present") and skin.get("lab_mean"):  # skin WB only with a detected face
        sk_cov = min(1.0, skin["coverage"] / 0.05)
        skin_temp = (skin["lab_mean"][2] - P["skin_b_prior"]) * P["neutral_ab_scale"]
        skin_tint = (skin["lab_mean"][1] - P["skin_a_prior"]) * P["neutral_ab_scale"]
        w = sk_cov * 0.5
        temp = temp * (1 - w) + skin_temp * w
        tint = tint * (1 - w) + skin_tint * w
        wb_conf = max(wb_conf, 0.6 * sk_cov)
    params["color"]["temperature"] = _r(clamp(temp))
    params["color"]["tint"] = _r(clamp(tint))
    conf["color.temperature"] = round(wb_conf, 2)
    conf["color.tint"] = round(wb_conf, 2)

    params["color"]["saturation"] = _r(clamp((st["chroma_mean"] - P["chroma_ref"]) / P["chroma_ref"] * 50))
    conf["color.saturation"] = 0.6
    ratio = st["chroma_median"] / max(st["chroma_mean"], 1e-3)
    vib = (ratio - P["vibrance_ratio_ref"]) * 250
    if params["color"]["saturation"] < 0 and vib < 0:
        vib = 0.0
    params["color"]["vibrance"] = _r(clamp(vib))
    conf["color.vibrance"] = 0.3

    for name, hist in st["hsl_hist"].items():
        if hist["frac"] < P["hsl_min_fraction"]:
            continue
        prior = P["hsl_prior"][name]
        band = {
            "sat": _r(clamp((hist["s"] - prior["s"]) / prior["s"] * 100 * 0.6)),
            "lum": _r(clamp((hist["v"] - prior["v"]) * 200)),
            "hue": 0.0,
        }
        if name in P["hsl_hue_trusted"]:
            from .analyze import HSL_CENTERS
            d = (hist["h"] - HSL_CENTERS[name] + 180.0) % 360.0 - 180.0
            band["hue"] = _r(clamp(d, -30, 30))
        params["hsl"][name] = band
        conf[f"hsl.{name}"] = round(min(1.0, hist["frac"] / 0.05) * 0.7, 2)

    for zone, z in st["grade_lab"].items():
        chroma = math.hypot(z["a"], z["b"])
        if chroma < P["grade_min_chroma"]:
            params["grade"][zone] = {"hue": 0.0, "sat": 0.0}
        else:
            hue = math.degrees(math.atan2(z["b"], z["a"])) % 360.0
            params["grade"][zone] = {"hue": _r(hue), "sat": _r(min(100.0, chroma * P["grade_chroma_scale"]))}
        conf[f"grade.{zone}"] = 0.5 if z["frac"] >= 0.05 else 0.2
    params["grade"]["balance"] = 0.0

    params["effects"]["clarity"] = _r(clamp((st["local_contrast"] - P["local_contrast_ref"]) / P["local_contrast_ref"] * 50))
    conf["effects.clarity"] = 0.5
    params["effects"]["texture"] = _r(clamp((st["texture_energy"] - P["texture_ref"]) / P["texture_ref"] * 40))
    conf["effects.texture"] = 0.2 if st["noise_sigma"] > P["noise_texture_untrusted"] else 0.4
    dark = st["haze"]["dark_channel_mean"]
    params["effects"]["dehaze"] = _r(clamp(max(0.0, (P["dark_channel_ref"] - dark) * 200)))
    conf["effects.dehaze"] = 0.2
    params["effects"]["vignette"] = _r(clamp((st["vignette_ratio"] - 1.0) * 150))
    conf["effects.vignette"] = 0.6
    params["effects"]["grain"] = _r(clamp((st["noise_sigma"] - P["noise_floor"]) / P["noise_scale"] * 100, 0, 100))
    conf["effects.grain"] = 0.5
    return params, conf


def extract(analysis: dict, *, name: str, priors: dict | None = None, min_confidence: float = 0.35,
            portrait: bool | None = None, source_image: str = "") -> dict:
    P = priors or load_priors()
    if portrait is None:
        portrait = bool(analysis.get("faces"))
    params, conf = params_from_stats(analysis, P, portrait=portrait)
    style = empty_style(name)
    style["source"] = {"image": source_image, "created": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                       "tool": f"dot photo {__version__}", "mode": "extract"}
    notes = []
    for group in ("tone", "color", "effects"):
        for k, v in params[group].items():
            key = f"{group}.{k}"
            if conf.get(key, 1.0) < min_confidence:
                style[group][k] = 0
                notes.append(f"{key} not inferred (confidence {conf.get(key, 0):.2f} < {min_confidence})")
            else:
                style[group][k] = v
    for name_, band in params["hsl"].items():
        if conf.get(f"hsl.{name_}", 1.0) < min_confidence:
            notes.append(f"hsl.{name_} not inferred (confidence {conf.get(f'hsl.{name_}', 0):.2f} < {min_confidence})")
            continue
        style["hsl"][name_] = band
    for zone, g in params["grade"].items():
        if zone == "balance":
            style["grade"]["balance"] = 0.0
            continue
        if conf.get(f"grade.{zone}", 1.0) < min_confidence:
            notes.append(f"grade.{zone} not inferred (confidence {conf.get(f'grade.{zone}', 0):.2f} < {min_confidence})")
            continue
        style["grade"][zone] = g
    style["curve"] = {"rgb": None, "r": None, "g": None, "b": None}
    conf["curve"] = 0.0
    notes.append("curve is identity at extract time; `style apply --mode match` derives one from stats")
    stats = {k: v for k, v in analysis.items() if k not in ("faces",)}
    style["stats"] = stats
    weights, total = 0.0, 0.0
    for key, c in conf.items():
        g, _, k = key.partition(".")
        v = params.get(g, {}).get(k, 0)
        mag = abs(v) if isinstance(v, (int, float)) else 1.0
        w = 1.0 + mag / 20.0
        weights += w
        total += w * c
    conf["overall"] = round(total / max(weights, 1e-6), 2)
    style["confidence"] = conf
    style["notes"] = notes
    return style


# ---------------------------------------------------------------- application

def scaled(style: dict, strength: float) -> dict:
    s = copy.deepcopy(style)
    k = float(strength)
    for group in ("tone", "color", "effects"):
        for key in list(s.get(group, {}).keys()):
            s[group][key] = s[group][key] * k
    for band in s.get("hsl", {}).values():
        for key in band:
            band[key] = band[key] * k
    for zone, g in s.get("grade", {}).items():
        if isinstance(g, dict) and "sat" in g:
            g["sat"] = g["sat"] * k
    s["_strength"] = k
    return s


def _match_params(style: dict, target_analysis: dict, priors: dict, mode: str) -> tuple[dict, list[str]]:
    """Return a copy of the style whose MATCH_FIELDS are 'reference minus target' deltas."""
    st = style.get("stats")
    if not st or not target_analysis:
        return style, []
    portrait = bool(target_analysis.get("faces"))
    ref_params, _ = params_from_stats(st, priors, portrait=portrait)
    tgt_params, _ = params_from_stats(target_analysis, priors, portrait=portrait)
    out = copy.deepcopy(style)
    matched = []
    for key in MATCH_FIELDS:
        g, _, k = key.partition(".")
        out[g][k] = ref_params[g][k] - tgt_params[g][k]
        matched.append(key)
    if mode == "match":
        rp, tp = st["luma_percentiles"], target_analysis["luma_percentiles"]
        pts = [[0, 0]]
        last = 0.0
        for p in ("p1", "p5", "p25", "p50", "p75", "p95", "p99"):
            x = tp[p] * 255.0
            y = max(rp[p] * 255.0, last + 0.5)
            last = y
            pts.append([round(x, 1), round(y, 1)])
        pts.append([255, 255])
        out["curve"]["rgb"] = pts
        # when the curve carries the tone, keep only WB from the matched tone fields
        for key in ("tone.contrast", "tone.blacks", "tone.whites"):
            g, _, k = key.partition(".")
            out[g][k] = 0.0
        matched.append("curve.rgb")
    return out, matched


def apply(img: WorkImage, style: dict, *, strength: float = 1.0, mode: str = "params",
          target_analysis: dict | None = None, priors: dict | None = None, seed: int = 0,
          lum_masks: dict | None = None) -> tuple[WorkImage, dict]:
    """Apply a style. mode: params (as stored), hybrid (tone/WB matched against the target's own
    analysis), match (hybrid + a tone curve from quantile matching)."""
    if mode not in ("params", "hybrid", "match"):
        raise DotPhotoError("BAD_MODE", f"unknown mode {mode}", "use params, hybrid or match", 2)
    P = priors or load_priors()
    matched: list[str] = []
    eff = style
    if mode in ("hybrid", "match"):
        eff, matched = _match_params(style, target_analysis or {}, P, mode)
    eff = scaled(eff, strength)
    rgb = f32(img.rgb).copy()
    h, w = rgb.shape[:2]
    short = min(h, w)
    tone, col, fx = eff["tone"], eff["color"], eff["effects"]

    # 1. white balance
    gains = temperature_tint_gains(col["temperature"], col["tint"])
    if np.any(np.abs(gains - 1) > 1e-6):
        rgb = np.clip(rgb * gains[None, None, :], 0, 1)
    # 2. exposure in linear light
    if abs(tone["exposure"]) > 1e-6:
        rgb = linear_to_srgb(srgb_to_linear(rgb) * (2.0 ** tone["exposure"]))
    # 3. blacks / whites / contrast / curve as one luma LUT
    curve_pts = eff.get("curve", {}).get("rgb")
    curve = build_curve_lut(curve_pts) if curve_pts else identity_lut()
    if strength != 1.0 and curve_pts:
        curve = identity_lut() * (1 - strength) + curve * strength
    lut = compose_luts(blacks_whites_lut(tone["blacks"], tone["whites"]), s_curve_lut(tone["contrast"]), curve)
    if np.abs(lut - identity_lut()).max() > 1e-6:
        rgb = apply_lut_luma(rgb, lut)
    # 4. highlights / shadows with luminosity masks
    if abs(tone["shadows"]) > 1e-6 or abs(tone["highlights"]) > 1e-6:
        lm = lum_masks or M.luminosity_masks(rgb)
        sh = tone["shadows"] / 100.0
        hi = tone["highlights"] / 100.0
        if sh > 0:
            rgb = rgb + (sh * 0.30 * lm["darks"])[..., None] * (1 - rgb)
        elif sh < 0:
            rgb = rgb + (sh * 0.30 * lm["darks"])[..., None] * rgb
        if hi > 0:
            rgb = rgb + (hi * 0.25 * lm["lights"])[..., None] * (1 - rgb)
        elif hi < 0:
            rgb = rgb + (hi * 0.25 * lm["lights"])[..., None] * rgb
        rgb = np.clip(rgb, 0, 1)
    # 5. per-channel curves
    for ch, idx in (("r", 0), ("g", 1), ("b", 2)):
        pts = eff.get("curve", {}).get(ch)
        if pts:
            rgb[..., idx] = lookup(rgb[..., idx], build_curve_lut(pts))
    # 6. vibrance / saturation / HSL
    hsl = {k: v for k, v in eff.get("hsl", {}).items() if any(abs(x) > 1e-6 for x in v.values())}
    if hsl or abs(col["saturation"]) > 1e-6 or abs(col["vibrance"]) > 1e-6:
        hsv = rgb_to_hsv(rgb)
        H, S, V = hsv[..., 0].copy(), hsv[..., 1].copy(), hsv[..., 2].copy()
        if abs(col["saturation"]) > 1e-6:
            S = S * (1 + col["saturation"] / 100.0)
        if abs(col["vibrance"]) > 1e-6:
            # vibrance boosts low-saturation pixels more, and protects skin (orange band)
            prot = 1 - 0.6 * hue_soft_weight(H, "orange")
            S = S + col["vibrance"] / 100.0 * 0.6 * (1 - S) * S * prot * 2
        for name, band in hsl.items():
            wgt = hue_soft_weight(H, name) * np.clip(S / 0.1, 0, 1)
            if abs(band.get("hue", 0)) > 1e-6:
                H = (H + band["hue"] * 0.3 * wgt) % 360.0
            if abs(band.get("sat", 0)) > 1e-6:
                S = S * (1 + band["sat"] / 100.0 * wgt)
            if abs(band.get("lum", 0)) > 1e-6:
                V = V * (1 + band["lum"] / 200.0 * wgt)
        rgb = hsv_to_rgb(np.stack([H, np.clip(S, 0, 1), np.clip(V, 0, 1)], axis=2))
    # 7. color grading in Lab per luminosity zone
    grade = {z: g for z, g in eff.get("grade", {}).items() if isinstance(g, dict) and abs(g.get("sat", 0)) > 1e-6}
    if grade:
        lm = M.luminosity_masks(rgb)
        zone_mask = {"shadows": lm["darks"], "midtones": lm["mids"], "highlights": lm["lights"]}
        lab = rgb_to_lab(rgb)
        for zone, g in grade.items():
            m = zone_mask.get(zone)
            if m is None:
                continue
            amt = g["sat"] / 100.0 * 12.0
            rad = math.radians(g.get("hue", 0.0))
            lab[..., 1] += amt * math.cos(rad) * m
            lab[..., 2] += amt * math.sin(rad) * m
        rgb = lab_to_rgb(lab)
    # 8. effects
    if abs(fx["clarity"]) > 1e-6:
        L = luma(rgb)
        hp = L - guided_filter(L, L, max(2, int(short / 40)), 0.04)
        rgb = np.clip(rgb + (fx["clarity"] / 100.0 * 0.5 * hp)[..., None], 0, 1)
    if abs(fx["texture"]) > 1e-6:
        L = luma(rgb)
        hp = L - gaussian(L, 2.0)
        rgb = np.clip(rgb + (fx["texture"] / 100.0 * 0.4 * hp)[..., None], 0, 1)
    if fx["dehaze"] > 1e-6:
        from .landscape import dehaze
        rgb, _ = dehaze(rgb, fx["dehaze"] / 100.0)
    elif fx["dehaze"] < -1e-6:
        # negative dehaze = add haze (lift toward light gray)
        k = -fx["dehaze"] / 100.0 * 0.3
        rgb = np.clip(rgb * (1 - k) + 0.85 * k, 0, 1)
    if abs(fx["vignette"]) > 1e-6:
        r = M.radial_falloff(h, w)
        factor = 1 + fx["vignette"] / 100.0 * 0.6 * (r ** 2)
        rgb = np.clip(rgb * factor[..., None], 0, 1)
    if fx["grain"] > 1e-6:
        rng = np.random.default_rng(seed)
        noise = rng.normal(0.0, 1.0, (h, w)).astype(np.float32)
        noise = gaussian(noise, 0.6)
        noise = noise / max(noise.std(), 1e-6)
        L = luma(rgb)
        amp = fx["grain"] / 100.0 * 0.05 * (0.3 + 0.7 * (1 - L))
        rgb = np.clip(rgb + (noise * amp)[..., None], 0, 1)

    info = {"mode": mode, "strength": float(strength), "matched_fields": matched,
            "params_used": {"tone": eff["tone"], "color": eff["color"], "effects": eff["effects"],
                            "hsl": eff.get("hsl", {}), "grade": eff.get("grade", {}),
                            "curve": eff.get("curve", {}).get("rgb")}}
    return img.copy_with(rgb.astype(np.float32)), info
