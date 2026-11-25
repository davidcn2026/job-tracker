"""简历文本提取：PDF / DOCX / 纯文本 / 图片。

设计取舍：
  1. **只取文本，不存原始文件** —— 原件在用户手里，分析真正需要的是文本。
  2. **扫描版 PDF 不做转换** —— 把 PDF 页面转成图片要装 poppler（几百 MB），
     而"图片识别"这条路我们已经有了。所以遇到扫描件就明确告诉用户改用截图。
  3. **图片走视觉模型** —— 复用截图识别那套 call_llm_vision。
"""

from __future__ import annotations

import io

from app.services.llm import LLMError, extract_resume_from_image

# 低于这个字数就认为"没提取到有效内容"（扫描件、或纯图片排版）
MIN_RESUME_CHARS = 30


class ResumeError(Exception):
    """简历解析失败。service 层不抛 HTTPException，由 router 翻译成 422。"""


def extract_resume_text(data: bytes, filename: str, mime: str) -> str:
    """同步解析 PDF / DOCX / 纯文本。图片请走 extract_resume_text_async。"""
    if not data:
        raise ResumeError("文件内容为空")

    if mime == "application/pdf" or filename.lower().endswith(".pdf"):
        return _from_pdf(data)

    if filename.lower().endswith(".docx") or mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return _from_docx(data)

    if mime.startswith("text/") or filename.lower().endswith((".txt", ".md")):
        try:
            return _clean(data.decode("utf-8"))
        except UnicodeDecodeError:
            return _clean(data.decode("gbk", errors="replace"))

    raise ResumeError(
        f"不支持的文件类型：{filename or mime}。请上传 PDF / DOCX / TXT，或直接粘贴文本"
    )


def is_image(mime: str, filename: str) -> bool:
    return mime.startswith("image/") or filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".webp")
    )


async def extract_resume_text_async(data: bytes, filename: str, mime: str) -> str:
    """图片简历（拍照 / 截图）走视觉模型；其它格式走本地解析。"""
    if is_image(mime, filename):
        try:
            text = await extract_resume_from_image(data, mime or "image/jpeg")
        except LLMError as e:
            raise ResumeError(f"图片简历识别失败：{e}") from e
        return _require_text(_clean(text))

    return extract_resume_text(data, filename, mime)


# ---------- 各格式实现 ----------


def _from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as e:
        raise ResumeError(f"PDF 解析失败：{e}") from e

    text = _clean("\n".join(pages))
    if len(text) < MIN_RESUME_CHARS:
        raise ResumeError(
            "这份 PDF 里提取不到文字，很可能是扫描件（把纸质简历扫描/拍照后存成的 PDF）。"
            "请改用图片上传，或直接把简历文字粘贴进来。"
        )
    return text


def _from_docx(data: bytes) -> str:
    try:
        from docx import Document

        document = Document(io.BytesIO(data))
    except Exception as e:
        raise ResumeError(f"DOCX 解析失败：{e}") from e

    parts = [p.text for p in document.paragraphs]

    # 简历模板大量使用表格排版，只取 paragraphs 会漏掉大半内容
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)

    return _require_text(_clean("\n".join(parts)))


def _require_text(text: str) -> str:
    if len(text) < MIN_RESUME_CHARS:
        raise ResumeError("简历内容太少（不足 30 字），请检查文件是否正常，或直接粘贴文本")
    return text


def _clean(text: str) -> str:
    """压缩多余空行：PDF 提取经常产出大量空白行，浪费提示词长度。"""
    lines = [line.strip() for line in text.splitlines()]
    kept: list[str] = []
    for line in lines:
        if line or (kept and kept[-1]):
            kept.append(line)
    return "\n".join(kept).strip()
