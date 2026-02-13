"""媒体处理模块 - 视频/音频/播客转录"""
import os
import re
import tempfile
import subprocess
from dataclasses import dataclass
from typing import Optional, List, Tuple
from urllib.parse import urlparse

import requests

from utils.logger import logger
from utils.config import config


# 已知媒体平台域名
MEDIA_DOMAINS = {
    # 视频平台
    'youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com',
    'bilibili.com', 'www.bilibili.com', 'b23.tv',
    # 播客平台
    'podcasts.apple.com', 'soundcloud.com', 'open.spotify.com',
    'music.163.com', 'ximalaya.com', 'www.ximalaya.com',
    'podcasts.google.com', 'overcast.fm', 'pocket.casts',
    # 其他音视频平台
    'vimeo.com', 'dailymotion.com', 'twitch.tv',
}

# 需要解析重定向的短链域名
SHORT_LINK_DOMAINS = {'b23.tv'}

# 需要通过 Playwright 获取 cookies 的域名（反爬严格）
COOKIE_REQUIRED_DOMAINS = {'bilibili.com', 'www.bilibili.com'}


@dataclass
class MediaMetadata:
    """媒体元数据"""
    title: str
    author: Optional[str]
    duration: Optional[float]  # 秒
    audio_path: str  # 本地音频文件路径


@dataclass
class TranscriptSegment:
    """转录文本段落"""
    start: float  # 开始时间（秒）
    end: float  # 结束时间（秒）
    text: str


