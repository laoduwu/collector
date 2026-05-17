"""视频处理全链路：字幕提取 / Whisper 转录 / 双语翻译 / 关键帧截图"""
import asyncio
import base64
import json
import os
import re
import struct
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import logger


# ────────────────────────────────────────────────
# B站 Playwright cookie
# ────────────────────────────────────────────────

async def _get_bilibili_cookies(url: str, cookies_file: str) -> None:
    """Playwright 访问 B 站视频页完成 JS 验证，导出 Netscape 格式 cookies.txt"""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        )
        page = await ctx.new_page()
        await page.goto(url, wait_until='networkidle', timeout=30000)
        await asyncio.sleep(3)
        cookies = await ctx.cookies()
        await browser.close()

    lines = ['# Netscape HTTP Cookie File']
    for c in cookies:
        domain = c['domain']
        flag = 'TRUE' if domain.startswith('.') else 'FALSE'
        secure = 'TRUE' if c.get('secure') else 'FALSE'
        expires = int(c.get('expires', 0)) if c.get('expires', -1) >= 0 else 0
        lines.append(
            f"{domain}\t{flag}\t{c['path']}\t{secure}\t{expires}"
            f"\t{c['name']}\t{c['value']}"
        )
    Path(cookies_file).write_text('\n'.join(lines), encoding='utf-8')
    logger.info(f'B站 cookies 已写入 {cookies_file}（{len(cookies)} 条）')


# ────────────────────────────────────────────────
# 字幕提取
# ────────────────────────────────────────────────

def _parse_vtt(vtt_path: str) -> List[Dict]:
    """解析 VTT 字幕文件，返回 [{start: float, text: str}]"""
    segments = []
    content = Path(vtt_path).read_text(encoding='utf-8')
    for block in re.split(r'\n\n+', content):
        lines = block.strip().splitlines()
        ts_line = next((l for l in lines if '-->' in l), None)
        if not ts_line:
            continue
        ts_part = ts_line.split('-->')[0].strip()
        m = re.match(r'(?:(\d+):)?(\d+):(\d+)\.(\d+)', ts_part)
        if not m:
            continue
        h, mn, s, ms = (int(x or 0) for x in m.groups())
        start = h * 3600 + mn * 60 + s + ms / 1000
        text_lines = [
            l for l in lines
            if '-->' not in l and l.strip()
            and not re.match(r'^\d+$', l.strip())
            and 'WEBVTT' not in l
        ]
        text = re.sub(r'<[^>]+>', '', ' '.join(text_lines)).strip()
        if text:
            segments.append({'start': start, 'text': text})
    return segments


def _extract_subtitles(
    url: str, tmpdir: str, cookies_file: Optional[str], is_bilibili: bool
) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """yt-dlp 下载字幕。返回 (segments, lang) 或 (None, None)"""
    sub_langs = 'zh,zh-Hans,zh-Hant,ai-zh' if is_bilibili else 'zh,zh-Hans,zh-Hant,en,en-US'
    out_template = os.path.join(tmpdir, 'subtitle')

    cmd = [
        'yt-dlp',
        '--write-subs', '--write-auto-subs', '--skip-download',
        '--sub-langs', sub_langs,
        '--sub-format', 'vtt',
        '--output', out_template,
        '--no-warnings', '--quiet',
    ]
    if cookies_file:
        cmd += ['--cookies', cookies_file]
    cmd.append(url)

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning(f'字幕下载失败: {e}')
        return None, None

    for lang_code in ['zh-Hans', 'zh', 'zh-Hant', 'ai-zh', 'en', 'en-US']:
        vtt_files = list(Path(tmpdir).glob(f'subtitle.{lang_code}*.vtt'))
        if vtt_files:
            segs = _parse_vtt(str(vtt_files[0]))
            if segs:
                lang = 'zh' if lang_code.startswith('zh') or lang_code == 'ai-zh' else 'en'
                logger.info(f'字幕提取成功：lang={lang}，{len(segs)} 段')
                return segs, lang

    return None, None


# ────────────────────────────────────────────────
# Groq Whisper 转录
# ────────────────────────────────────────────────

def _download_audio(url: str, tmpdir: str, cookies_file: Optional[str]) -> str:
    out_path = os.path.join(tmpdir, 'audio.mp3')
    cmd = [
        'yt-dlp', '--extract-audio', '--audio-format', 'mp3',
        '--audio-quality', '5', '--output', out_path,
        '--no-warnings', '--quiet',
    ]
    if cookies_file:
        cmd += ['--cookies', cookies_file]
    cmd.append(url)
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    logger.info(f'音频下载完成：{os.path.getsize(out_path) // 1024}KB')
    return out_path


def _whisper_file(client: Any, audio_path: str) -> Tuple[List[Dict], str]:
    with open(audio_path, 'rb') as f:
        result = client.audio.transcriptions.create(
            model='whisper-large-v3',
            file=f,
            response_format='verbose_json',
            timestamp_granularities=['segment'],
        )
    segs = [
        {
            'start': float(s['start'] if isinstance(s, dict) else s.start),
            'text': (s['text'] if isinstance(s, dict) else s.text).strip(),
        }
        for s in result.segments
    ]
    lang = getattr(result, 'language', None) or 'zh'
    return segs, lang


