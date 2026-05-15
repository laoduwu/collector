import base64
from unittest.mock import patch, MagicMock, AsyncMock
import pytest


@pytest.mark.asyncio
async def test_article_html_inlines_images_and_keeps_style(monkeypatch):
    """HTML 直存：图片下载后 base64 内联到 src；内联 style 保留；script 删除。"""
    monkeypatch.setenv('ARTICLE_ID', 'a-1')
    monkeypatch.setenv('SOURCE_URL', 'https://mp.weixin.qq.com/s/xxx')
    monkeypatch.setenv('CONTENT_TYPE', 'article')
    monkeypatch.setenv('CALLBACK_URL', 'https://x.supabase.co/functions/v1/actions-callback')
    monkeypatch.setenv('CALLBACK_TOKEN', 't')

    from main import run

    fake_article = MagicMock()
    fake_article.title = 'T'
    fake_article.author = '某公众号'
    fake_article.content = '备用'
    fake_article.content_html = (
        '<script>tracker()</script>'
        '<p style="text-align:center;font-size:12px">图注居中小字</p>'
        '<img src="https://mmbiz.qpic.cn/x/640?wx_fmt=png">'
    )

    with patch('main.PlaywrightScraper') as Scraper, \
         patch('main.download_to_bytes', return_value=('640.png', b'PNG')) as dl, \
         patch('main.post_callback') as cb:
        Scraper.return_value.scrape = AsyncMock(return_value=fake_article)
        await run()

        sent = cb.call_args.args[0]
        assert sent['status'] == 'success'
        assert sent['author'] == '某公众号'
        # 图片 base64 内联
        b64 = base64.b64encode(b'PNG').decode()
        assert f'data:image/png;base64,{b64}' in sent['content_md']
        assert 'mmbiz.qpic.cn' not in sent['content_md']
        # 内联 style 保留（排版保真）
        assert 'text-align:center' in sent['content_md']
        # script 被删除
        assert 'tracker()' not in sent['content_md']
        # 分类用纯文本，不含标签
        assert '<' not in sent['content_text']
        assert '图注居中小字' in sent['content_text']
        # 微信图带防盗链 Referer
        assert dl.call_args.kwargs.get('referer') == 'https://mp.weixin.qq.com/'
        # HTML 直存不再产出 article_images 字段
        assert 'article_images' not in sent


@pytest.mark.asyncio
async def test_article_delazies_then_inlines(monkeypatch):
    """懒加载图：data-src 真实地址被提升并内联，占位 SVG 不残留。"""
    monkeypatch.setenv('ARTICLE_ID', 'a-lazy')
    monkeypatch.setenv('SOURCE_URL', 'https://mp.weixin.qq.com/s/xxx')
    monkeypatch.setenv('CONTENT_TYPE', 'article')
    monkeypatch.setenv('CALLBACK_URL', 'https://x.supabase.co/functions/v1/actions-callback')
    monkeypatch.setenv('CALLBACK_TOKEN', 't')

    from main import run

    fake_article = MagicMock()
    fake_article.title = 'T'
    fake_article.author = 'A'
    fake_article.content = '备用'
    fake_article.content_html = (
        '<img src="data:image/svg+xml,%3Csvg/%3E" '
        'data-src="https://mmbiz.qpic.cn/real/640?wx_fmt=png">'
    )

    with patch('main.PlaywrightScraper') as Scraper, \
         patch('main.download_to_bytes', return_value=('640.png', b'IMG')) as dl, \
         patch('main.post_callback') as cb:
        Scraper.return_value.scrape = AsyncMock(return_value=fake_article)
        await run()

        sent = cb.call_args.args[0]
        b64 = base64.b64encode(b'IMG').decode()
        assert f'data:image/png;base64,{b64}' in sent['content_md']
        # 占位 svg 与原始 http 地址都不应残留
        assert 'svg+xml' not in sent['content_md']
        assert 'mmbiz.qpic.cn' not in sent['content_md']
        # 下载的是 data-src 的真实地址
        assert dl.call_args.args[0] == 'https://mmbiz.qpic.cn/real/640?wx_fmt=png'


@pytest.mark.asyncio
async def test_article_flow_failure_reports_error(monkeypatch):
    monkeypatch.setenv('ARTICLE_ID', 'a-2')
    monkeypatch.setenv('SOURCE_URL', 'https://bad.example/404')
    monkeypatch.setenv('CONTENT_TYPE', 'article')
    monkeypatch.setenv('CALLBACK_URL', 'https://x.supabase.co/functions/v1/actions-callback')
    monkeypatch.setenv('CALLBACK_TOKEN', 't')

    from main import run

    with patch('main.PlaywrightScraper') as Scraper, \
         patch('main.post_callback') as cb:
        Scraper.return_value.scrape = AsyncMock(side_effect=RuntimeError('boom'))
        await run()
        sent = cb.call_args.args[0]
        assert sent['article_id'] == 'a-2'
        assert sent['status'] == 'error'
        assert 'boom' in sent['error_message']


# YouTube 转录流程的测试见独立任务（youtube-transcript-api 新版 API 变更，
# _handle_youtube 待单独适配，不在 HTML 直存任务范围内）。
