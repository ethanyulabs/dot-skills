import copy

import numpy as np
import pytest

from dphoto_lib import DotPhotoError
from dphoto_lib import analyze as A
from dphoto_lib import style as S
from dphoto_lib.color import luma, rgb_to_hsv


def _p50(img):
    return float(np.median(luma(img.rgb)))


def test_presets_resolve_and_validate():
    for name in ("neutral", "clean-portrait", "film-warm", "dating-safe"):
        st = S.resolve(name)
        assert S.validate(st) == []
        assert st["name"] == name
    with pytest.raises(DotPhotoError) as e:
        S.resolve("does-not-exist")
    assert e.value.exit_code == 2


def test_validate_rejects_bad():
    st = S.resolve("neutral")
    bad = copy.deepcopy(st); bad["tone"]["exposure"] = 9
    assert S.validate(bad)
    bad = copy.deepcopy(st); bad["tone"]["bogus"] = 1
    assert S.validate(bad)
    bad = copy.deepcopy(st); bad["hsl"] = {"red": {"sat": 200}}
    assert S.validate(bad)
    bad = copy.deepcopy(st); del bad["tone"]
    assert S.validate(bad)


def test_neutral_is_identity(warm_cast_img):
    out, info = S.apply(warm_cast_img, S.resolve("neutral"))
    assert np.abs(out.rgb - warm_cast_img.rgb).max() < 1e-3
    assert info["params_used"]["tone"]["exposure"] == 0


def test_strength_zero_is_identity(sky_ground):
    out, _ = S.apply(sky_ground, S.resolve("film-warm"), strength=0.0)
    assert np.abs(out.rgb - sky_ground.rgb).max() < 2e-3


def test_exposure_monotone(gradient_img):
    st = S.resolve("neutral")
    vals = []
    for ev in (-1.0, 0.0, 1.0):
        s = copy.deepcopy(st); s["tone"]["exposure"] = ev
        out, _ = S.apply(gradient_img, s)
        vals.append(_p50(out))
    assert vals[0] < vals[1] < vals[2]


def test_hsl_green_desaturates_ground(sky_ground):
    st = S.resolve("neutral")
    st["hsl"] = {"green": {"hue": 0, "sat": -80, "lum": 0}}
    out, _ = S.apply(sky_ground, st)
    h = sky_ground.rgb.shape[0]
    s0 = rgb_to_hsv(sky_ground.rgb)[h // 2 + 50:, :, 1].mean()
    s1 = rgb_to_hsv(out.rgb)[h // 2 + 50:, :, 1].mean()
    sky0 = rgb_to_hsv(sky_ground.rgb)[:h // 2 - 50, :, 1].mean()
    sky1 = rgb_to_hsv(out.rgb)[:h // 2 - 50, :, 1].mean()
    assert s1 < s0 * 0.5
    assert abs(sky1 - sky0) < 0.02


def test_extract_warm_cast(warm_cast_img):
    an = A.analyze(warm_cast_img, faces=[], with_sky=False)
    st = S.extract(an, name="warm", source_image="x.jpg")
    assert S.validate(st) == []
    assert st["color"]["temperature"] > 10
    assert abs(st["color"]["tint"]) < st["color"]["temperature"]
    assert st["stats"]["luma_percentiles"]["p50"] > 0
    assert 0 <= st["confidence"]["overall"] <= 1
    assert st["curve"]["rgb"] is None


def test_extract_min_confidence_zeroes_fields(warm_cast_img):
    an = A.analyze(warm_cast_img, faces=[], with_sky=False)
    st = S.extract(an, name="w", min_confidence=0.99)
    assert all(v == 0 for v in st["tone"].values())
    assert any("not inferred" in n for n in st["notes"])


def test_hybrid_matches_toward_reference(gradient_img, warm_cast_img):
    ref_an = A.analyze(warm_cast_img, faces=[], with_sky=False)
    st = S.extract(ref_an, name="ref")
    tgt_an = A.analyze(gradient_img, faces=[], with_sky=False)
    out, info = S.apply(gradient_img, st, mode="hybrid", target_analysis=tgt_an)
    assert "color.temperature" in info["matched_fields"]
    # the gray gradient should pick up a warm cast
    lab_b = A.rgb_to_lab(out.rgb)[..., 2]
    assert lab_b[:, 200:800].mean() > 2.0
    out2, info2 = S.apply(gradient_img, st, mode="match", target_analysis=tgt_an)
    assert "curve.rgb" in info2["matched_fields"]
    assert info2["params_used"]["curve"] is not None


def test_scaled():
    st = S.resolve("film-warm")
    half = S.scaled(st, 0.5)
    assert half["tone"]["contrast"] == st["tone"]["contrast"] * 0.5
    assert half["grade"]["shadows"]["sat"] == st["grade"]["shadows"]["sat"] * 0.5
    assert half["grade"]["shadows"]["hue"] == st["grade"]["shadows"]["hue"]


def test_user_styles_resolve_after_builtins(dot_home, monkeypatch):
    import json
    import os
    from dphoto_lib import home
    os.makedirs(home.styles_dir())
    mine = S.resolve("neutral")
    mine["name"] = "mine"
    mine["tone"]["exposure"] = 0.3
    S.save(mine, os.path.join(home.styles_dir(), "mine.json"))
    st = S.resolve("mine")
    assert st["tone"]["exposure"] == 0.3 and st["source"]["resolved_from"] == "user"
    assert S.resolve("neutral")["source"]["resolved_from"] == "builtin"
    shadow = S.resolve("neutral"); shadow["tone"]["exposure"] = 1.0
    S.save(shadow, os.path.join(home.styles_dir(), "neutral.json"))
    assert S.resolve("neutral")["tone"]["exposure"] == 0  # the built-in wins over a user file of the same name
    with pytest.raises(DotPhotoError) as e:
        S.resolve("nope")
    assert "mine" in e.value.hint and "neutral" in e.value.hint
    listing = S.list_styles()
    assert [s["name"] for s in listing["builtin"]] == ["clean-portrait", "dating-safe", "film-warm", "neutral"]
    assert {s["name"] for s in listing["user"]} == {"mine", "neutral"}
    with open(os.path.join(home.styles_dir(), "broken.json"), "w") as fh:
        fh.write("{not json")
    broken = [s for s in S.list_styles()["user"] if s["name"] == "broken"][0]
    assert broken["valid"] is False and broken["error"]


def test_reserved_and_invalid_style_names():
    assert S.is_reserved_name("Neutral") and S.is_reserved_name("none") and not S.is_reserved_name("mine")
    assert S.name_problem("") and S.name_problem("a/b") and S.name_problem(".hidden") and S.name_problem("a\\b")
    assert S.name_problem("my-look") is None
