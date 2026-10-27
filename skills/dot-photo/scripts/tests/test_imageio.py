import numpy as np
from PIL import Image

from dphoto_lib import imageio


def test_orientation_and_gps(oriented_jpeg, tmp_path):
    img = imageio.load(oriented_jpeg)
    assert (img.width, img.height) == (200, 300)  # rotated
    assert img.source["orientation"] == 6
    # after rotation by 6 (90 CW) the red half ends up on top
    assert img.rgb[:100, :, 0].mean() > 0.6 and img.rgb[200:, :, 2].mean() > 0.6
    out = tmp_path / "o.jpg"
    info = imageio.save_jpeg(img.rgb, str(out), exif=img.exif, strip_gps=True, quality=90)
    assert info["exif_stripped"] is False
    ex = Image.open(out).getexif()
    assert ex.get(0x010F) == "dot-photo-test"
    assert ex.get(0x0112, 1) == 1
    assert 0x8825 not in ex and not ex.get_ifd(0x8825)


def test_strip_exif_entirely(oriented_jpeg, tmp_path):
    img = imageio.load(oriented_jpeg)
    out = tmp_path / "s.jpg"
    info = imageio.save_jpeg(img.rgb, str(out), exif=img.exif, strip_exif=True)
    assert info["exif_stripped"] is True
    ex = Image.open(out).getexif()
    assert len(ex) == 0
    assert Image.open(out).info.get("icc_profile")


def test_jpeg_ppi(gradient_img, tmp_path):
    out = tmp_path / "p.jpg"
    imageio.save_jpeg(gradient_img.rgb, str(out), ppi=300)
    assert Image.open(out).info["dpi"][0] == 300


def test_tiff16_roundtrip(gradient_img, tmp_path):
    out = tmp_path / "x.tif"
    info = imageio.save_tiff16(gradient_img.rgb, str(out))
    assert info["bit_depth"] == 16
    back = imageio.load(str(out))
    assert back.source["bit_depth"] == 16
    assert back.source["source_profile"].lower().startswith("srgb")
    assert np.abs(back.rgb - gradient_img.rgb).max() <= 2.0 / 65535 + 1e-6


def test_tiff16_pillow_reads_header(gradient_img, tmp_path):
    out = tmp_path / "y.tif"
    imageio.save_tiff16(gradient_img.rgb, str(out), ppi=240)
    with Image.open(out) as im:
        assert im.size == (gradient_img.width, gradient_img.height)
        assert im.info.get("icc_profile")
        assert int(im.info["dpi"][0]) == 240


def test_srgb_icc_passthrough(gradient_img, tmp_path):
    p = tmp_path / "icc.jpg"
    imageio.save_jpeg(gradient_img.rgb, str(p), quality=100, subsampling=0)
    back = imageio.load(str(p))
    assert back.source["source_profile"].lower().startswith("srgb")
    assert np.abs(back.rgb - gradient_img.rgb).mean() < 0.01


def test_heic_loads(heic_file):
    img = imageio.load(heic_file)
    assert (img.width, img.height) == (160, 120)
    assert img.rgb[..., 1].mean() > 0.6


def test_downscale(gradient_img):
    small, scale = imageio.downscale(gradient_img, 100_000)
    assert small.width * small.height <= 100_000 * 1.02
    assert abs(scale - small.width / gradient_img.width) < 1e-6


def test_missing_file_raises():
    import pytest
    from dphoto_lib import DotPhotoError
    with pytest.raises(DotPhotoError) as e:
        imageio.load("/nonexistent/file.jpg")
    assert e.value.exit_code == 3


def test_default_out_dir():
    assert imageio.default_out_dir("/a/b/IMG_1.HEIC") == "/a/b/IMG_1.dot-photo"
