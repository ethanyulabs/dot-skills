import os

import numpy as np
from PIL import Image

from dphoto_lib import export as E
from dphoto_lib.masks import Face


def test_print_sizes_and_ppi(gradient_img, tmp_path):
    presets = E.load_presets()
    res, info = E.export(gradient_img, targets=["print"], presets=presets, faces=[], paper="4x6", finish="matte",
                         out_dir=str(tmp_path / "e"))
    r = res[0]
    assert r["size"] == [1800, 1200]  # landscape input -> 6x4 at 300 ppi
    im = Image.open(r["path"])
    assert int(im.info["dpi"][0]) == 300
    assert os.path.basename(r["path"]) == "print_4x6_matte.jpg"
    res, _ = E.export(gradient_img, targets=["print"], presets=presets, faces=[], paper="A4", finish="glossy",
                      fit="pad", out_dir=str(tmp_path / "e2"), tiff16=True)
    assert res[0]["size"] == [3507, 2481] and os.path.isfile(res[0]["tiff"])


def test_web(sky_ground, oriented_jpeg, tmp_path):
    from dphoto_lib.imageio import load
    presets = E.load_presets()
    src = load(oriented_jpeg)
    res, _ = E.export(sky_ground.copy_with(sky_ground.rgb), targets=["web"], presets=presets, faces=[],
                      out_dir=str(tmp_path / "w"), exif=src.exif)
    r = res[0]
    assert max(r["size"]) == min(2048, 1200)
    assert r["exif_stripped"] is True
    im = Image.open(r["path"])
    assert len(im.getexif()) == 0 and im.info.get("icc_profile")


def test_dating_face_placement(skin_patch, tmp_path):
    img, _ = skin_patch
    face = Face(box=[500, 300, 240, 300], confidence=1.0, kind="manual")
    presets = E.load_presets()
    res, info = E.export(img, targets=["dating"], presets=presets, faces=[face], out_dir=str(tmp_path / "d"),
                         dating_retouch=False)
    sizes = {r["target"]: r["size"] for r in res}
    assert sizes == {"dating_1x1": [1080, 1080], "dating_4x5": [1080, 1350]}
    for r in res:
        assert 0.33 <= r["face_center_frac"][1] <= 0.43, r
        assert 0.25 <= r["face_height_frac"] <= 0.35, r
        assert r["face_in_safe_area"]
        assert r["exif_stripped"]
        assert len(Image.open(r["path"]).getexif()) == 0
    assert not info["reviews"]


def test_dating_without_face(sky_ground, tmp_path):
    presets = E.load_presets()
    res, info = E.export(sky_ground, targets=["dating"], presets=presets, faces=[], out_dir=str(tmp_path / "n"))
    assert [c for c, _ in info["reviews"]] == ["NO_FACE"]
    assert all("face_box_in_output" not in r for r in res)


def test_dating_retouch_runs(skin_patch, tmp_path):
    img, meta = skin_patch
    x, y, w, h = meta["face_box"]
    face = Face(box=[x, y, w, h], confidence=1.0, kind="manual")
    presets = E.load_presets()
    res, _ = E.export(img, targets=["dating"], presets=presets, faces=[face], out_dir=str(tmp_path / "r"),
                      dating_retouch=True)
    assert all(r["retouched"] for r in res)


def test_bad_target(gradient_img, tmp_path):
    import pytest
    from dphoto_lib import DotPhotoError
    with pytest.raises(DotPhotoError):
        E.export(gradient_img, targets=["tiktok"], presets=E.load_presets(), faces=[], out_dir=str(tmp_path))


def test_print_upscale_reported(gradient_img, tmp_path):
    presets = E.load_presets()
    res, info = E.export(gradient_img, targets=["print"], presets=presets, faces=[], paper="8x10", finish="matte",
                         out_dir=str(tmp_path / "up"))
    assert res[0]["upscale"] > 1.5
    assert [c for c, _ in info["reviews"]] == ["PRINT_UPSCALE_HIGH"]
    box = res[0]["crop_box_in_source"]
    assert len(box) == 4 and box[2] <= gradient_img.width + 1


def test_dating_bounded_by_small_image(skin_patch, tmp_path):
    img, meta = skin_patch
    x, y, w, h = meta["face_box"]
    face = Face(box=[x, y, w, h], confidence=1.0, kind="manual")
    res, _ = E.export(img, targets=["dating"], presets=E.load_presets(), faces=[face], out_dir=str(tmp_path / "b"),
                      dating_retouch=False)
    assert all(r["crop"]["bounded_by_image"] for r in res)
    assert all(r["face_height_frac"] > 0.35 for r in res)
