import numpy as np

from dphoto_lib import analyze as A


def test_gradient_percentiles(gradient_img):
    an = A.analyze(gradient_img, faces=[], with_sky=False)
    p = an["luma_percentiles"]
    assert 0.52 <= p["p50"] <= 0.55  # Lab L of sRGB 0.5 is ~0.534
    assert p["p1"] < 0.03 and p["p99"] > 0.97
    assert an["faces"] == []
    assert an["neutral_lab_mean"]["coverage"] > 0.3
    assert abs(an["neutral_lab_mean"]["b"]) < 1.0


def test_warm_cast_detected(warm_cast_img):
    an = A.analyze(warm_cast_img, faces=[], with_sky=False)
    assert an["neutral_lab_mean"]["b"] > 3.0
    assert an["skin"]["present"] in (True, False)


def test_hsl_hist_sky_ground(sky_ground):
    an = A.analyze(sky_ground, faces=[])
    h = an["hsl_hist"]
    assert 0.4 <= h["blue"]["frac"] + h["aqua"]["frac"] <= 0.6
    assert 0.4 <= h["green"]["frac"] <= 0.6
    assert an["sky_coverage"] > 0.4
    assert an["haze"]["dark_channel_top"] > an["haze"]["dark_channel_mean"]


def test_classify_rules():
    base = {"size": [1200, 800], "faces": [], "skin": {"coverage": 0.0}, "sky_coverage": 0.0}
    assert A.classify(dict(base, sky_coverage=0.3))["value"] == "landscape"
    assert A.classify(dict(base))["value"] == "landscape"  # aspect 1.5, no skin
    sq = dict(base, size=[1000, 1000])
    assert A.classify(sq)["value"] == "unknown"
    face = dict(sq, faces=[{"box": [100, 100, 300, 300]}], skin={"coverage": 0.1})
    c = A.classify(face)
    assert c["value"] == "portrait" and c["confidence"] >= 0.85
    small = dict(sq, faces=[{"box": [100, 100, 50, 50]}], skin={"coverage": 0.01})
    assert A.classify(small)["confidence"] < 0.75


def test_hue_soft_weight():
    H = np.array([30.0, 50.0, 120.0], np.float32)
    w = A.hue_soft_weight(H, "orange")
    assert w[0] == 1.0 and w[2] == 0.0 and 0 < w[1] < 1
