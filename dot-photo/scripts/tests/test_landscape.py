import numpy as np

from dphoto_lib import landscape as LS
from dphoto_lib import masks as M
from dphoto_lib.color import gaussian, luma

DEFAULTS = {"black": 0.5, "white": 99.5, "far_clarity": -15, "near_texture": 20, "dehaze": 0.15,
            "clahe": 2.5, "clahe_tile": 8, "orton": 0.0, "sky": True, "sky_darken": 0.15}


def test_black_white_points(sky_ground):
    out, info = LS.enhance(sky_ground, params=dict(DEFAULTS, dehaze=0.0, clahe=0.0, sky_darken=0.0,
                                                    far_clarity=0, near_texture=0))
    L = luma(out.rgb)
    assert np.percentile(L, 0.5) <= 0.006
    assert np.percentile(L, 99.5) >= 0.994
    assert info["metrics"]["clip_fraction"] == 0.01
    assert not any(c == "CLIP_HIGH" for c, _ in info["reviews"])
    _, info2 = LS.enhance(sky_ground, params=dict(DEFAULTS, black=2.0))
    assert any(c == "CLIP_HIGH" for c, _ in info2["reviews"])


def test_dehaze_lowers_dark_channel(sky_ground):
    base, _ = LS.enhance(sky_ground, params=dict(DEFAULTS, dehaze=0.0, clahe=0.0, sky_darken=0.0,
                                                  far_clarity=0, near_texture=0))
    out, info = LS.enhance(sky_ground, params=dict(DEFAULTS, dehaze=1.0, clahe=0.0, sky_darken=0.0,
                                                   far_clarity=0, near_texture=0))
    h = out.rgb.shape[0]
    d0 = M.dark_channel(base.rgb, 15)[: h // 3].mean()
    d1 = M.dark_channel(out.rgb, 15)[: h // 3].mean()
    assert d1 < d0 * 0.7, (d0, d1)
    assert info["metrics"]["dehaze"]["omega"] > 0


def test_sky_darkening_is_graduated(sky_ground):
    base, _ = LS.enhance(sky_ground, params=dict(DEFAULTS, sky_darken=0.0))
    out, info = LS.enhance(sky_ground, params=dict(DEFAULTS, sky_darken=0.3))
    L0, L1 = luma(base.rgb), luma(out.rgb)
    top = (L0[:40] - L1[:40]).mean()
    horizon = info["metrics"]["horizon_row"]
    assert horizon is not None and 300 < horizon < 500
    near_h = (L0[horizon - 30:horizon - 10] - L1[horizon - 30:horizon - 10]).mean()
    assert top > near_h >= -1e-3
    assert np.abs(L0[horizon + 60:] - L1[horizon + 60:]).max() < 1e-3


def test_ground_texture_not_lost(sky_ground):
    out, info = LS.enhance(sky_ground, params=DEFAULTS)
    m = info["metrics"]
    assert m["ground_texture_after"] >= m["ground_texture_before"] * 0.95
    assert m["sky_coverage"] > 0.4
    assert len(info["focus"]) == 4
    assert m["halo_ratio"] < 1.8


def test_orton_brightens_softly(sky_ground):
    base, _ = LS.enhance(sky_ground, params=dict(DEFAULTS, orton=0.0))
    out, _ = LS.enhance(sky_ground, params=dict(DEFAULTS, orton=0.15))
    assert luma(out.rgb).mean() > luma(base.rgb).mean()
    # glow lowers fine detail a little, but not much at 0.15
    L0, L1 = luma(base.rgb), luma(out.rgb)
    f0 = (L0 - gaussian(L0, 2))[500:].std()
    f1 = (L1 - gaussian(L1, 2))[500:].std()
    assert f1 > f0 * 0.7


def test_no_sky_image_still_works(gradient_img):
    out, info = LS.enhance(gradient_img, params=DEFAULTS)
    assert out.rgb.shape == gradient_img.rgb.shape
    assert np.isfinite(out.rgb).all()
