"""长截图处理器（第二期：版面理解 + 图文穿插）

把超长图（如手机长截图）纵向切片后用 Gemini Vision 做**版面理解**：
按阅读顺序输出"文字块 / 图片块"，文字块转 HTML，图片块给出坐标。
我们据坐标从原图裁出子图，按位置穿插进正文，形成一篇图文；
末尾再附上完整原始长截图作为备份/对照。

为何切片：单张超长图直接送 Gemini 会被整体降采样到不可读，只能读到顶部一小段；
按高度切成窄片后，每片在模型内有足够分辨率，可覆盖全文并定位子图。
"""
import base64
import json
import re
from io import BytesIO
from typing import Any, Dict, List, Tuple

import os

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
OVERLAP = 80          # 相邻片重叠（px），便于模型在批内拼接、去重
BATCH_SIZE = 6        # 每次 Gemini 调用处理的切片数（同批内模型可去重拼接）
MIN_FIG_RATIO = 0.01  # 小于切片面积此比例的"图片块"视为噪声，丢弃
FIG_PAD = 6           # 裁剪时四周外扩像素，避免切边

_LAYOUT_PROMPT = """\
下面是同一张长截图从上到下的 {n} 张**连续切片**（编号 0 起，相邻切片有少量重叠）。
请理解整体版面，按**阅读顺序**输出一个 JSON：

{{"blocks": [
  {{"type": "text", "html": "<p>这一段正文…</p>"}},
  {{"type": "figure", "s": 切片编号, "box": [ymin, xmin, ymax, xmax]}},
  ...
]}}

规则：
1. "text"：属于文章正文流的标题/段落/列表/引用 → 转成 HTML 片段（<h2>/<h3>/<p>/<ul><li>/<blockquote>），文字完整保留。
2. "figure"：自成一体的**图片单元**——照片、插画、图表、信息图、表情包、截图里嵌的另一张截图/聊天记录/卡片。
   - 只输出它所在切片编号 s 和边界框 box；**不要转写图片内部的文字**（图内文字属于这张图）。
   - box 用该切片内的归一化坐标，范围 0–1000，顺序固定为 [ymin, xmin, ymax, xmax]。
3. 判据是"读者眼中是不是一张插入的图"，而非"有没有文字"。带底色的正文引用仍算 text；配图照片即使印着字也算 figure。
4. 相邻切片重叠处的重复内容请去重；忽略状态栏、导航栏、点赞/评论等界面元素。
5. 严格只输出 JSON，不要 ```包裹、不要任何解释。
"""

_TITLE_PROMPT = """\
这是一张长截图的开头部分。如果开头有清晰可辨的文章标题/大标题，\
请只返回该标题的原文文字（不加引号、不加任何说明）；\
如果没有明确的标题，只返回一个减号 "-"。
"""

# 批内解析失败时的降级：纯文字 OCR
_FALLBACK_OCR_PROMPT = """\
以下是同一张长截图的连续切片，请把其中文字完整转为 HTML 片段（<h2>/<h3>/<p>/<ul><li>），\
重叠处去重，忽略界面元素，只输出 HTML 片段，不要 ```包裹。
"""


def _slice_image(img: Image.Image) -> List[Tuple[Image.Image, int]]:
    """按高度纵向切片，返回 [(切片, 顶部y偏移), ...]，相邻片重叠 OVERLAP。"""
    w, h = img.size
    strips: List[Tuple[Image.Image, int]] = []
    y = 0
    while y < h:
        bottom = min(y + STRIP_HEIGHT, h)
        strips.append((img.crop((0, y, w, bottom)), y))
        if bottom >= h:
            break
        y += STRIP_HEIGHT - OVERLAP
    return strips


def _to_rgb(img: Image.Image) -> Image.Image:
    return img if img.mode in ("RGB", "L") else img.convert("RGB")


