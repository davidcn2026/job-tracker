"""图片预处理：让任意截图都能被视觉模型处理。

模型硬限制：
    HTTP 400 "its width and height must each be at most 8192 pixels"

实测结论：
    1080x2400   ✅ 正常识别
    1080x6000   ✅ 正常识别，底部内容也能读到
    1080x12000  ❌ 400，高度超过 8192

所以策略是「按需处理」——**大多数手机截图根本不需要动**：
    两边都 <= 8192            → 原样发送（不重编码，不掉质量）
    高度超限（超长截图）        → 垂直切片，**保持原分辨率**，绝不缩小
    宽度超限（极少见）          → 按比例缩小到 8192 宽

为什么超长图必须切片而不是缩小：
    1080x6000 缩到 1080x1500，文字高度从 28px 变成 7px，直接糊掉无法识别。
    切片则每片都是原分辨率，文字清晰，代价是多调几次模型。
"""

from __future__ import annotations

import io

from PIL import Image

# 模型硬限制（来自 400 错误信息）
MODEL_MAX_SIDE = 8192

# 单片高度：留出余量，避免刚好卡在边界上
SLICE_HEIGHT = 7000

# 相邻切片重叠像素：防止一行文字正好被切在两片之间
SLICE_OVERLAP = 120

# 切片重编码质量：92 对文字截图足够，再高只是白增体积
JPEG_QUALITY = 92


def prepare_images(data: bytes, mime: str) -> list[tuple[bytes, str]]:
    """把原始图片变成「模型能接受的 1~N 张图」。

    返回 [(bytes, mime), ...]：
      - 只有一张时，尽量返回原始字节（不重编码，保质量）
      - 多张时全部是 JPEG（Pillow 重编码）
    """
    with Image.open(io.BytesIO(data)) as img:
        width, height = img.size

        # 快路径：尺寸合规就直接用原图，一次编码都不做
        if width <= MODEL_MAX_SIDE and height <= MODEL_MAX_SIDE:
            return [(data, mime)]

        rgb = img.convert("RGB")

        # 宽度超限：横图极少见，等比缩小是可接受的妥协
        if width > MODEL_MAX_SIDE:
            ratio = MODEL_MAX_SIDE / width
            rgb = rgb.resize(
                (MODEL_MAX_SIDE, max(1, round(height * ratio))),
                Image.LANCZOS,
            )
            width, height = rgb.size

        # 缩完还是不高，就直接用
        if height <= MODEL_MAX_SIDE:
            return [(_encode(rgb), "image/jpeg")]

        # 超长：垂直切片，每片保持原始分辨率
        slices: list[tuple[bytes, str]] = []
        top = 0
        while top < height:
            bottom = min(top + SLICE_HEIGHT, height)
            slices.append((_encode(rgb.crop((0, top, width, bottom))), "image/jpeg"))
            if bottom >= height:
                break
            top = bottom - SLICE_OVERLAP

        return slices


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()
