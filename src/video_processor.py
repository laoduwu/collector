"""视频处理全链路：字幕提取 / Whisper 转录 / 双语翻译 / 关键帧截图"""
import asyncio
import base64
import json
import os
import re
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
    segs = [{'start': float(s.start), 'text': s.text.strip()} for s in result.segments]
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
    """调用 Gemini，返回解析后的 JSON 对象"""
    import urllib.request
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
    return json.loads(result['candidates'][0]['content']['parts'][0]['text'])


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
    return json.loads(result['choices'][0]['message']['content'])


def _llm_json(prompt: str, timeout: int = 60) -> Any:
    """依次尝试 Gemini → MiniMax，返回第一个成功的 JSON 结果"""
    errors = []
    if os.environ.get('GEMINI_API_KEY'):
        try:
            return _call_gemini_json(prompt, timeout)
        except Exception as e:
            errors.append(f'Gemini: {e}')
            logger.warning(f'Gemini 调用失败，切换 MiniMax: {e}')
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

def _identify_keyframes(transcript_text: str) -> List[Dict]:
    """LLM 从转录文本识别 3-7 个值得截图的语义时刻"""
    prompt = (
        'You are analyzing a video transcript. Identify 3 to 7 moments that '
        'benefit from a screenshot because they show a diagram, chart, process flow, '
        'UI interface, or visual comparison. For talking-head videos with no such '
        'visual content, return an empty list.\n\n'
        'Return JSON: {"keyframes": [{"timestamp_seconds": <number>, "reason": "<why>"}]}\n\n'
        'Transcript (first 8000 chars):\n' + transcript_text[:8000]
    )
    try:
        data = _llm_json(prompt, timeout=60)
        kfs = data.get('keyframes', [])
        logger.info(f'关键帧识别：{len(kfs)} 个时刻')
        return kfs
    except Exception as e:
        logger.warning(f'关键帧识别失败: {e}')
        return []


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
# 主入口
# ────────────────────────────────────────────────

async def handle_video(
    article_id: str, source_url: str, content_type: str
) -> Dict[str, Any]:
    """
    视频处理全链路。返回 actions-callback 所需的 payload dict。
    content_type: 'youtube' | 'bilibili'
    """
    import tempfile
    is_bilibili = content_type == 'bilibili'
    tmpdir = tempfile.mkdtemp(prefix='rocvideo_')
    cookies_file: Optional[str] = None

    try:
        # 1. B站：Playwright 获取 cookies
        if is_bilibili:
            cookies_file = os.path.join(tmpdir, 'cookies.txt')
            await _get_bilibili_cookies(source_url, cookies_file)

        # 2. 字幕提取
        segments, lang = _extract_subtitles(source_url, tmpdir, cookies_file, is_bilibili)

        # 3. 无字幕 → 下载音频 + Whisper
        if not segments:
            logger.info('无可用字幕，启动 Whisper 转录')
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
        keyframes = _identify_keyframes(full_text)

        # 7. 视频下载 + 帧提取 + Vision 选帧
        article_images: Dict[str, str] = {}
        keyframe_para_map: Dict[int, str] = {}

        if keyframes:
            logger.info(f'开始视频下载，提取 {len(keyframes)} 个关键帧')
            try:
                video_path = _download_video(source_url, tmpdir, cookies_file)
                for kf_idx, kf in enumerate(keyframes):
                    t = float(kf['timestamp_seconds'])
                    try:
                        candidate_frames = _extract_candidate_frames(video_path, t, tmpdir, kf_idx)
                        if not candidate_frames:
                            continue

                        # 找最近的段落片段作为 Vision 提示
                        nearest_para = min(
                            paragraphs, key=lambda p: abs(p['start'] - t)
                        )
                        snippet = ' '.join(nearest_para['texts'])[:200]

                        best_frame = _select_best_frame(candidate_frames, snippet)
                        if not best_frame:
                            continue

                        frame_name = f'frame_{int(t)}s.jpg'  # article_images key（不含 article_id）
                        article_images[frame_name] = base64.b64encode(
                            Path(best_frame).read_bytes()
                        ).decode()

                        # 确定插入的段落位置（最近段落的索引）
                        para_idx = min(
                            range(len(paragraphs)),
                            key=lambda i: abs(paragraphs[i]['start'] - t),
                        )
                        keyframe_para_map[para_idx] = frame_name

                    except Exception as e:
                        logger.warning(f'关键帧 {kf_idx} 处理失败（跳过）: {e}')

            except Exception as e:
                logger.warning(f'视频下载失败，跳过全部关键帧: {e}')

        # 8. 拼装 content_md
        content_md = _build_content_md(
            paragraphs, lang, translations, keyframe_para_map, article_id
        )

        platform = 'B站' if is_bilibili else 'YouTube'
        title = f'{platform} 视频转录'

        return {
            'article_id': article_id,
            'status': 'success',
            'title': title,
            'content_md': content_md,
            'content_text': full_text[:4000],
            'article_images': article_images or None,
        }

    finally:
        # 清理临时目录
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