def _encode_jpeg_b64(img: Image.Image, quality: int = 85) -> str:
    buf = BytesIO()
    _to_rgb(img).save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def _parse_blocks(raw: str) -> List[Dict[str, Any]]:
    """从模型响应中提取 {"blocks":[...]}，失败返回 []。"""
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        blocks = data.get("blocks", [])
        return blocks if isinstance(blocks, list) else []
    except Exception:
        return []


def _crop_figure(strip: Image.Image, box: List[float]) -> Image.Image | None:
    """按归一化 box [ymin,xmin,ymax,xmax](0-1000) 从切片裁出子图，过小则返回 None。"""
    try:
        w, h = strip.size
        ymin, xmin, ymax, xmax = box[:4]
        x1 = max(0, int(xmin / 1000 * w) - FIG_PAD)
        y1 = max(0, int(ymin / 1000 * h) - FIG_PAD)
        x2 = min(w, int(xmax / 1000 * w) + FIG_PAD)
        y2 = min(h, int(ymax / 1000 * h) + FIG_PAD)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return None
        if (x2 - x1) * (y2 - y1) < MIN_FIG_RATIO * w * h:
            return None
        return strip.crop((x1, y1, x2, y2))
    except Exception:
        return None


def _detect_title(first_strip: Image.Image) -> str:
    try:
        raw = _call_gemini_vision(_TITLE_PROMPT, [("image/jpeg", _encode_jpeg_b64(first_strip))], timeout=60).strip()
        return "" if raw in ("", "-", "—") else raw[:120]
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
    logger.info(f"共 {len(strips)} 片，逐批做版面理解")

    parts: List[str] = []          # 按阅读顺序的 HTML 片段 / 图片占位符
    article_images: Dict[str, str] = {}
    fig_n = 0

    for start in range(0, len(strips), BATCH_SIZE):
        batch = strips[start:start + BATCH_SIZE]
        images = [("image/jpeg", _encode_jpeg_b64(s)) for s, _ in batch]
        logger.info(f"  版面理解 第 {start + 1}–{start + len(batch)} / {len(strips)} 片")
        try:
            raw_resp = _call_gemini_vision(_LAYOUT_PROMPT.format(n=len(batch)), images, timeout=180)
            blocks = _parse_blocks(raw_resp)
        except Exception as e:
            logger.warning(f"  批 {start} 版面理解失败，降级纯文字: {e}")
            blocks = []

        if not blocks:
            # 降级：整批做纯文字 OCR，保证不丢字
            try:
                fb = _strip_code_fence(_call_gemini_vision(_FALLBACK_OCR_PROMPT, images, timeout=180))
                if fb:
                    parts.append(fb)
            except Exception as e:
                logger.warning(f"  批 {start} 降级 OCR 也失败: {e}")
            continue

        for blk in blocks:
            btype = blk.get("type")
            if btype == "text":
                html = _strip_code_fence(str(blk.get("html", ""))).strip()
                if html:
                    parts.append(html)
            elif btype == "figure":
                s_local = blk.get("s", 0)
                box = blk.get("box")
                if not isinstance(box, list) or not (0 <= s_local < len(batch)):
                    continue
                crop = _crop_figure(batch[s_local][0], box)
                if crop is None:
                    continue
                key = f"fig_{fig_n}.jpg"
                article_images[key] = _encode_jpeg_b64(crop, quality=88)
                parts.append(f"![[{key}]]")
                fig_n += 1

    body_html = "\n\n".join(p for p in parts if p).strip()
    if not body_html:
        return {"article_id": article_id, "status": "error",
                "error_message": "未能从图片中提取到内容"}

    title = _detect_title(strips[0][0])
    plain_text = _html_to_plain(body_html)

    # 末尾保留完整原始长截图作为附件
    article_images["img_0.jpg"] = base64.b64encode(raw).decode()
    content_md = f"{body_html}\n\n![[img_0.jpg]]"

    logger.info(f"完成：标题={title!r}，子图 {fig_n} 张，正文 {len(body_html)} chars")

    return {
        "article_id": article_id,
        "status": "success",
        "title": title,
        "content_md": content_md,
        "content_text": plain_text[:4000],
        "article_images": article_images,
    }
