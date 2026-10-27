"""Decode, color-manage and write images.

load() returns a WorkImage: float32 RGB 0..1 in sRGB, orientation applied, ICC converted.
Writers: save_jpeg (8-bit, ICC, EXIF handling, ppi), save_tiff16 (16-bit RGB TIFF with an
embedded sRGB profile, written by the small writer below so no extra dependency is needed),
save_png (8-bit, for masks and previews).
"""
from __future__ import annotations

import io
import os
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageCms, ImageOps

import cv2

from . import DotPhotoError
from .color import f32, p3_to_srgb, resize

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HAS_HEIF = True
except Exception:  # pragma: no cover
    HAS_HEIF = False

Image.MAX_IMAGE_PIXELS = None

SRGB_PROFILE = ImageCms.createProfile("sRGB")
SRGB_ICC_BYTES = ImageCms.ImageCmsProfile(SRGB_PROFILE).tobytes()

GPS_IFD = 0x8825
ORIENTATION = 0x0112
HEIC_SUFFIXES = {".heic", ".heif", ".hif"}
TIFF_SUFFIXES = {".tif", ".tiff"}


@dataclass
class WorkImage:
    rgb: np.ndarray                      # float32 HxWx3 sRGB 0..1
    exif: Image.Exif = field(default_factory=Image.Exif)
    source: dict = field(default_factory=dict)

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def short_side(self) -> int:
        return min(self.height, self.width)

    def copy_with(self, rgb: np.ndarray) -> "WorkImage":
        return WorkImage(rgb=f32(rgb), exif=self.exif, source=dict(self.source))


# ---------------------------------------------------------------- helpers

def profile_description(icc: bytes | None) -> str:
    if not icc:
        return ""
    try:
        return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
    except Exception:
        return "unknown"


def is_srgb_description(desc: str) -> bool:
    d = desc.lower().replace(" ", "")
    return "srgb" in d


def apply_orientation(arr: np.ndarray, orientation: int) -> np.ndarray:
    """EXIF orientation 1..8 applied to an HxWxC array."""
    o = int(orientation or 1)
    if o == 2:
        return arr[:, ::-1]
    if o == 3:
        return arr[::-1, ::-1]
    if o == 4:
        return arr[::-1]
    if o == 5:
        return np.rot90(arr, 1)[:, ::-1]
    if o == 6:
        return np.rot90(arr, -1)
    if o == 7:
        return np.rot90(arr, 1)[::-1]
    if o == 8:
        return np.rot90(arr, 1)
    return arr


def _pil_to_srgb(im: Image.Image, warnings: list[str]) -> tuple[Image.Image, str]:
    """Return an 8-bit RGB PIL image converted to sRGB and the source profile name."""
    icc = im.info.get("icc_profile")
    desc = profile_description(icc)
    source_profile = desc or "untagged"
    if im.mode not in ("RGB", "RGBA", "L", "I;16", "I", "P", "CMYK", "LA"):
        im = im.convert("RGB")
    if icc and not is_srgb_description(desc):
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            base = im.convert("RGB") if im.mode not in ("RGB", "CMYK", "L") else im
            im = ImageCms.profileToProfile(
                base, src, SRGB_PROFILE, renderingIntent=ImageCms.Intent.PERCEPTUAL, outputMode="RGB"
            )
            warnings.append(f"ICC '{desc}' converted to sRGB")
        except Exception as e:  # pragma: no cover - lcms edge cases
            warnings.append(f"ICC conversion failed ({e}); treated as sRGB")
            im = im.convert("RGB")
    elif im.mode != "RGB":
        im = im.convert("RGB")
    return im, source_profile


def _nclx_primaries(im: Image.Image):
    nclx = im.info.get("nclx_profile")
    if nclx is None:
        return None
    for attr in ("color_primaries", "colour_primaries"):
        if isinstance(nclx, dict) and attr in nclx:
            return nclx[attr]
        if hasattr(nclx, attr):
            return getattr(nclx, attr)
    return None


def _sips_to_png(path: str, workdir: str | None) -> str:
    d = workdir or tempfile.mkdtemp(prefix="dot-photo-")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "_decoded.png")
    try:
        subprocess.run(["sips", "-s", "format", "png", path, "--out", out],
                       check=True, capture_output=True, timeout=120)
    except Exception as e:
        raise DotPhotoError("HEIC_DECODE_FAILED", f"cannot decode {path}: {e}",
                            "convert the file first, e.g. `sips -s format png IN.HEIC --out IN.png`", 3)
    return out


# ---------------------------------------------------------------- load

