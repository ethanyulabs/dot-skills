"""Synthetic fixtures. Everything is generated with a fixed seed so assertions are stable."""
import os
import sys

import numpy as np
import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import cv2  # noqa: E402

from dphoto_lib.imageio import WorkImage, save_jpeg  # noqa: E402


def _rng(seed=0):
    return np.random.default_rng(seed)


@pytest.fixture
def gradient_img():
    """1024x768 horizontal 0->1 gray gradient with a little noise."""
    w, h = 1024, 768
    x = np.linspace(0.0, 1.0, w, dtype=np.float32)
    rgb = np.repeat(x[None, :, None], h, axis=0)
    rgb = np.repeat(rgb, 3, axis=2)
    rgb = rgb + _rng(1).normal(0, 0.003, rgb.shape).astype(np.float32)
    return WorkImage(rgb=np.clip(rgb, 0, 1).astype(np.float32))


@pytest.fixture
def warm_cast_img():
    """Neutral mid-gray scene with a warm cast (R x1.1, B x0.9) and some structure."""
    w, h = 800, 600
    base = _rng(2).uniform(0.35, 0.65, (h, w, 1)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 6)[..., None]
    rgb = np.repeat(base, 3, axis=2)
    rgb[..., 0] *= 1.10
    rgb[..., 2] *= 0.90
    return WorkImage(rgb=np.clip(rgb, 0, 1).astype(np.float32))


@pytest.fixture
def skin_patch():
    """1200x1200 skin-colored field with fine texture, 6 dark blemish dots, 1 mole, 2 'eyes'.
    Returns (WorkImage, meta) with the positions used by the assertions."""
    size = 1200
    lab = np.zeros((size, size, 3), np.float32)
    lab[..., 0] = 62.0
    lab[..., 1] = 14.0
    lab[..., 2] = 18.0
    rgb = np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB), 0, 1)
    tex = _rng(3).normal(0, 0.035, (size, size, 1)).astype(np.float32)
    tex = cv2.GaussianBlur(tex, (0, 0), 1.2)[..., None] * 2.0  # pore-like texture
    rgb = np.clip(rgb + tex, 0, 1)
    # gentle shading so the field is not perfectly flat
    yy = np.linspace(-0.04, 0.04, size, dtype=np.float32)[:, None, None]
    rgb = np.clip(rgb + yy, 0, 1)
    dots = [(300, 300, 3), (500, 360, 4), (700, 420, 5), (400, 650, 6), (800, 700, 4), (600, 900, 5)]
    for (x, y, r) in dots:
        cv2.circle(rgb, (x, y), r, (0.25, 0.12, 0.10), -1, lineType=cv2.LINE_AA)
    mole = (900, 300, 12)
    cv2.circle(rgb, (mole[0], mole[1]), mole[2], (0.28, 0.16, 0.12), -1, lineType=cv2.LINE_AA)
    eyes = [(380, 180, 70, 36), (820, 180, 70, 36)]  # cx, cy, half-w, half-h
    for (cx, cy, hw, hh) in eyes:
        cv2.ellipse(rgb, (cx, cy), (hw, hh), 0, 0, 360, (0.95, 0.95, 0.95), -1, lineType=cv2.LINE_AA)
        cv2.circle(rgb, (cx, cy), 18, (0.08, 0.06, 0.05), -1, lineType=cv2.LINE_AA)
    meta = {"dots": dots, "mole": mole, "eyes": eyes, "size": size,
            "face_box": [150, 100, 900, 1000]}
    return WorkImage(rgb=rgb.astype(np.float32)), meta


@pytest.fixture
def sky_ground():
    """1200x800: top half hazy blue sky gradient, bottom half textured green ground."""
    w, h = 1200, 800
    rgb = np.zeros((h, w, 3), np.float32)
    half = h // 2
    t = np.linspace(0.0, 1.0, half, dtype=np.float32)[:, None]
    top = np.array([0.30, 0.50, 0.90], np.float32)
    hor = np.array([0.60, 0.75, 0.95], np.float32)
    sky = top[None, None, :] * (1 - t[..., None]) + hor[None, None, :] * t[..., None]
    sky = sky * 0.7 + 0.3  # haze: mix with white
    rgb[:half] = np.repeat(sky, w, axis=1)
    g = _rng(4).uniform(0.0, 1.0, (h - half, w, 1)).astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 1.5)[..., None]
    ground = np.array([0.18, 0.42, 0.14], np.float32)[None, None, :] * (0.6 + 0.8 * g)
    rgb[half:] = np.clip(ground, 0, 1)
    return WorkImage(rgb=np.clip(rgb, 0, 1).astype(np.float32))


@pytest.fixture
def oriented_jpeg(tmp_path):
    """A 300x200 JPEG with EXIF Orientation=6 (needs a 90-degree rotation on load) and GPS."""
    arr = np.zeros((200, 300, 3), np.uint8)
    arr[:, :150] = (200, 40, 40)
    arr[:, 150:] = (40, 40, 200)
    im = Image.fromarray(arr, "RGB")
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "dot-photo-test"
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (IFDRational(40, 1), IFDRational(0, 1), IFDRational(0, 1))
    p = tmp_path / "oriented.jpg"
    im.save(p, "JPEG", quality=95, exif=exif.tobytes())
    return str(p)


@pytest.fixture
def heic_file(tmp_path):
    try:
        import pillow_heif
    except Exception:
        pytest.skip("pillow-heif missing")
    arr = np.zeros((120, 160, 3), np.uint8)
    arr[..., 1] = 180
    p = tmp_path / "small.heic"
    try:
        Image.fromarray(arr, "RGB").save(p, "HEIF", quality=90)
    except Exception as e:
        pytest.skip(f"HEIF encoding unavailable: {e}")
    return str(p)


@pytest.fixture
def jpeg_from(tmp_path):
    def _make(img: WorkImage, name="in.jpg", quality=95):
        p = tmp_path / name
        save_jpeg(img.rgb, str(p), quality=quality, strip_exif=True)
        return str(p)
    return _make
