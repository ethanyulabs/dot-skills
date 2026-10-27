"""report.json assembly and the needs_review catalogue."""
from __future__ import annotations

import json
import os
import time

from . import __version__

REVIEW_TEXT = {
    "NO_FACE": ("未检测到人脸", "看 compare.jpg 确认；人像可用 --face x,y,w,h 指定脸框，或接受全图肤色蒙版"),
    "MULTI_FACE": ("检测到多张脸且未指定 --face", "默认全部处理；如只修主体，用 --face N 选第 N 大的脸"),
    "SKIN_LOW_COVERAGE": ("肤色蒙版覆盖率过低，可能漏检", "看 compare.jpg 下排；必要时 --face 指定或降低 --skin-strength"),
    "SKIN_HIGH_COVERAGE": ("肤色蒙版覆盖率过高，可能把背景当皮肤", "看 compare.jpg 整图是否有背景被柔化；可 --face 限定"),
    "TEXTURE_RETAINED_LOW": ("皮肤高频纹理保留比偏低，可能出现塑料感", "看 100% 裁块；把 --skin-strength 降 0.15 重跑"),
    "BLEMISH_COUNT_HIGH": ("瑕疵检测数量很多，可能把纹理当瑕疵", "看 100% 裁块；可 --blemish off 或降低强度"),
    "CLIP_HIGH": ("黑白点裁切掉的像素超过 1%", "检查高光/阴影是否死白死黑；可调 --black / --white 百分位"),
    "HALO_RISK": ("天际线附近梯度增幅过大，可能有光晕", "降低 --clahe 或 --far-clarity，看 compare.jpg 天际线"),
    "STYLE_LOW_CONFIDENCE": ("风格反推整体置信度低", "向用户说明哪些字段不可靠，不要擅自补数"),
    "DATING_FACE_TOO_SMALL": ("交友版输出中脸部占比过小", "原图脸太小或太靠边；考虑换图或手动裁切"),
    "PRINT_UPSCALE_HIGH": ("打印版需要放大原图超过 1.5 倍，近看会偏软", "换更大的纸型以外的原片，或改小纸型（--paper 5x7 / 4x6）"),
    "DATING_UPSCALE_HIGH": ("交友版需要放大原图超过 1.67 倍，会损失清晰度", "原图分辨率偏低；尽量用更高分辨率的原片"),
    "LARGE_IMAGE_DOWNSCALED": ("图片过大，处理前已缩小", "打印 8x10@300ppi 仍够；如需全尺寸请加 --max-process-px 0 并确保内存"),
    "TYPE_UNCERTAIN": ("照片类型判定不确定", "按 info 的 suggested_type 执行并向用户确认，或用 --type 指定"),
    "GUIDED_FILTER_FALLBACK": ("cv2.ximgproc 不可用，使用了 numpy 引导滤波", "结果等价但更慢；可重装 opencv-contrib-python-headless"),
}


def review(code: str, detail: str = "", suggest: str | None = None) -> dict:
    msg, sug = REVIEW_TEXT.get(code, (code, ""))
    if detail:
        msg = f"{msg}（{detail}）"
    return {"code": code, "message": msg, "suggest": suggest or sug}


class Timer:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.marks: dict[str, int] = {}
        self._last = self.t0

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        self.marks[name] = self.marks.get(name, 0) + int((now - self._last) * 1000)
        self._last = now

    def total(self) -> dict:
        out = dict(self.marks)
        out["total"] = int((time.perf_counter() - self.t0) * 1000)
        return out


def build(action: str, input_path: str, out_dir: str, *, artifacts: dict, summary: dict,
          warnings: list, needs_review: list, timing: dict, extra: dict | None = None) -> tuple[dict, dict]:
    """Returns (stdout_json, report_json). The report carries the bulky extra sections."""
    base = {
        "ok": True, "action": action, "version": __version__,
        "input": os.path.abspath(input_path) if input_path else None,
        "out_dir": os.path.abspath(out_dir) if out_dir else None,
        "artifacts": artifacts, "summary": summary, "warnings": warnings,
        "needs_review": needs_review, "timing_ms": timing,
    }
    report = dict(base)
    if extra:
        report.update(extra)
    return base, report


def write(report: dict, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, default=_default)
    return os.path.abspath(path)


def _default(o):
    try:
        import numpy as np
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:  # pragma: no cover
        pass
    return str(o)