def resolve_short_link(url: str) -> str:
    """
    解析短链重定向，返回最终 URL

    Args:
        url: 可能是短链的 URL

    Returns:
        解析后的真实 URL（如果不是短链则原样返回）
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        if hostname not in SHORT_LINK_DOMAINS:
            return url

        logger.info(f"Resolving short link: {url}")
        resp = requests.head(url, allow_redirects=True, timeout=10)
        resolved = resp.url
        logger.info(f"Resolved to: {resolved}")
        return resolved
    except Exception as e:
        logger.warning(f"Failed to resolve short link {url}: {e}")
        return url


def _needs_cookies(url: str) -> bool:
    """检查 URL 是否需要通过浏览器获取 cookies"""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        bare_host = hostname.removeprefix('www.')
        return hostname in COOKIE_REQUIRED_DOMAINS or bare_host in COOKIE_REQUIRED_DOMAINS
    except Exception:
        return False


async def _fetch_cookies_with_playwright(url: str) -> Optional[str]:
    """
    用 Playwright 访问页面，完成 JS 验证后导出 Netscape cookies.txt

    Args:
        url: 需要访问的页面 URL

    Returns:
        cookies.txt 文件路径，失败返回 None
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not available, cannot fetch cookies")
        return None

    cookies_path = os.path.join(config.DOWNLOADS_DIR, 'media', 'cookies.txt')
    os.makedirs(os.path.dirname(cookies_path), exist_ok=True)

    logger.info(f"Fetching cookies via Playwright: {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            await page.goto(url, wait_until='networkidle', timeout=30000)
            # 等待 JS 验证完成
            await page.wait_for_timeout(3000)

            cookies = await context.cookies()
            await browser.close()

        if not cookies:
            logger.warning("No cookies obtained from Playwright")
            return None

        # 写入 Netscape cookies.txt 格式
        with open(cookies_path, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")
            for c in cookies:
                domain = c.get('domain', '')
                include_subdomains = 'TRUE' if domain.startswith('.') else 'FALSE'
                path = c.get('path', '/')
                secure = 'TRUE' if c.get('secure', False) else 'FALSE'
                expires = str(int(c.get('expires', 0)))
                name = c.get('name', '')
                value = c.get('value', '')
                f.write(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")

        logger.info(f"Cookies saved: {cookies_path} ({len(cookies)} cookies)")
        return cookies_path

    except Exception as e:
        logger.warning(f"Failed to fetch cookies with Playwright: {e}")
        return None


def is_media_url(url: str) -> bool:
    """
    检测 URL 是否为视频/音频平台

    先通过域名快速匹配，不匹配则用 yt-dlp --simulate 尝试。

    Args:
        url: 待检测的 URL

    Returns:
        是否为媒体 URL
    """
    # 先解析短链
    url = resolve_short_link(url)

    # 快速域名匹配
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ''
        # 去掉 www. 前缀后再匹配
        bare_host = hostname.removeprefix('www.')
        if hostname in MEDIA_DOMAINS or bare_host in MEDIA_DOMAINS:
            logger.info(f"URL matched as media by domain: {hostname}")
            return True
    except Exception:
        pass

    # yt-dlp simulate 检测
    try:
        result = subprocess.run(
            ['yt-dlp', '--simulate', '--no-warnings', '-q', url],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            logger.info(f"URL matched as media by yt-dlp simulate: {url}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return False


async def extract_audio(url: str) -> MediaMetadata:
    """
    用 yt-dlp 下载音频并提取元数据

    对需要 cookies 的站点（如 Bilibili），先用 Playwright 获取 cookies。

    Args:
        url: 媒体 URL

    Returns:
        MediaMetadata 包含音频路径和元数据

    Raises:
        RuntimeError: 下载失败
    """
    # 解析短链
    url = resolve_short_link(url)

    # 确保下载目录存在
    download_dir = os.path.join(config.DOWNLOADS_DIR, 'media')
    os.makedirs(download_dir, exist_ok=True)

    output_template = os.path.join(download_dir, '%(id)s.%(ext)s')

    # 如果需要 cookies，先用 Playwright 获取
    cookies_args = []
    if _needs_cookies(url):
        logger.info("Site requires cookies, fetching via Playwright...")
        cookies_path = await _fetch_cookies_with_playwright(url)
        if cookies_path:
            cookies_args = ['--cookies', cookies_path]
        else:
            logger.warning("Failed to obtain cookies, trying without...")

    # 先提取元数据
    logger.info(f"Extracting media metadata: {url}")
    try:
        meta_cmd = [
            'yt-dlp',
            '--no-download',
            '--print', '%(title)s\n%(uploader)s\n%(duration)s',
            '--no-warnings',
            '--no-check-certificates',
            *cookies_args,
            url
        ]
        meta_result = subprocess.run(
            meta_cmd, capture_output=True, text=True, timeout=30
        )
        meta_lines = meta_result.stdout.strip().split('\n')
        title = meta_lines[0] if len(meta_lines) > 0 and meta_lines[0] != 'NA' else 'Untitled'
        author = meta_lines[1] if len(meta_lines) > 1 and meta_lines[1] != 'NA' else None
        duration_str = meta_lines[2] if len(meta_lines) > 2 else None
        duration = float(duration_str) if duration_str and duration_str != 'NA' else None
    except Exception as e:
        logger.warning(f"Failed to extract metadata: {e}")
        title = 'Untitled'
        author = None
        duration = None

    # 下载音频（提取为 mp3）
    logger.info(f"Downloading audio: {url}")
    try:
        download_cmd = [
            'yt-dlp',
            '-x',  # 只提取音频
            '--audio-format', 'mp3',
            '--audio-quality', '5',  # 中等质量，减小文件
            '-o', output_template,
            '--no-warnings',
            '--no-check-certificates',
            '--no-playlist',  # 不下载播放列表
            *cookies_args,
            url
        ]
        result = subprocess.run(
            download_cmd, capture_output=True, text=True, timeout=600
        )

        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    except subprocess.TimeoutExpired:
        raise RuntimeError("Audio download timed out (10 min)")

    # 清理 cookies 文件
    cookies_file = os.path.join(download_dir, 'cookies.txt')
    if os.path.exists(cookies_file):
        os.remove(cookies_file)

    # 查找下载的文件
    audio_files = [
        f for f in os.listdir(download_dir)
        if f.endswith('.mp3')
    ]

    if not audio_files:
        raise RuntimeError("No audio file found after download")

    # 取最新的文件
    audio_path = os.path.join(
        download_dir,
        max(audio_files, key=lambda f: os.path.getmtime(os.path.join(download_dir, f)))
    )

    logger.info(f"Audio downloaded: {audio_path} ({os.path.getsize(audio_path) / 1024 / 1024:.1f} MB)")

    return MediaMetadata(
        title=title,
        author=author,
        duration=duration,
        audio_path=audio_path
    )


def transcribe_audio(audio_path: str) -> List[TranscriptSegment]:
    """
    用 faster-whisper 转录音频

    Args:
        audio_path: 本地音频文件路径

    Returns:
        转录文本段落列表

    Raises:
        RuntimeError: 转录失败
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper not installed. Run: pip install faster-whisper")

    logger.info(f"Loading Whisper model (base)...")
    model = WhisperModel("base", device="cpu", compute_type="int8")

    logger.info(f"Transcribing audio: {audio_path}")
    segments_iter, info = model.transcribe(
        audio_path,
        beam_size=5,
        language=None,  # 自动检测语言
        vad_filter=True,  # VAD过滤静音段
    )

    logger.info(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")

    segments = []
    for segment in segments_iter:
        segments.append(TranscriptSegment(
            start=segment.start,
            end=segment.end,
            text=segment.text.strip()
        ))

    logger.info(f"Transcription complete: {len(segments)} segments")
    return segments


def segments_to_text(segments: List[TranscriptSegment]) -> str:
    """
    将转录段落合并为原始文本

    Args:
        segments: 转录段落列表

    Returns:
        合并后的纯文本
    """
    return '\n'.join(seg.text for seg in segments if seg.text)


def cleanup_media_files(audio_path: str) -> None:
    """清理下载的媒体文件"""
    try:
        if os.path.exists(audio_path):
            os.remove(audio_path)
            logger.info(f"Cleaned up media file: {audio_path}")
    except OSError as e:
        logger.warning(f"Failed to cleanup media file: {e}")
