import numpy as np

from dphoto_lib import masks as M


def test_skin_mask_on_patch(skin_patch):
    img, meta = skin_patch
    x, y, w, h = meta["face_box"]
    face = M.Face(box=[x, y, w, h], eyes=[[cx - hw, cy - hh, 2 * hw, 2 * hh] for (cx, cy, hw, hh) in meta["eyes"]],
                  confidence=1.0, kind="manual")
    m, info = M.skin_mask(img.rgb, [face])
    inner = m[250:1050, 250:1000]
    assert inner.mean() >= 0.85, inner.mean()
    for (cx, cy, hw, hh) in meta["eyes"]:
        assert m[cy - 10:cy + 10, cx - 10:cx + 10].mean() < 0.1
    assert 0.3 < info["coverage"] <= 1.0


def test_skin_mask_without_faces_caps(skin_patch):
    img, _ = skin_patch
    m, info = M.skin_mask(img.rgb, [], max_coverage=0.45)
    assert info.get("capped") is True and m.max() == 0
    m2, info2 = M.skin_mask(img.rgb, [], max_coverage=0.99)
    assert m2.mean() > 0.8


def test_luminosity_masks_sum(gradient_img):
    lm = M.luminosity_masks(gradient_img.rgb)
    s = lm["lights"] + lm["darks"] + lm["mids"]
    assert np.allclose(s, 1.0, atol=1e-5)
    assert lm["lights"][:, -1].mean() > 0.9 and lm["darks"][:, 0].mean() > 0.9


def test_sky_mask(sky_ground):
    m = M.sky_mask(sky_ground.rgb)
    h = m.shape[0]
    assert m[: int(h * 0.45)].mean() >= 0.9
    assert m[int(h * 0.55):].mean() <= 0.1


def test_depth_bands_sum(sky_ground):
    rgb = sky_ground.rgb
    dark = M.dark_channel(rgb, 15)
    A = M.atmosphere(rgb, dark)
    t = M.transmission(rgb, A)
    sky = M.sky_mask(rgb)
    bands = M.depth_bands(t, sky)
    s = bands["far"] + bands["mid"] + bands["near"]
    assert np.allclose(s, 1.0, atol=1e-4)
    assert bands["far"][:100].mean() > 0.9


def test_detect_faces_no_false_positive(sky_ground, gradient_img):
    assert M.detect_faces(sky_ground.rgb) == []
    assert M.detect_faces(gradient_img.rgb) == []


def test_radial_and_vertical():
    r = M.radial_falloff(100, 200)
    assert r[50, 100] < 0.02 and r[0, 0] > 0.98
    g = M.vertical_gradient(100, 10)
    assert g[0, 0] == 1.0 and g[60, 0] == 0.0
