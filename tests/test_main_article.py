import base64
import os
from unittest.mock import patch, MagicMock, AsyncMock
import pytest


@pytest.mark.asyncio
async def test_article_flow_success(monkeypatch):
    monkeypatch.setenv('ARTICLE_ID', 'a-1')
    monkeypatch.setenv('SOURCE_URL', 'https://mp.weixin.qq.com/s/xxx')
    monkeypatch.setenv('CONTENT_TYPE', 'article')
    monkeypatch.setenv('CALLBACK_URL', 'https://x.supabase.co/functions/v1/actions-callback')
    monkeypatch.setenv('CALLBACK_TOKEN', 't')

    from main import run

    fake_article = MagicMock()
    fake_article.title = 'T'
    fake_article.author = '某公众号'
    fake_article.content = '纯文本备用'
    fake_article.images = []
    # 微信图片在 content_html 里以 <img src> 出现；markdownify 转出 ![](url)
    fake_article.content_html = (
        '<p>正文</p>'
        '<img src="https://mmbiz.qpic.cn/x/640?wx_fmt=png">'
    )

    with patch('main.PlaywrightScraper') as Scraper, \
         patch('main.download_to_bytes', return_value=('640.png', b'PNG')) as dl, \
         patch('main.post_callback') as cb:
        Scraper.return_value.scrape = AsyncMock(return_value=fake_article)
        await run()

        sent = cb.call_args.args[0]
        assert sent['article_id'] == 'a-1'
        assert sent['status'] == 'success'
        assert sent['title'] == 'T'
        assert sent['author'] == '某公众号'
        assert '640.png' in sent['article_images']
        assert base64.b64decode(sent['article_images']['640.png']) == b'PNG'
        # 正文里图片被替换为 Obsidian 内部链接，不再有原始 URL
        assert '![[640.png]]' in sent['content_md']
        assert 'mmbiz.qpic.cn' not in sent['content_md']
        # 微信图片下载带了防盗链 Referer
        assert dl.call_args.kwargs.get('referer') == 'https://mp.weixin.qq.com/'


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


@pytest.mark.asyncio
async def test_article_flow_uses_html_when_available(monkeypatch):
    monkeypatch.setenv('ARTICLE_ID', 'a-html')
    monkeypatch.setenv('SOURCE_URL', 'https://mp.weixin.qq.com/s/xxx')
    monkeypatch.setenv('CONTENT_TYPE', 'article')
    monkeypatch.setenv('CALLBACK_URL', 'https://x.supabase.co/functions/v1/actions-callback')
    monkeypatch.setenv('CALLBACK_TOKEN', 't')

    from main import run

    fake_article = MagicMock()
    fake_article.title = 'T'
    fake_article.content = '原始纯文本备用'
    fake_article.content_html = '<h1>标题</h1><p>这是<strong>加粗</strong>段落</p><pre><code>print(1)</code></pre>'
    fake_article.images = []

    with patch('main.PlaywrightScraper') as Scraper, \
         patch('main.post_callback') as cb:
        Scraper.return_value.scrape = AsyncMock(return_value=fake_article)
        await run()
        sent = cb.call_args.args[0]
        # 来自 HTML 转换：应该看到 markdown 加粗、代码块标记
        assert '**加粗**' in sent['content_md']
        assert 'print(1)' in sent['content_md']
        # 不应该看到 HTML 标签残留
        assert '<strong>' not in sent['content_md']
        assert '<pre>' not in sent['content_md']


@pytest.mark.asyncio
async def test_article_flow_delazies_wechat_lazy_images(monkeypatch):
    """微信懒加载：真图在 data-src，src 是占位 SVG。
    预期：data-src 提升为 src → 下载真图 → 正文用 ![[]]，无 data: 占位残留。"""
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
    fake_article.images = []
    fake_article.content_html = (
        '<p>正文</p>'
        '<img src="data:image/svg+xml,%3Csvg/%3E" '
        'data-src="https://mmbiz.qpic.cn/real/640?wx_fmt=png">'
    )

    with patch('main.PlaywrightScraper') as Scraper, \
         patch('main.download_to_bytes', return_value=('640.png', b'IMG')) as dl, \
         patch('main.post_callback') as cb:
        Scraper.return_value.scrape = AsyncMock(return_value=fake_article)
        await run()
        sent = cb.call_args.args[0]
        assert '![[640.png]]' in sent['content_md']
        assert '640.png' in sent['article_images']
        # 占位 SVG 与真实 URL 都不应残留在正文
        assert 'data:image/svg' not in sent['content_md']
        assert 'mmbiz.qpic.cn' not in sent['content_md']
        # 下载的是 data-src 的真实地址，带防盗链 Referer
        assert dl.call_args.args[0] == 'https://mmbiz.qpic.cn/real/640?wx_fmt=png'
        assert dl.call_args.kwargs.get('referer') == 'https://mp.weixin.qq.com/'
