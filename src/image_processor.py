"""长截图处理器：把超长图（如手机长截图）纵向切片后用 Gemini Vision 逐批 OCR，
完整提取文字并转为结构化 HTML。文字排在前，原始整图作为附件放在末尾。

为何切片：单张超长图直接送 Gemini 会被整体降采样到不可读，只能读到顶部一小段；
按高度切成多条窄片后，每片在模型内有足够分辨率，可覆盖全文。
"""
import base64
import os
from io import BytesIO
from typing import Any, Dict, List, Tuple

from PIL import Image

from utils.logger import logger
from document_processor import (
    _download_from_storage,
    _call_gemini_vision,
    _strip_code_fence,
    _html_to_plain,
)

# 切片参数
STRIP_HEIGHT = 1500   # 每片高度（px），保证文字清晰
OVERLAP = 100         # 相邻片重叠（px），避免边界处文字被截断
BATCH_SIZE = 8        # 每次 Gemini 调用处理的切片数

_OCR_PROMPT = """\
以下是同一张长截图从上到下的**连续切片**（相邻切片有少量重叠）。\
请将其中的文字内容**完整**转换为结构化 HTML 片段。

转换规则：
1. 文字必须完整保留，不得遗漏任何段落
2. 相邻切片重叠处的重复文字请**去重**，按自然阅读顺序拼接为连贯正文
3. 标题/小标题按视觉层级 → <h2>/<h3>；正文段落 → <p>
4. 加粗 → <b>；列表 → <ul><li> 或 <ol><li>；引用 → <blockquote>
5. 忽略状态栏、导航栏、点赞/评论按钮等截图里的界面元素
6. 图片/插图本身不要描述、不要转写其中的文字
7. 只输出正文 HTML 片段，不含 <html>/<body>，不要用 ```html``` 包裹
"""

_TITLE_PROMPT = """\
这是一张长截图的开头部分。如果开头有清晰可辨的文章标题/大标题，\
请只返回该标题的原文文字（不加引号、不加任何说明）；\
如果没有明确的标题，只返回一个减号 "-"。
"""


def _slice_image(img: Image.Image) -> List[Image.Image]:
    """按高度纵向切片，相邻片重叠 OVERLAP。"""
    w, h = img.size
    strips: List[Image.Image] = []
    y = 0
    while y < h:
        bottom = min(y + STRIP_HEIGHT, h)
        strips.append(img.crop((0, y, w, bottom)))
        if bottom >= h:
            break
        y += STRIP_HEIGHT - OVERLAP
    return strips


def _encode_jpeg_b64(img: Image.Image) -> str:
    buf = BytesIO()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _detect_title(first_strip: Image.Image) -> str:
    """识别截图开头的原始标题；无则返回空串。"""
    try:
        b64 = _encode_jpeg_b64(first_strip)
        raw = _call_gemini_vision(_TITLE_PROMPT, [("image/jpeg", b64)], timeout=60).strip()
        if raw in ("", "-", "—"):
            return ""
        return raw[:120]
    except Exception as e:
        logger.warning(f"标题识别失败: {e}")
        return ""


async def handle_image(article_id: str) -> Dict[str, Any]:
    media_storage_path = os.environ.get("MEDIA_STORAGE_PATH", "")
    if not media_storage_path:
        return {"article_id": article_id, "status": "error",
                "error_message": "MEDIA_STORAGE_PATH 未设置"}

    logger.info(f"下载长截图：{media_storage_path}")
    raw = _download_from_storage(media_storage_path)
    img = Image.open(BytesIO(raw))
    w, h = img.size
    logger.info(f"图片尺寸 {w}x{h}，开始切片")

    strips = _slice_image(img)
    logger.info(f"共 {len(strips)} 片，逐批 OCR")

    # 逐批 OCR
    html_parts: List[str] = []
    for start in range(0, len(strips), BATCH_SIZE):
        batch = strips[start:start + BATCH_SIZE]
        images: List[Tuple[str, str]] = [("image/jpeg", _encode_jpeg_b64(s)) for s in batch]
        logger.info(f"  OCR 第 {start + 1}–{start + len(batch)} / {len(strips)} 片")
        chunk = _strip_code_fence(_call_gemini_vision(_OCR_PROMPT, images, timeout=180))
        if chunk:
            html_parts.append(chunk)

    body_html = "\n".join(html_parts).strip()
    if not body_html:
        return {"article_id": article_id, "status": "error",
                "error_message": "未能从图片中提取到文字"}

    title = _detect_title(strips[0])
    plain_text = _html_to_plain(body_html)

    # 文字在前，原始整图作为附件占位符放末尾（插件端替换为 Vault 附件）
    content_md = f"{body_html}\n\n![[img_0.jpg]]"
    original_b64 = base64.b64encode(raw).decode()

    logger.info(f"完成：标题={title!r}，正文 {len(body_html)} chars，附件 {len(original_b64)} b64")

    return {
        "article_id": article_id,
        "status": "success",
        "title": title,
        "content_md": content_md,
        "content_text": plain_text[:4000],
        "article_images": {"img_0.jpg": original_b64},
    }