def load(path: str, *, max_px: int | None = None, workdir: str | None = None) -> WorkImage:
    """Decode any supported file into a WorkImage. max_px>0 downsizes after decoding."""
    if not os.path.isfile(path):
        raise DotPhotoError("INPUT_NOT_FOUND", f"no such file: {path}", "", 3)
    suffix = os.path.splitext(path)[1].lower()
    warnings: list[str] = []
    exif = Image.Exif()
    orientation = 1
    source_profile = "untagged"
    bit_depth = 8
    fmt = suffix.lstrip(".")

    try:
        pil = Image.open(path)
    except Exception as e:
        if suffix in HEIC_SUFFIXES:
            warnings.append("pillow-heif could not decode; used sips")
            pil = Image.open(_sips_to_png(path, workdir))
        else:
            raise DotPhotoError("DECODE_FAILED", f"cannot decode {path}: {e}", "", 3)

    fmt = (pil.format or fmt).lower()
    try:
        exif = pil.getexif()
        orientation = int(exif.get(ORIENTATION, 1) or 1)
    except Exception:
        exif = Image.Exif()

    bits = None
    if suffix in TIFF_SUFFIXES or fmt == "tiff":
        try:
            bits = pil.tag_v2.get(258)
            bits = bits[0] if isinstance(bits, (tuple, list)) else bits
        except Exception:
            bits = None

    if bits == 16:
        # 16-bit TIFF: decode with OpenCV (Pillow has no 16-bit RGB mode)
        arr = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise DotPhotoError("DECODE_FAILED", f"cannot decode 16-bit TIFF {path}", "", 3)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=2)
        if arr.shape[2] == 4:
            arr = arr[..., :3]
        rgb = f32(arr[..., ::-1]) / 65535.0
        bit_depth = 16
        desc = profile_description(pil.info.get("icc_profile"))
        source_profile = desc or "untagged"
        if desc and not is_srgb_description(desc):
            warnings.append(f"16-bit TIFF tagged '{desc}' was treated as sRGB (no 16-bit conversion)")
        rgb = apply_orientation(rgb, orientation)
    else:
        pil, source_profile = _pil_to_srgb(pil, warnings)
        if source_profile == "untagged" and suffix in HEIC_SUFFIXES:
            prim = _nclx_primaries(pil)
            if prim == 12:
                source_profile = "Display P3 (nclx)"
        pil = ImageOps.exif_transpose(pil)
        rgb = f32(np.asarray(pil.convert("RGB"))) / 255.0
        if source_profile == "Display P3 (nclx)":
            rgb = p3_to_srgb(rgb)
            warnings.append("HEIC nclx Display P3 converted to sRGB")
        elif source_profile == "untagged" and suffix in HEIC_SUFFIXES:
            warnings.append("HEIC carries no color profile; treated as sRGB (phone originals are usually tagged P3)")

    # orientation is now baked into the pixels
    try:
        exif[ORIENTATION] = 1
    except Exception:
        pass

    original_size = [int(rgb.shape[1]), int(rgb.shape[0])]
    scale = 1.0
    if max_px and rgb.shape[0] * rgb.shape[1] > max_px:
        s = (max_px / (rgb.shape[0] * rgb.shape[1])) ** 0.5
        rgb = resize(rgb, max(1, round(rgb.shape[1] * s)), max(1, round(rgb.shape[0] * s)))
        scale = rgb.shape[1] / original_size[0]

    return WorkImage(
        rgb=rgb,
        exif=exif,
        source={
            "path": os.path.abspath(path),
            "format": fmt,
            "original_size": original_size,
            "orientation": orientation,
            "source_profile": source_profile,
            "bit_depth": bit_depth,
            "scale": scale,
            "warnings": warnings,
        },
    )


def downscale(img: WorkImage, max_px: int) -> tuple[WorkImage, float]:
    """Return (image, scale) with at most max_px pixels. scale = new / old width."""
    h, w = img.rgb.shape[:2]
    if max_px <= 0 or h * w <= max_px:
        return img, 1.0
    s = (max_px / (h * w)) ** 0.5
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    small = img.copy_with(resize(img.rgb, nw, nh))
    return small, nw / w


# ---------------------------------------------------------------- write

def to_uint8(rgb: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(f32(rgb) * 255.0), 0, 255).astype(np.uint8)


def to_uint16(rgb: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(f32(rgb) * 65535.0), 0, 65535).astype(np.uint16)


def exif_without_gps(exif: Image.Exif | None) -> Image.Exif:
    out = Image.Exif()
    if exif is None:
        return out
    try:
        out.load(exif.tobytes())
    except Exception:
        return out
    if GPS_IFD in out:
        try:
            del out[GPS_IFD]
        except Exception:
            pass
    try:
        out._ifds.pop(GPS_IFD, None)  # noqa: SLF001 - Pillow keeps parsed IFDs here
    except Exception:
        pass
    try:
        out[ORIENTATION] = 1
    except Exception:
        pass
    return out


