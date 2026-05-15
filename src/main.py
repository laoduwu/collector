"""GitHub Actions 入口 - 抓取并回调 Supabase"""
import asyncio
import base64
import os
import re
import traceback
from typing import Any, Dict

from utils.logger import logger
from utils.callback import post_callback
from scrapers.image_downloader import download_to_bytes
from markdownify import markdownify as html_to_md

try:
    from scrapers.playwright_scraper import PlaywrightScraper
except Exception as _e:  # pragma: no cover - 仅在缺依赖时触发
    PlaywrightScraper = None  # type: ignore[assignment]
    _playwright_import_error = _e
else:
    _playwright_import_error = None


WECHAT_REFERER = "https://mp.weixin.qq.com/"


def _replace_image_urls_with_filenames(
    content: str,
    url_to_filename: Dict[str, str],
) -> str:
    """把正文里的图片 URL 替换为 Obsidian 内部链接 ![[文件名]]。"""
    for url, fname in url_to_filename.items():
        content = re.sub(
            re.escape(url),
            f'![[{fname}]]',
            content,
        )
    return content


async def _handle_article(article_id: str, source_url: str) -> Dict[str, Any]:
    if PlaywrightScraper is None:
        raise RuntimeError(
            f"PlaywrightScraper 不可用: {_playwright_import_error}"
        )
    scraper = PlaywrightScraper(headless=True)
    article = await scraper.scrape(source_url)

    images_b64: Dict[str, str] = {}
    url_to_filename: Dict[str, str] = {}
    for img_url in article.images or []:
        try:
            referer = WECHAT_REFERER if 'mmbiz.qpic.cn' in img_url else None
            fname, raw = download_to_bytes(img_url, referer=referer)
            base_fname = fname
            i = 1
            while fname in images_b64:
                stem, _, ext = base_fname.rpartition('.')
                fname = f"{stem}_{i}.{ext}"
                i += 1
            images_b64[fname] = base64.b64encode(raw).decode('ascii')
            url_to_filename[img_url] = fname
        except Exception as e:
            logger.warning(f"图片下载失败，跳过 {img_url}: {e}")

    # 优先使用 HTML 抓取并转 Markdown（保留代码块、引用、加粗等格式）
    raw_md = (
        html_to_md(article.content_html, heading_style='ATX', bullets='-')
        if getattr(article, 'content_html', None)
        else article.content
    )
    content = _replace_image_urls_with_filenames(raw_md, url_to_filename)

    return {
        "article_id": article_id,
        "status": "success",
        "title": article.title,
        "author": getattr(article, "author", None),
        "content_md": content,
        "article_images": images_b64,
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

    return {
        "article_id": article_id,
        "status": "success",
        "title": f"YouTube · {video_id}",
        "content_md": f"## 视频转录\n\n{body}",
        "article_images": {},
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