def _transcribe_audio(audio_path: str) -> Tuple[List[Dict], str]:
    """Groq Whisper 转录，不传 language 参数，自动检测语言"""
    from groq import Groq
    client = Groq(api_key=os.environ['GROQ_API_KEY'])

    max_bytes = 24 * 1024 * 1024
    if os.path.getsize(audio_path) <= max_bytes:
        segs, lang = _whisper_file(client, audio_path)
    else:
        segs, lang = _whisper_chunked(client, audio_path)

    logger.info(f'Whisper 转录完成：lang={lang}，{len(segs)} 段')
    return segs, lang


def _whisper_chunked(client: Any, audio_path: str) -> Tuple[List[Dict], str]:
    """超 24MB 音频按 20 分钟切段分别转录"""
    chunk_dir = audio_path + '_chunks'
    os.makedirs(chunk_dir, exist_ok=True)
    chunk_pattern = os.path.join(chunk_dir, 'chunk_%03d.mp3')

    subprocess.run([
        'ffmpeg', '-i', audio_path,
        '-f', 'segment', '-segment_time', '1200',
        '-c', 'copy', chunk_pattern,
    ], check=True, capture_output=True, timeout=300)

    all_segs: List[Dict] = []
    lang = 'zh'
    time_offset = 0.0

    for chunk in sorted(Path(chunk_dir).glob('chunk_*.mp3')):
        chunk_segs, detected = _whisper_file(client, str(chunk))
        if chunk_segs:
            lang = detected
        for s in chunk_segs:
            all_segs.append({'start': s['start'] + time_offset, 'text': s['text']})
        if chunk_segs:
            time_offset += chunk_segs[-1]['start'] + 5.0
    return all_segs, lang


# ────────────────────────────────────────────────
# 英文自然段分段 + 翻译
# ────────────────────────────────────────────────

def _segment_paragraphs(segments: List[Dict]) -> List[Dict]:
    """按停顿时长和句子结尾将 segments 合并成自然段落"""
    if not segments:
        return []

    paragraphs: List[Dict] = []
    cur_texts = [segments[0]['text']]
    cur_start = segments[0]['start']

    for i in range(1, len(segments)):
        prev, curr = segments[i - 1], segments[i]
        gap = curr['start'] - prev['start']
        ends_sent = bool(re.search(r'[.!?。！？]$', prev['text'].strip()))
        is_boundary = gap >= 2.0 or (ends_sent and gap >= 0.8)

        if is_boundary:
            paragraphs.append({'start': cur_start, 'texts': cur_texts})
            cur_texts = [curr['text']]
            cur_start = curr['start']
        else:
            cur_texts.append(curr['text'])

    paragraphs.append({'start': cur_start, 'texts': cur_texts})
    return paragraphs


