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

# Playwright 浏览器 UA（必须与 yt-dlp 使用的一致，否则 cookie 失效）
BROWSER_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'


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


async def _extract_bilibili_audio(url: str, download_dir: str) -> MediaMetadata:
    """
    用 Playwright 拦截 Bilibili 音频流 URL，再用 ffmpeg 下载

    绕过 yt-dlp 的 Bilibili extractor 412 问题。

    Args:
        url: Bilibili 视频 URL
        download_dir: 音频保存目录

    Returns:
        MediaMetadata

    Raises:
        RuntimeError: 提取失败
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("Playwright not available")

    logger.info(f"Extracting Bilibili audio via Playwright: {url}")
    audio_urls = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=BROWSER_USER_AGENT
        )
        page = await context.new_page()

        # 拦截网络请求，捕获音频流 URL
        def on_response(response):
            resp_url = response.url
            # B 站音频流特征：包含 /audio/ 或 mime=audio 或 30280（音频流标识）
            if any(kw in resp_url for kw in ('.m4s', '/audio/', 'mime=audio')):
                audio_urls.append(resp_url)

        page.on('response', on_response)

        # 访问视频页
        await page.goto(url, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(5000)

        # 提取标题和作者
        title = await page.title() or 'Untitled'
        # 清理标题（去掉 _哔哩哔哩_bilibili 后缀）
        title = re.sub(r'[_\-]\s*哔哩哔哩.*$', '', title).strip()

        author = None
        try:
            author_el = await page.query_selector('.up-name, .username, [class*="upname"]')
            if author_el:
                author = (await author_el.text_content() or '').strip()
        except Exception:
            pass

        # 获取 cookies 用于 ffmpeg 下载
        cookies = await context.cookies()
        cookie_header = '; '.join(f"{c['name']}={c['value']}" for c in cookies)

        await browser.close()

    if not audio_urls:
        raise RuntimeError("No audio stream URL found on Bilibili page")

    # 选取第一个音频流 URL
    audio_stream_url = audio_urls[0]
    logger.info(f"Found audio stream URL ({len(audio_urls)} total)")

    # 用 ffmpeg 下载音频流并转为 mp3
    # 生成安全的文件名
    safe_title = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', title)[:50]
    audio_path = os.path.join(download_dir, f'{safe_title}.mp3')

    logger.info(f"Downloading audio stream with ffmpeg...")
    try:
        result = subprocess.run(
            [
                'ffmpeg', '-y',
                '-headers', f'User-Agent: {BROWSER_USER_AGENT}\r\nReferer: https://www.bilibili.com\r\nCookie: {cookie_header}',
                '-i', audio_stream_url,
                '-vn',  # 无视频
                '-acodec', 'libmp3lame',
                '-q:a', '5',
                audio_path
            ],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg download timed out (5 min)")

    file_size = os.path.getsize(audio_path) / 1024 / 1024
    logger.info(f"✓ Audio downloaded: {audio_path} ({file_size:.1f} MB)")

    return MediaMetadata(
        title=title,
        author=author,
        duration=None,
        audio_path=audio_path
    )


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

    # Bilibili 走专用 Playwright 提取（绕过 yt-dlp 412 问题）
    if _needs_cookies(url):
        return await _extract_bilibili_audio(url, download_dir)

    # 其他平台用 yt-dlp
    output_template = os.path.join(download_dir, '%(id)s.%(ext)s')
    logger.info(f"Downloading audio with yt-dlp: {url}")
    try:
        import yt_dlp

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '5',
            }],
            'noplaylist': True,
            'nocheckcertificate': True,
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Untitled')
            author = info.get('uploader') or info.get('channel')
            duration = info.get('duration')

        logger.info(f"✓ yt-dlp download complete: {title}")

    except Exception as e:
        raise RuntimeError(f"yt-dlp failed: {e}")

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
