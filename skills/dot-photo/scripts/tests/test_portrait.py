import numpy as np

from dphoto_lib import portrait as P
from dphoto_lib.color import luma
from dphoto_lib.masks import Face


def _face(meta):
    x, y, w, h = meta["face_box"]
    return Face(box=[x, y, w, h], eyes=[[cx - hw, cy - hh, 2 * hw, 2 * hh] for (cx, cy, hw, hh) in meta["eyes"]],
                confidence=1.0, kind="manual")


def _spot_contrast(L, x, y, r):
    yy, xx = np.mgrid[0:L.shape[0], 0:L.shape[1]]
    d = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    inner = L[d <= r].mean()
    ring = L[(d > r + 4) & (d <= r + 12)].mean()
    return abs(float(inner - ring))


def test_blemishes_removed_mole_kept(skin_patch):
    img, meta = skin_patch
    out, info = P.retouch(img, faces=[_face(meta)], eye_sharpen=0.0)
    L0, L1 = luma(img.rgb), luma(out.rgb)
    for (x, y, r) in meta["dots"]:
        assert _spot_contrast(L0, x, y, r) > 0.2
        assert _spot_contrast(L1, x, y, r) < 0.03, (x, y, _spot_contrast(L1, x, y, r))
    mx, my, mr = meta["mole"]
    assert _spot_contrast(L1, mx, my, mr) > 0.1
    assert info["metrics"]["blemishes_removed"] >= 6
    assert info["metrics"]["moles_kept"] >= 1
    assert info["metrics"]["texture_retained"] >= 0.6
    assert info["skin_coverage"] > 0.5


def test_remove_moles_flag(skin_patch):
    img, meta = skin_patch
    out, info = P.retouch(img, faces=[_face(meta)], remove_moles=True, eye_sharpen=0.0)
    mx, my, mr = meta["mole"]
    assert _spot_contrast(luma(out.rgb), mx, my, mr) < 0.03
    assert info["metrics"]["moles_removed"] >= 1


def test_non_skin_untouched(skin_patch):
    img, meta = skin_patch
    out, _ = P.retouch(img, faces=[_face(meta)], eye_sharpen=0.0)
    for (cx, cy, hw, hh) in meta["eyes"]:
        d = np.abs(out.rgb[cy - 8:cy + 8, cx - 8:cx + 8] - img.rgb[cy - 8:cy + 8, cx - 8:cx + 8]).max()
        assert d < 1e-3, d


def test_eye_sharpen_changes_eyes_only(skin_patch):
    img, meta = skin_patch
    a, _ = P.retouch(img, faces=[_face(meta)], eye_sharpen=0.0, blemish=False, skin_strength=0.0)
    b, _ = P.retouch(img, faces=[_face(meta)], eye_sharpen=0.8, blemish=False, skin_strength=0.0)
    cx, cy, hw, hh = meta["eyes"][0]
    assert np.abs(b.rgb[cy - 20:cy + 20, cx - 20:cx + 20] - a.rgb[cy - 20:cy + 20, cx - 20:cx + 20]).max() > 1e-3
    assert np.abs(b.rgb[700:900, 300:500] - a.rgb[700:900, 300:500]).max() < 1e-6


def test_smoothing_reduces_blotch_but_keeps_pores(skin_patch):
    img, meta = skin_patch
    out, info = P.retouch(img, faces=[_face(meta)], blemish=False, eye_sharpen=0.0, skin_strength=0.7)
    L0, L1 = luma(img.rgb), luma(out.rgb)
    region = (slice(600, 1000), slice(300, 800))
    fine0 = (L0 - P.gaussian(L0, 1.5))[region].std()
    fine1 = (L1 - P.gaussian(L1, 1.5))[region].std()
    assert fine1 > fine0 * 0.6          # pores survive
    assert info["metrics"]["texture_retained"] >= 0.6


def test_no_face_whole_image_capped(skin_patch):
    img, _ = skin_patch
    out, info = P.retouch(img, faces=[])
    assert info["skin_coverage"] == 0.0
    assert np.abs(out.rgb - img.rgb).max() < 1e-6
    assert any("skin mask disabled" in w for w in info["warnings"])
