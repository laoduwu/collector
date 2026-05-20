"""文档处理器：PDF/DOCX/PPTX/TXT/MD 提取、摘要、双语翻译、HTML 组装"""
import json
import os
from io import BytesIO
from typing import Any, Dict, Tuple

import requests

from utils.logger import logger
from video_processor import _llm_json, _translate_paragraphs


# ─── Storage 下载 ───────────────────────────────────────────

def _download_from_storage(storage_path: str) -> bytes:
    """从 Supabase Storage media-temp bucket 下载文件"""
    supabase_url = os.environ['SUPABASE_URL']
    service_key = os.environ['SUPABASE_SERVICE_ROLE_KEY']
    url = f'{supabase_url}/storage/v1/object/media-temp/{storage_path}'
    resp = requests.get(url, headers={'Authorization': f'Bearer {service_key}'}, timeout=60)
    resp.raise_for_status()
    return resp.content


# ─── 文字提取 ────────────────────────────────────────────────

def _extract_pdf(raw: bytes) -> Tuple[str, str]:
    import fitz  # pymupdf
    doc = fitz.open(stream=raw, filetype='pdf')
    title = (doc.metadata or {}).get('title', '') or ''
    pages = [page.get_text().strip() for page in doc if page.get_text().strip()]
    return '\n\n'.join(pages), title


def _extract_docx(raw: bytes) -> Tuple[str, str]:
    from docx import Document
    doc = Document(BytesIO(raw))
    title = (doc.core_properties.title or '').strip()
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return '\n\n'.join(paragraphs), title


def _extract_pptx(raw: bytes) -> Tuple[str, str]:
    from pptx import Presentation
    prs = Presentation(BytesIO(raw))
    title = (prs.core_properties.title or '').strip()
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = para.text.strip()
                    if t:
                        parts.append(t)
        if parts:
            slides.append(f'[幻灯片 {i}]\n' + '\n'.join(parts))
    return '\n\n'.join(slides), title


def _extract_text_file(raw: bytes) -> Tuple[str, str]:
    text = raw.decode('utf-8', errors='replace')
    # 取首行作为标题（去掉 Markdown # 前缀，最多 80 字符）
    first_line = text.split('\n')[0].strip().lstrip('#').strip()
    title = first_line[:80] if first_line else ''
    return text, title


def _extract_text(raw: bytes, ext: str) -> Tuple[str, str]:
    """返回 (全文纯文字, 标题)"""
    if ext == 'pdf':
        return _extract_pdf(raw)
    elif ext == 'docx':
        return _extract_docx(raw)
    elif ext == 'pptx':
        return _extract_pptx(raw)
    elif ext in ('txt', 'md'):
        return _extract_text_file(raw)
    else:
        raise ValueError(f'不支持的格式：.{ext}')


# ─── 语言检测 ────────────────────────────────────────────────

def _detect_english(text: str) -> bool:
    """非 ASCII 字符（主要为中文）占比 < 40% 则判定为英文文档"""
    sample = text[:2000]
    if not sample:
        return False
    non_ascii = sum(1 for c in sample if ord(c) > 127)
    return (non_ascii / len(sample)) < 0.4


# ─── HTML 组装 ───────────────────────────────────────────────

def _paragraphs_to_html(text: str) -> str:
    """将纯文本按空行分段，包裹为 <p> 标签"""
    paras = [p.strip() for p in text.split('\n\n') if p.strip()]
    return ''.join(f'<p>{p}</p>' for p in paras)


def _bilingual_html(text: str) -> str:
    """英文文档：每段原文下紧跟中文译文"""
    raw_paras = [p.strip() for p in text.split('\n\n') if p.strip()]
    if not raw_paras:
        return ''

    # 构造 _translate_paragraphs 期望的格式 [{start, texts}]
    fake_paras = [{'start': i, 'texts': [p]} for i, p in enumerate(raw_paras)]

    try:
        translations = _translate_paragraphs(fake_paras)
    except Exception as e:
        logger.warning(f'批量翻译失败，降级为原文: {e}')
        translations = [''] * len(raw_paras)

    parts = []
    for orig, zh in zip(raw_paras, translations):
        parts.append(f'<p lang="en">{orig}</p>')
        if zh:
            parts.append(f'<p lang="zh">{zh}</p>')
    return ''.join(parts)


def _build_summary_html(text: str) -> str:
    """调用 LLM 生成中文摘要与核心要点，返回 HTML 片段"""
    prompt = (
        '请为以下文档生成中文摘要与核心要点。'
        '返回 JSON 格式：{"summary": "一段话摘要", "key_points": ["要点1", "要点2", ...]}\n\n'
        f'文档内容（前 6000 字）：\n{text[:6000]}'
    )
    try:
        data = _llm_json(prompt, timeout=90)
        summary = data.get('summary', '')
        key_points = data.get('key_points', [])
    except Exception as e:
        logger.warning(f'摘要生成失败: {e}')
        return '<p>（摘要生成失败）</p>'

    points_html = ''.join(f'<li>{p}</li>' for p in key_points) if key_points else ''
    return (
        f'<p>{summary}</p>'
        + (f'<ul>{points_html}</ul>' if points_html else '')
    )


def _build_document_html(text: str, is_english: bool) -> str:
    """组装最终 HTML：摘要段 + 分隔线 + 正文段"""
    summary_html = _build_summary_html(text)
    body_html = _bilingual_html(text) if is_english else _paragraphs_to_html(text)
    return (
        '<div class="doc-summary">'
        '<h2>摘要与核心要点</h2>'
        + summary_html
        + '</div>'
        '<hr>'
        '<div class="doc-content">'
        + body_html
        + '</div>'
    )


# ─── 入口 ────────────────────────────────────────────────────

async def handle_document(article_id: str) -> Dict[str, Any]:
    media_storage_path = os.environ.get('MEDIA_STORAGE_PATH', '')
    if not media_storage_path:
        return {
            'article_id': article_id,
            'status': 'error',
            'error_message': 'MEDIA_STORAGE_PATH 未设置',
        }

    ext = media_storage_path.rsplit('.', 1)[-1].lower()

    # 老格式提前返回友好错误
    if ext == 'doc':
        return {'article_id': article_id, 'status': 'error',
                'error_message': '暂不支持 .doc 格式，请转换为 .docx 后重新发送。'}
    if ext == 'ppt':
        return {'article_id': article_id, 'status': 'error',
                'error_message': '暂不支持 .ppt 格式，请转换为 .pptx 后重新发送。'}

    logger.info(f'下载文档：{media_storage_path}')
    raw_bytes = _download_from_storage(media_storage_path)

    logger.info(f'提取文字：ext={ext}，大小={len(raw_bytes)} bytes')
    text, title = _extract_text(raw_bytes, ext)

    if not text.strip():
        return {'article_id': article_id, 'status': 'error',
                'error_message': '文档内容为空，无法处理。'}

    is_english = _detect_english(text)
    logger.info(f'语言检测：{"英文" if is_english else "中文"}')

    logger.info('AI 处理：生成摘要 + HTML 格式化')
    content_html = _build_document_html(text, is_english)

    return {
        'article_id': article_id,
        'status': 'success',
        'title': title,
        'content_md': content_html,
        'content_text': text[:4000],
        'video_storage_path': media_storage_path,  # 复用字段触发 signed URL 生成
    }