def save_jpeg(rgb: np.ndarray, path: str, *, quality: int = 92, ppi: int | None = None,
              strip_exif: bool = False, strip_gps: bool = True, embed_srgb: bool = True,
              exif: Image.Exif | None = None, subsampling: int | str = "keep") -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im = Image.fromarray(to_uint8(rgb), "RGB")
    kwargs: dict = {"quality": int(quality), "optimize": True}
    if subsampling != "keep":
        kwargs["subsampling"] = subsampling
    if ppi:
        kwargs["dpi"] = (int(ppi), int(ppi))
    if embed_srgb:
        kwargs["icc_profile"] = SRGB_ICC_BYTES
    exif_stripped = True
    if not strip_exif and exif is not None:
        ex = exif_without_gps(exif) if strip_gps else exif
        try:
            b = ex.tobytes()
            if len(b) > 8:
                kwargs["exif"] = b
                exif_stripped = False
        except Exception:
            pass
    im.save(path, "JPEG", **kwargs)
    return {"path": os.path.abspath(path), "size": [im.width, im.height], "ppi": ppi,
            "quality": int(quality), "exif_stripped": exif_stripped, "icc": "sRGB" if embed_srgb else None}


def save_png(rgb_or_gray: np.ndarray, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    a = to_uint8(rgb_or_gray)
    Image.fromarray(a, "RGB" if a.ndim == 3 else "L").save(path, "PNG")
    return os.path.abspath(path)


def _tiff_entry(tag: int, typ: int, count: int, value_or_offset: int) -> bytes:
    return struct.pack("<HHII", tag, typ, count, value_or_offset)


def save_tiff16(rgb: np.ndarray, path: str, *, ppi: int = 300, icc: bytes | None = SRGB_ICC_BYTES) -> dict:
    """Write an uncompressed little-endian 16-bit RGB TIFF with resolution and an ICC tag."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = np.ascontiguousarray(to_uint16(rgb))
    h, w = data.shape[:2]
    pixels = data.tobytes()
    icc = icc or b""

    entries = []
    # layout: header(8) | IFD | extra values (bps, xres, yres, icc) | pixels
    n_entries = 13 + (1 if icc else 0)
    ifd_size = 2 + n_entries * 12 + 4
    extra_off = 8 + ifd_size
    bps_off = extra_off
    xres_off = bps_off + 6
    yres_off = xres_off + 8
    icc_off = yres_off + 8
    pix_off = icc_off + len(icc)
    if pix_off % 2:
        pix_off += 1

    entries.append(_tiff_entry(256, 4, 1, w))                 # ImageWidth
    entries.append(_tiff_entry(257, 4, 1, h))                 # ImageLength
    entries.append(_tiff_entry(258, 3, 3, bps_off))           # BitsPerSample
    entries.append(_tiff_entry(259, 3, 1, 1))                 # Compression = none
    entries.append(_tiff_entry(262, 3, 1, 2))                 # Photometric = RGB
    entries.append(_tiff_entry(273, 4, 1, pix_off))           # StripOffsets
    entries.append(_tiff_entry(277, 3, 1, 3))                 # SamplesPerPixel
    entries.append(_tiff_entry(278, 4, 1, h))                 # RowsPerStrip
    entries.append(_tiff_entry(279, 4, 1, len(pixels)))       # StripByteCounts
    entries.append(_tiff_entry(282, 5, 1, xres_off))          # XResolution
    entries.append(_tiff_entry(283, 5, 1, yres_off))          # YResolution
    entries.append(_tiff_entry(284, 3, 1, 1))                 # PlanarConfiguration = chunky
    entries.append(_tiff_entry(296, 3, 1, 2))                 # ResolutionUnit = inch
    if icc:
        entries.append(_tiff_entry(34675, 7, len(icc), icc_off))  # ICC profile
    entries.sort(key=lambda e: struct.unpack("<H", e[:2])[0])

    with open(path, "wb") as fh:
        fh.write(b"II*\x00" + struct.pack("<I", 8))
        fh.write(struct.pack("<H", len(entries)))
        for e in entries:
            fh.write(e)
        fh.write(struct.pack("<I", 0))
        fh.write(struct.pack("<HHH", 16, 16, 16))
        fh.write(struct.pack("<II", int(ppi), 1))
        fh.write(struct.pack("<II", int(ppi), 1))
        if icc:
            fh.write(icc)
        if fh.tell() < pix_off:
            fh.write(b"\x00" * (pix_off - fh.tell()))
        fh.write(pixels)
    return {"path": os.path.abspath(path), "size": [w, h], "ppi": ppi, "bit_depth": 16,
            "icc": "sRGB" if icc else None}


def default_out_dir(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(os.path.dirname(os.path.abspath(path)), f"{base}.dot-photo")