def _call_gemini_json(prompt: str, timeout: int = 60) -> Any:
    """调用 Gemini，返回解析后的 JSON 对象；429 时最多重试 2 次"""
    import urllib.request
    import urllib.error
    import time
    api_key = os.environ['GEMINI_API_KEY']
    url = (
        f'https://generativelanguage.googleapis.com/v1beta/models/'
        f'gemini-2.5-flash:generateContent?key={api_key}'
    )
    body = json.dumps({
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'responseMimeType': 'application/json'},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            return json.loads(result['candidates'][0]['content']['parts'][0]['text'])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                wait = 10 * (attempt + 1)
                logger.warning(f'Gemini 429，{wait}s 后重试（第 {attempt + 1} 次）')
                time.sleep(wait)
            else:
                raise


def _call_minimax_json(prompt: str, timeout: int = 60) -> Any:
    """调用 MiniMax（OpenAI 兼容格式），返回解析后的 JSON 对象"""
    import urllib.request
    api_key = os.environ['MINIMAX_API_KEY']
    model = os.environ.get('MINIMAX_MODEL', 'MiniMax-M2')
    url = 'https://api.minimax.chat/v1/chat/completions'
    body = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.3,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
    content = result['choices'][0]['message']['content']
    if not content or not content.strip():
        raise ValueError('MiniMax 返回空内容')
    return json.loads(content)


def _call_groq_json(prompt: str, timeout: int = 60) -> Any:
    """调用 Groq（OpenAI 兼容），返回解析后的 JSON 对象"""
    import urllib.request
    api_key = os.environ['GROQ_API_KEY']
    url = 'https://api.groq.com/openai/v1/chat/completions'
    body = json.dumps({
        'model': 'llama-3.3-70b-versatile',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.3,
        'response_format': {'type': 'json_object'},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
    content = result['choices'][0]['message']['content']
    if not content or not content.strip():
        raise ValueError('Groq 返回空内容')
    return json.loads(content)


def _llm_json(prompt: str, timeout: int = 60) -> Any:
    """依次尝试 Gemini → Groq → MiniMax，返回第一个成功的 JSON 结果"""
    errors = []
    if os.environ.get('GEMINI_API_KEY'):
        try:
            return _call_gemini_json(prompt, timeout)
        except Exception as e:
            errors.append(f'Gemini: {e}')
            logger.warning(f'Gemini 调用失败，切换 Groq: {e}')
    if os.environ.get('GROQ_API_KEY'):
        try:
            return _call_groq_json(prompt, timeout)
        except Exception as e:
            errors.append(f'Groq: {e}')
            logger.warning(f'Groq 调用失败，切换 MiniMax: {e}')
    if os.environ.get('MINIMAX_API_KEY'):
        try:
            return _call_minimax_json(prompt, timeout)
        except Exception as e:
            errors.append(f'MiniMax: {e}')
    raise RuntimeError(f'所有 LLM 均失败: {"; ".join(errors)}')


def _translate_paragraphs(paragraphs: List[Dict]) -> List[str]:
    texts = [' '.join(p['texts']) for p in paragraphs]
    prompt = (
        'Translate the following English paragraphs to Chinese. '
        'Return a JSON array of strings, one translation per paragraph, preserving order. '
        'Output only the JSON array.\n\n'
        + json.dumps(texts, ensure_ascii=False)
    )
    result = _llm_json(prompt, timeout=90)
    if not isinstance(result, list):
        return [''] * len(paragraphs)
    return result


# ────────────────────────────────────────────────
# 关键帧识别
# ────────────────────────────────────────────────

def _identify_keyframes(transcript_text: str, video_duration_sec: float = 0) -> List[Dict]:
    """LLM 从转录文本识别值得截图的时刻；LLM 失败或返回空时均匀采样兜底"""
    prompt = (
        'You are analyzing a video transcript (may be in Chinese or English). '
        'Identify 3 to 7 moments that would benefit from a screenshot. '
        'Good candidates: diagrams, charts, code on screen, terminal output, UI demos, '
        'side-by-side comparisons, data/results being shown, or any moment where the '
        'speaker says "look at this", "watch here", "let\'s see", or equivalent in Chinese '
        '(e.g. "你看", "注意看", "咱们看看", "走，看效果"). '
        'Only return empty list for pure audio podcasts with absolutely no visual content.\n\n'
        'Return JSON: {"keyframes": [{"timestamp_seconds": <number>, "reason": "<why>"}]}\n\n'
        'Transcript:\n' + transcript_text[:12000]
    )
    try:
        data = _llm_json(prompt, timeout=90)
        kfs = data.get('keyframes', [])
        logger.info(f'关键帧识别：{len(kfs)} 个时刻')
        if kfs:
            return kfs
    except Exception as e:
        logger.warning(f'关键帧识别失败: {e}')

    # 兜底：按时长均匀采样 3 帧（视频时长已知时）
    if video_duration_sec > 30:
        count = 3
        step = video_duration_sec / (count + 1)
        fallback = [
            {'timestamp_seconds': round(step * (i + 1)), 'reason': 'uniform fallback'}
            for i in range(count)
        ]
        logger.info(f'均匀采样兜底：{len(fallback)} 帧（时长 {video_duration_sec:.0f}s）')
        return fallback
    return []


# ────────────────────────────────────────────────
# 微信视频号 Isaac64 解密
# ────────────────────────────────────────────────

_U64 = 0xFFFFFFFFFFFFFFFF
_GOLDEN = 0x9e3779b97f4a7c13


def _u64(x: int) -> int:
    return x & _U64


def _isaac64_mix(a, b, c, d, e, f, g, h):
    a = _u64(a - e); f = _u64(f ^ (h >> 9));  h = _u64(h + a)
    b = _u64(b - f); g = _u64(g ^ _u64(a << 9)); a = _u64(a + b)
    c = _u64(c - g); h = _u64(h ^ (b >> 23)); b = _u64(b + c)
    d = _u64(d - h); a = _u64(a ^ _u64(c << 15)); c = _u64(c + d)
    e = _u64(e - a); b = _u64(b ^ (d >> 14)); d = _u64(d + e)
    f = _u64(f - b); c = _u64(c ^ _u64(e << 20)); e = _u64(e + f)
    g = _u64(g - c); d = _u64(d ^ (f >> 17)); f = _u64(f + g)
    h = _u64(h - d); e = _u64(e ^ _u64(g << 14)); g = _u64(g + h)
    return a, b, c, d, e, f, g, h


class _RandCtx64:
    __slots__ = ('cnt', 'seed', 'mm', 'aa', 'bb', 'cc')

    def __init__(self):
        self.cnt = 255
        self.seed = [0] * 256
        self.mm = [0] * 256
        self.aa = self.bb = self.cc = 0

    def _step(self):
        self.cc = _u64(self.cc + 1)
        self.bb = _u64(self.bb + self.cc)
        for i in range(256):
            x = self.mm[i]
            m = i & 3
            if m == 0:
                self.aa = _u64(~_u64(self.aa ^ _u64(self.aa << 21)))
            elif m == 1:
                self.aa = _u64(self.aa ^ (self.aa >> 5))
            elif m == 2:
                self.aa = _u64(self.aa ^ _u64(self.aa << 12))
            else:
                self.aa = _u64(self.aa ^ (self.aa >> 33))
            self.aa = _u64(self.aa + self.mm[(i + 128) & 0xFF])
            y = _u64(self.mm[(x >> 3) & 0xFF] + self.aa + self.bb)
            self.mm[i] = y
            self.bb = _u64(self.mm[(y >> 11) & 0xFF] + x)
            self.seed[i] = self.bb

    def next(self) -> int:
        v = self.seed[self.cnt]
        if self.cnt == 0:
            self._step()
            self.cnt = 255
        else:
            self.cnt -= 1
        return v


def _make_isaac64(enc_key: int) -> _RandCtx64:
    ctx = _RandCtx64()
    ctx.seed[0] = _u64(enc_key)
    a = b = c = d = e = f = g = h = _GOLDEN
    for _ in range(4):
        a, b, c, d, e, f, g, h = _isaac64_mix(a, b, c, d, e, f, g, h)
    for i in range(0, 256, 8):
        a = _u64(a + ctx.seed[i]);   b = _u64(b + ctx.seed[i+1])
        c = _u64(c + ctx.seed[i+2]); d = _u64(d + ctx.seed[i+3])
        e = _u64(e + ctx.seed[i+4]); f = _u64(f + ctx.seed[i+5])
        g = _u64(g + ctx.seed[i+6]); h = _u64(h + ctx.seed[i+7])
        a, b, c, d, e, f, g, h = _isaac64_mix(a, b, c, d, e, f, g, h)
        ctx.mm[i:i+8] = [a, b, c, d, e, f, g, h]
    for i in range(0, 256, 8):
        a = _u64(a + ctx.mm[i]);   b = _u64(b + ctx.mm[i+1])
        c = _u64(c + ctx.mm[i+2]); d = _u64(d + ctx.mm[i+3])
        e = _u64(e + ctx.mm[i+4]); f = _u64(f + ctx.mm[i+5])
        g = _u64(g + ctx.mm[i+6]); h = _u64(h + ctx.mm[i+7])
        a, b, c, d, e, f, g, h = _isaac64_mix(a, b, c, d, e, f, g, h)
        ctx.mm[i:i+8] = [a, b, c, d, e, f, g, h]
    ctx._step()
    return ctx


def _decrypt_wechat_video(video_path: str, decode_key: int) -> None:
    """用 Isaac64 XOR 解密视频文件前 131072 字节（原地修改）"""
    ENC_LEN = 131072
    data = bytearray(Path(video_path).read_bytes())
    actual_enc = min(ENC_LEN, len(data))
    ctx = _make_isaac64(decode_key)
    i = 0
    while i < actual_enc:
        rand_val = ctx.next()
        key_bytes = struct.pack('>Q', rand_val)
        for j in range(8):
            idx = i + j
            if idx >= actual_enc:
                break
            data[idx] ^= key_bytes[j]
        i += 8
    Path(video_path).write_bytes(bytes(data))
    logger.info(f'Isaac64 解密完成: decode_key={decode_key}, 解密前 {actual_enc} 字节')


# ────────────────────────────────────────────────
# 微信视频号下载（三级降级）
# ────────────────────────────────────────────────

def _sph_to_preview_url(url: str) -> str:
    """将 weixin.qq.com/sph/XXX 短链转为 channels.weixin.qq.com/finder-preview 预览 URL"""
    import re
    m = re.search(r'/sph/([A-Za-z0-9]+)', url)
    if m:
        return f'https://channels.weixin.qq.com/finder-preview/pages/sph?id={m.group(1)}'
    return url


def _find_decode_key_in_json(obj: Any) -> Optional[int]:
    """递归搜索 JSON 对象中的 decodeKey / decode_key 字段"""
    if isinstance(obj, dict):
        for k in ('decodeKey', 'decode_key'):
            if k in obj:
                try:
                    return int(obj[k])
                except (ValueError, TypeError):
                    pass
        for v in obj.values():
            result = _find_decode_key_in_json(v)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_decode_key_in_json(item)
            if result is not None:
                return result
    return None


async def _intercept_wechat_video_url(page_url: str) -> Tuple[str, Optional[int]]:
    """
    Playwright 打开视频号 finder-preview 页。
    返回 (cdn_url, decode_key)，decode_key 可能为 None（若页面未通过 HTTP 暴露）。
    """
    from playwright.async_api import async_playwright
    video_url: Optional[str] = None
    decode_key: Optional[int] = None

    preview_url = _sph_to_preview_url(page_url)
    logger.info(f'Playwright 加载预览页: {preview_url}')

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            viewport={'width': 1280, 'height': 800},
        )

        def _is_video_cdn(u: str) -> bool:
            cdn_hosts = (
                'finder.video.qq.com',
                'finderoutside.video.qq.com',
                'wxapp.tc.qq.com',
                'vod2.myqcloud.com',
            )
            return any(h in u for h in cdn_hosts) and (
                '.mp4' in u or 'stodownload' in u or 'encfilekey' in u
            )

        async def on_request(request):
            nonlocal video_url
            if video_url:
                return
            if _is_video_cdn(request.url):
                logger.info(f'拦截到视频 CDN URL: {request.url[:80]}...')
                video_url = request.url

        async def on_response(response):
            nonlocal video_url, decode_key
            u = response.url
            ct = response.headers.get('content-type', '')

            # CDN 视频响应
            if not video_url and 'video' in ct and _is_video_cdn(u):
                logger.info(f'Response 拦截到视频: {u[:80]}...')
                video_url = u

            # WeChat API JSON 响应 → 搜寻 decodeKey
            if decode_key is None and 'json' in ct:
                weixin_domains = (
                    'channels.weixin.qq.com',
                    'res.wx.qq.com',
                    'finder.video.qq.com',
                    'mp.weixin.qq.com',
                )
                if any(d in u for d in weixin_domains):
                    try:
                        body = await response.body()
                        data = json.loads(body)
                        found = _find_decode_key_in_json(data)
                        if found is not None:
                            decode_key = found
                            logger.info(f'从 API 响应中获取 decode_key={decode_key}: {u[:60]}')
                    except Exception:
                        pass

        page = await ctx.new_page()
        page.on('request', on_request)
        page.on('response', on_response)
        try:
            await page.goto(preview_url, wait_until='domcontentloaded', timeout=30000)
            try:
                await page.wait_for_selector('video, .video-player, [class*="player"]', timeout=10000)
            except Exception:
                pass
            for selector in ['video', '.play-btn', '[class*="play"]', 'button']:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0:
                        await el.click(timeout=3000)
                        break
                except Exception:
                    pass
            # 等待 CDN URL 出现，同时继续收集 decodeKey
            for _ in range(12):
                if video_url and decode_key is not None:
                    break
                await asyncio.sleep(1)

            # 最后尝试从页面 JS 全局变量读取 decodeKey
            if decode_key is None:
                try:
                    val = await page.evaluate(
                        '(()=>{'
                        'const sources=['
                        'window.__INITIAL_STATE__,'
                        'window.__pinia,'
                        'window.__wechat_video_data__,'
                        '];'
                        'for(const s of sources){'
                        'if(!s)continue;'
                        'const str=JSON.stringify(s);'
                        'const m=str.match(/"(?:decodeKey|decode_key)"\s*:\s*"?(\d+)"?/);'
                        'if(m)return parseInt(m[1]);'
                        '}'
                        'return null;'
                        '})()'
                    )
                    if val:
                        decode_key = int(val)
                        logger.info(f'从页面 JS 全局变量获取 decode_key={decode_key}')
                except Exception:
                    pass
        finally:
            await browser.close()

    if not video_url:
        raise RuntimeError('Playwright 未拦截到视频 CDN URL（finder.video.qq.com）')

    if decode_key is None:
        logger.warning(
            'decode_key 未能从页面获取（WeChat 使用专有 WeixinJSBridge，'
            '普通浏览器无法访问）。将下载加密文件。'
        )
    return video_url, decode_key


def _is_valid_video(path: str) -> bool:
    """ffprobe 验证文件是有效视频（duration > 0）"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'json', path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False
        duration = float(json.loads(result.stdout).get('format', {}).get('duration', 0))
        return duration > 0
    except Exception:
        return False


async def _download_wechat_video(url: str, tmpdir: str) -> str:
    """
    微信视频号视频下载，三级降级：
    1. yt-dlp 直接下载（极少成功，通常为加密文件）
    2. Playwright 拦截 CDN URL + Isaac64 解密
    3. 报错
    返回已解密的有效视频文件路径。
    """
    out_path = os.path.join(tmpdir, 'wechat_source.mp4')

    # Level 1: yt-dlp 直接
    try:
        cmd = [
            'yt-dlp',
            '--format', 'best[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '--output', out_path,
            '--no-warnings', '--quiet',
            url,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        if os.path.exists(out_path) and _is_valid_video(out_path):
            logger.info(f'yt-dlp 下载视频号成功: {os.path.getsize(out_path) // 1024}KB')
            return out_path
        else:
            logger.warning('yt-dlp 下载内容无效（可能是加密文件），尝试 Playwright + 解密')
    except Exception as e:
        logger.warning(f'yt-dlp 下载视频号失败，尝试 Playwright: {e}')

    # Level 2: Playwright 拦截 CDN URL + Isaac64 解密
    try:
        cdn_url, decode_key = await _intercept_wechat_video_url(url)

        # 用 curl 直接下载（避免 yt-dlp 对 CDN URL 的二次处理）
        curl_cmd = [
            'curl', '-L', '-s', '--max-time', '300',
            '-H', 'Referer: https://channels.weixin.qq.com/',
            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            '-o', out_path,
            cdn_url,
        ]
        subprocess.run(curl_cmd, check=True, capture_output=True, timeout=330)

        if not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
            raise RuntimeError('curl 下载文件为空或过小')

        file_size_kb = os.path.getsize(out_path) // 1024
        logger.info(f'CDN 下载完成: {file_size_kb}KB')

        # 若拿到 decode_key，尝试 Isaac64 解密
        if decode_key is not None:
            _decrypt_wechat_video(out_path, decode_key)
            if _is_valid_video(out_path):
                logger.info(f'Isaac64 解密后验证通过: {file_size_kb}KB')
                return out_path
            else:
                logger.warning('Isaac64 解密后 ffprobe 仍验证失败，decode_key 可能不正确')
        else:
            # 没有 decode_key：直接检查（极低概率是未加密）
            if _is_valid_video(out_path):
                logger.info(f'文件未加密，直接可用: {file_size_kb}KB')
                return out_path
            raise RuntimeError(
                '视频文件已加密（需要 decode_key），但无法从页面获取。'
                '微信视频号加密通过专有 WeixinJSBridge 传递密钥，'
                '在无 WeChat 客户端的环境中无法解密。'
            )
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning(f'Playwright 拦截下载失败: {e}')

    raise RuntimeError(
        '微信视频号视频下载失败（yt-dlp 和 Playwright + Isaac64 均无法获取），'
        '该视频已加密，需要 WeChat 客户端才能获取解密密钥'
    )


def _extract_audio_from_video(video_path: str, tmpdir: str) -> str:
    """从视频文件提取音频（mp3），供 Whisper 转录"""
    audio_path = os.path.join(tmpdir, 'audio.mp3')
    subprocess.run([
        'ffmpeg', '-i', video_path,
        '-vn', '-ar', '16000', '-ac', '1', '-b:a', '64k',
        '-y', audio_path,
    ], check=True, capture_output=True, timeout=300)
    logger.info(f'音频提取完成: {os.path.getsize(audio_path) // 1024}KB')
    return audio_path


# ────────────────────────────────────────────────
# 视频下载 + 帧提取 + Vision 选帧
# ────────────────────────────────────────────────

def _download_video(url: str, tmpdir: str, cookies_file: Optional[str]) -> str:
    out_path = os.path.join(tmpdir, 'video.mp4')
    cmd = [
        'yt-dlp',
        '--format', 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
        '--merge-output-format', 'mp4',
        '--output', out_path,
        '--no-warnings', '--quiet',
    ]
    if cookies_file:
        cmd += ['--cookies', cookies_file]
    cmd.append(url)
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    logger.info(f'视频下载完成：{os.path.getsize(out_path) // (1024*1024)}MB')
    return out_path


def _extract_candidate_frames(
    video_path: str, timestamp_sec: float, tmpdir: str, idx: int
) -> List[str]:
    start = max(0.0, timestamp_sec - 2.0)
    frame_dir = os.path.join(tmpdir, f'frames_{idx}')
    os.makedirs(frame_dir, exist_ok=True)
    out_pattern = os.path.join(frame_dir, 'frame_%03d.jpg')

    subprocess.run([
        'ffmpeg', '-ss', str(start), '-i', video_path,
        '-t', '4', '-vf', 'fps=1', '-q:v', '2', out_pattern,
    ], check=True, capture_output=True, timeout=30)

    return sorted(str(p) for p in Path(frame_dir).glob('frame_*.jpg'))


def _select_best_frame(frame_paths: List[str], transcript_snippet: str) -> Optional[str]:
    """从候选帧选信息量最大的一帧，依次尝试 Gemini Vision → MiniMax Vision"""
    if not frame_paths:
        return None

    prompt_text = (
        f'These are {len(frame_paths)} consecutive frames from a video. '
        f'Transcript at this moment: "{transcript_snippet}". '
        'Which frame has the most informational visual content (diagrams, charts, '
        'UI screenshots, or text on screen)? '
        'Reply with JSON: {"selected_index": <0-based index>}'
    )
    frame_b64 = [base64.b64encode(Path(fp).read_bytes()).decode() for fp in frame_paths]

    sel = None
    errors = []

    if os.environ.get('GEMINI_API_KEY'):
        try:
            import urllib.request
            parts: List[Dict] = []
            for b64 in frame_b64:
                parts.append({'inline_data': {'mime_type': 'image/jpeg', 'data': b64}})
            parts.append({'text': prompt_text})
            api_key = os.environ['GEMINI_API_KEY']
            url = (
                f'https://generativelanguage.googleapis.com/v1beta/models/'
                f'gemini-2.5-flash:generateContent?key={api_key}'
            )
            body = json.dumps({
                'contents': [{'parts': parts}],
                'generationConfig': {'responseMimeType': 'application/json'},
            }).encode()
            req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            raw = result['candidates'][0]['content']['parts'][0]['text']
            sel = json.loads(raw).get('selected_index', 0)
        except Exception as e:
            errors.append(f'Gemini Vision: {e}')
            logger.warning(f'Gemini Vision 失败，切换 MiniMax: {e}')

    if sel is None and os.environ.get('MINIMAX_API_KEY'):
        try:
            import urllib.request
            content_parts: List[Dict] = []
            for b64 in frame_b64:
                content_parts.append({
                    'type': 'image_url',
                    'image_url': {'url': f'data:image/jpeg;base64,{b64}'},
                })
            content_parts.append({'type': 'text', 'text': prompt_text})
            model = os.environ.get('MINIMAX_MODEL', 'MiniMax-M2')
            body = json.dumps({
                'model': model,
                'messages': [{'role': 'user', 'content': content_parts}],
            }).encode()
            req = urllib.request.Request(
                'https://api.minimax.chat/v1/chat/completions',
                data=body,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {os.environ["MINIMAX_API_KEY"]}',
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
            raw = result['choices'][0]['message']['content']
            sel = json.loads(raw).get('selected_index', 0)
        except Exception as e:
            errors.append(f'MiniMax Vision: {e}')

    if sel is None:
        logger.warning(f'Vision 选帧全部失败，取中间帧: {"; ".join(errors)}')
        sel = len(frame_paths) // 2

    sel = max(0, min(sel, len(frame_paths) - 1))
    return frame_paths[sel]


# ────────────────────────────────────────────────
# content_md 拼装
# ────────────────────────────────────────────────

def _fmt_ts(sec: float) -> str:
    m, s = int(sec) // 60, int(sec) % 60
    return f'{m:02d}:{s:02d}'


def _build_content_md(
    paragraphs: List[Dict],
    lang: str,
    translations: Optional[List[str]],
    keyframe_para_map: Dict[int, str],
    article_id: str,
) -> str:
    """
    拼装最终 Markdown。
    keyframe_para_map: {para_idx → frame_filename}，frame_filename 格式为 frame_{t}s.jpg（不含 article_id）。
    content_md 中引用的文件名加上 article_id 前缀，与 file-writer.ts 写入的磁盘文件名一致。
    """
    lines: List[str] = []
    for i, para in enumerate(paragraphs):
        ts = _fmt_ts(para['start'])
        text = ' '.join(para['texts'])

        if lang == 'en' and translations and i < len(translations):
            lines.append(f'[{ts}] {text}')
            lines.append('')
            lines.append(translations[i])
        else:
            lines.append(f'[{ts}] {text}')

        if i in keyframe_para_map:
            filename = f'{article_id}_{keyframe_para_map[i]}'
            lines.append('')
            lines.append(f'![[{filename}]]')

        lines.append('')

    return '\n'.join(lines).strip()


# ────────────────────────────────────────────────
# 视频压缩 + Storage 上传
# ────────────────────────────────────────────────

def _upload_to_storage(video_path: str, article_id: str) -> str:
    """上传视频到 Supabase Storage，返回 storage_path"""
    import urllib.request
    supabase_url = os.environ['SUPABASE_URL']
    service_key = os.environ['SUPABASE_SERVICE_ROLE_KEY']
    storage_path = f'videos/{article_id}.mp4'
    upload_url = f'{supabase_url}/storage/v1/object/media-temp/{storage_path}'

    file_size = os.path.getsize(video_path)
    logger.info(f'上传视频到 Storage: {file_size // (1024*1024)}MB → {storage_path}')

    with open(video_path, 'rb') as f:
        video_bytes = f.read()

    req = urllib.request.Request(
        upload_url,
        data=video_bytes,
        headers={
            'Authorization': f'Bearer {service_key}',
            'Content-Type': 'video/mp4',
            'x-upsert': 'true',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        resp.read()
    logger.info(f'Storage 上传完成: {storage_path}')
    return storage_path


def _compress_and_upload_video(source_video: str, article_id: str, tmpdir: str) -> str:
    """
    压缩视频至 ≤50MB，上传 Supabase Storage，返回 storage_path。
    若压缩后仍超限则截取前 N 秒直到达标。
    """
    # 获取时长
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', source_video],
        capture_output=True, text=True, timeout=30, check=True,
    )
    duration_sec = float(json.loads(result.stdout)['format']['duration'])

    MAX_MB = 48  # 留 2MB 余量应对容器开销，避免卡在 Storage 50MB 上限边缘
    # 目标总码率（视频 + 音频 64kbps），上限 1500kbps
    target_kbps = min(int(MAX_MB * 8 * 1024 / max(duration_sec, 1)) - 64, 1500)
    target_kbps = max(target_kbps, 100)  # 最低 100kbps，保证可用

    compressed_path = os.path.join(tmpdir, 'compressed.mp4')
    subprocess.run([
        'ffmpeg', '-i', source_video,
        '-b:v', f'{target_kbps}k',
        '-b:a', '64k',
        '-vf', 'scale=-2:min(480\\,ih)',
        '-movflags', '+faststart',
        '-y', compressed_path,
    ], check=True, capture_output=True, timeout=600)

    actual_mb = os.path.getsize(compressed_path) / (1024 * 1024)
    logger.info(f'压缩完成: {actual_mb:.1f}MB（{target_kbps}kbps，时长 {duration_sec:.0f}s）')

    # 兜底：仍超限 → 用实际码率计算可容纳秒数（截取至 90% 安全余量）
    if actual_mb > MAX_MB:
        actual_total_kbps = (os.path.getsize(compressed_path) * 8) / (duration_sec * 1000)
        safe_sec = int(MAX_MB * 8 * 1024 * 0.90 / actual_total_kbps)
        safe_sec = max(safe_sec, 30)  # 至少保留 30 秒
        logger.warning(f'压缩后仍超限，截取前 {safe_sec}s（实际码率 {actual_total_kbps:.0f}kbps）')
        trimmed_path = os.path.join(tmpdir, 'trimmed.mp4')
        subprocess.run([
            'ffmpeg', '-i', compressed_path,
            '-t', str(safe_sec),
            '-c', 'copy', '-y', trimmed_path,
        ], check=True, capture_output=True, timeout=120)
        compressed_path = trimmed_path

    return _upload_to_storage(compressed_path, article_id)


# ────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────

async def handle_video(
    article_id: str, source_url: str, content_type: str
) -> Dict[str, Any]:
    """
    视频处理全链路。
    content_type: 'youtube' | 'bilibili' | 'wechat_video'
    """
    import tempfile
    is_bilibili = content_type == 'bilibili'
    is_wechat = content_type == 'wechat_video'
    save_video = os.environ.get('SAVE_VIDEO', '').lower() in ('true', '1', 'yes')
    tmpdir = tempfile.mkdtemp(prefix='rocvideo_')
    cookies_file: Optional[str] = None

    try:
        # 1. B站：Playwright 获取 cookies
        if is_bilibili:
            cookies_file = os.path.join(tmpdir, 'cookies.txt')
            await _get_bilibili_cookies(source_url, cookies_file)

        # 2. 字幕提取（视频号无官方字幕，直接跳过）
        segments: List[Dict] = []
        lang: Optional[str] = None
        if not is_wechat:
            segments, lang = _extract_subtitles(source_url, tmpdir, cookies_file, is_bilibili)

        # 3. 无字幕时的转录路径
        wechat_video_path: Optional[str] = None
        if not segments:
            logger.info('无可用字幕，启动 Whisper 转录')
            if is_wechat:
                # 视频号：先下载视频，再提取音频
                wechat_video_path = await _download_wechat_video(source_url, tmpdir)
                audio_path = _extract_audio_from_video(wechat_video_path, tmpdir)
            else:
                audio_path = _download_audio(source_url, tmpdir, cookies_file)
            segments, lang = _transcribe_audio(audio_path)

        if not segments:
            return {
                'article_id': article_id,
                'status': 'error',
                'error_message': '字幕提取和 Whisper 转录均失败，无法获取内容',
            }

        lang = lang or 'zh'

        # 4. 段落化
        paragraphs = _segment_paragraphs(segments)

        # 5. 英文视频：翻译
        translations: Optional[List[str]] = None
        if lang == 'en':
            logger.info('英文视频，开始段落翻译')
            translations = _translate_paragraphs(paragraphs)

        # 6. 关键帧识别
        full_text = ' '.join(s['text'] for s in segments)
        video_duration_sec = segments[-1]['start'] if segments else 0
        keyframes = _identify_keyframes(full_text, video_duration_sec)

        # 7. 视频下载 + 帧提取 + Vision 选帧
        article_images: Dict[str, str] = {}
        keyframe_para_map: Dict[int, str] = {}
        downloaded_video_path: Optional[str] = wechat_video_path  # 视频号已下载则复用

        if keyframes:
            logger.info(f'开始提取 {len(keyframes)} 个关键帧')
            try:
                if downloaded_video_path is None:
                    downloaded_video_path = _download_video(source_url, tmpdir, cookies_file)
                for kf_idx, kf in enumerate(keyframes):
                    t = float(kf['timestamp_seconds'])
                    try:
                        candidate_frames = _extract_candidate_frames(
                            downloaded_video_path, t, tmpdir, kf_idx
                        )
                        if not candidate_frames:
                            continue
                        nearest_para = min(paragraphs, key=lambda p: abs(p['start'] - t))
                        snippet = ' '.join(nearest_para['texts'])[:200]
                        best_frame = _select_best_frame(candidate_frames, snippet)
                        if not best_frame:
                            continue
                        frame_name = f'frame_{int(t)}s.jpg'
                        article_images[frame_name] = base64.b64encode(
                            Path(best_frame).read_bytes()
                        ).decode()
                        para_idx = min(
                            range(len(paragraphs)),
                            key=lambda i: abs(paragraphs[i]['start'] - t),
                        )
                        keyframe_para_map[para_idx] = frame_name
                    except Exception as e:
                        logger.warning(f'关键帧 {kf_idx} 处理失败（跳过）: {e}')
            except Exception as e:
                logger.warning(f'视频下载/帧提取失败，跳过关键帧: {e}')

        # 8. 拼装 content_md
        content_md = _build_content_md(
            paragraphs, lang, translations, keyframe_para_map, article_id
        )

        # 9. 保存原始视频（可选）
        video_storage_path: Optional[str] = None
        if save_video:
            try:
                source_for_save = downloaded_video_path
                if source_for_save is None:
                    # keyframes 未触发下载，单独为 save_video 下载
                    if is_wechat:
                        source_for_save = await _download_wechat_video(source_url, tmpdir)
                    else:
                        source_for_save = _download_video(source_url, tmpdir, cookies_file)
                video_storage_path = _compress_and_upload_video(
                    source_for_save, article_id, tmpdir
                )
                logger.info(f'视频保存完成: {video_storage_path}')
            except Exception as e:
                logger.warning(f'视频保存失败（不影响转录结果）: {e}')

        platform = '视频号' if is_wechat else ('B站' if is_bilibili else 'YouTube')
        title = f'{platform} 视频转录'

        payload: Dict[str, Any] = {
            'article_id': article_id,
            'status': 'success',
            'title': title,
            'content_md': content_md,
            'content_text': full_text[:4000],
            'article_images': article_images or None,
        }
        if video_storage_path:
            payload['video_storage_path'] = video_storage_path
        return payload

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
