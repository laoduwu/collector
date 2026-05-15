"""GitHub Actions 入口 - 抓取并回调 Supabase

文章正文采用 HTML 直存方案：保留微信内联 CSS 排版（居中图注、引用、
分割线、列表样式等），图片以 base64 data URI 内联到 <img src>，
Obsidian 阅读视图直接渲染，不依赖附件路径。
"""
import asyncio
import base64
import os
import re
import traceback
from typing import Any, Dict

from bs4 import BeautifulSoup

from utils.logger import logger
from utils.callback import post_callback
from scrapers.image_downloader import download_to_bytes

try:
    from scrapers.playwright_scraper import PlaywrightScraper
except Exception as _e:  # pragma: no cover - 仅在缺依赖时触发
    PlaywrightScraper = None  # type: ignore[assignment]
    _playwright_import_error = _e
else:
    _playwright_import_error = None


WECHAT_REFERER = "https://mp.weixin.qq.com/"

# 微信图片懒加载：真实地址在 data-src，src 是 1x1 占位 SVG
_LAZY_ATTRS = ('data-src', 'data-original', 'data-actualsrc', 'data-backsrc')

_MIME_BY_EXT = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
}


def _guess_mime(filename: str) -> str:
    ext = filename[filename.rfind('.'):].lower() if '.' in filename else ''
    return _MIME_BY_EXT.get(ext, 'image/jpeg')


def _clean_html(html: str) -> str:
    """清洗微信正文 HTML：
    1. 懒加载 data-src 提升为 src
    2. 删除 script/style/iframe 等无用/危险标签（保留元素 style 属性）
    3. 图片下载并以 base64 data URI 内联（Obsidian 渲染稳定，自包含）
    """
    soup = BeautifulSoup(html, 'html.parser')

    for img in soup.find_all('img'):
        real = next((img.get(a) for a in _LAZY_ATTRS if img.get(a)), None)
        if real:
            img['src'] = real
        for a in _LAZY_ATTRS:
            if img.has_attr(a):
                del img[a]

    for tag in soup.find_all(['script', 'style', 'iframe', 'noscript']):
        tag.decompose()

    for img in soup.find_all('img'):
        src = img.get('src', '')
        if not src.startswith('http'):
            continue
        try:
            referer = WECHAT_REFERER if 'mmbiz' in src else None
            fname, raw = download_to_bytes(src, referer=referer)
            mime = _guess_mime(fname)
            b64 = base64.b64encode(raw).decode('ascii')
            img['src'] = f'data:{mime};base64,{b64}'
        except Exception as e:
            logger.warning(f"图片内联失败，保留原链接 {src}: {e}")

    return str(soup)


def _html_to_text(html: str) -> str:
    """从 HTML 提取纯文本，供 AI 分类（节省 token、避免标签干扰）。"""
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text(separator='\n', strip=True)


async def _handle_article(article_id: str, source_url: str) -> Dict[str, Any]:
    if PlaywrightScraper is None:
        raise RuntimeError(
            f"PlaywrightScraper 不可用: {_playwright_import_error}"
        )
    scraper = PlaywrightScraper(headless=True)
    article = await scraper.scrape(source_url)

    if getattr(article, 'content_html', None):
        html = _clean_html(article.content_html)
        text = _html_to_text(html)
    else:
        html = f"<p>{article.content}</p>"
        text = article.content

    return {
        "article_id": article_id,
        "status": "success",
        "title": article.title,
        "author": getattr(article, "author", None),
        "content_md": html,
        "content_text": text[:4000],
    }


async def _handle_youtube(article_id: str, source_url: str) -> Dict[str, Any]:
    from youtube_transcript_api import YouTubeTranscriptApi

    m = re.search(r"(?:v=|youtu\.be/)([^&\s]+)", source_url)
    if not m:
        raise ValueError("无法解析 YouTube 视频 ID")
    video_id = m.group(1)

    try:
        items = YouTubeTranscriptApi.get_transcript(
            video_id, languages=['zh-Hans', 'zh', 'en']
        )
    except Exception as e:
        raise RuntimeError(f"该视频暂无字幕：{e}")

    body = "\n".join(
        f"[{int(it['start'])//60:02d}:{int(it['start'])%60:02d}] {it['text']}"
        for it in items
    )
    content = f"## 视频转录\n\n{body}"

    return {
        "article_id": article_id,
        "status": "success",
        "title": f"YouTube · {video_id}",
        "content_md": content,
        "content_text": body[:4000],
    }


async def run() -> None:
    article_id = os.environ["ARTICLE_ID"]
    source_url = os.environ["SOURCE_URL"]
    content_type = os.environ["CONTENT_TYPE"]

    logger.info(f"Start scraping article_id={article_id} type={content_type}")

    try:
        if content_type == "article":
            payload = await _handle_article(article_id, source_url)
        elif content_type == "youtube":
            payload = await _handle_youtube(article_id, source_url)
        else:
            raise ValueError(f"不支持的 content_type: {content_type}")
    except Exception as e:
        logger.error(f"抓取失败: {e}\n{traceback.format_exc()}")
        payload = {
            "article_id": article_id,
            "status": "error",
            "error_message": str(e),
        }

    post_callback(payload)
    logger.info("Callback posted; done.")


if __name__ == "__main__":
    asyncio.run(run())
