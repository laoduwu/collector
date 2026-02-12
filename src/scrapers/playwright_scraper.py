"""基于Playwright的网页抓取器 - 支持微信公众号文章和飞书文档"""
import asyncio
import hashlib
import os
import re
from typing import Optional, List, Dict
from urllib.parse import urlparse

from utils.config import config

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from utils.logger import logger
from utils.retry import async_retry_with_backoff


class ArticleData:
    """文章数据模型"""

    def __init__(
        self,
        url: str,
        title: str,
        content: str,
        author: Optional[str] = None,
        publish_date: Optional[str] = None,
        images: Optional[List[str]] = None,
        content_html: Optional[str] = None,
        local_image_map: Optional[Dict[str, str]] = None
    ):
        self.url = url
        self.title = title
        self.content = content  # 纯文本内容
        self.content_html = content_html  # HTML内容（保留格式）
        self.author = author
        self.publish_date = publish_date
        self.images = images or []
        self.local_image_map = local_image_map or {}  # {原始URL: 本地路径}

    @property
    def content_length(self) -> int:
        """返回内容长度"""
        return len(self.content) if self.content else 0

    def __repr__(self):
        return f"ArticleData(title='{self.title}', images={len(self.images)})"


class PlaywrightScraper:
    """Playwright网页抓取器 - 支持微信公众号"""

    def __init__(self, headless: bool = True):
        """
        初始化抓取器

        Args:
            headless: 是否使用无头模式，默认True
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError(
                "Playwright未安装。请运行: pip install playwright && python -m playwright install chromium"
            )
        self.headless = headless
        self.browser: Optional[Browser] = None

    def is_weixin_article(self, url: str) -> bool:
        """判断是否为微信公众号文章"""
        parsed = urlparse(url)
        return 'weixin.qq.com' in parsed.netloc or 'mp.weixin.qq.com' in parsed.netloc

    def is_feishu_document(self, url: str) -> bool:
        """判断是否为飞书文档（wiki 或 docx）"""
        parsed = urlparse(url)
        is_feishu_host = any(
            domain in parsed.netloc
            for domain in ['feishu.cn', 'larksuite.com']
        )
        is_doc_path = '/wiki/' in parsed.path or '/docx/' in parsed.path
        return is_feishu_host and is_doc_path

    @async_retry_with_backoff(max_retries=3, base_delay=5.0)
    async def scrape(self, url: str) -> ArticleData:
        """
        抓取文章内容

        Args:
            url: 文章URL

        Returns:
            ArticleData 文章数据
        """
        logger.info(f"Starting to scrape with Playwright: {url}")

        async with async_playwright() as p:
            try:
                # 启动浏览器
                self.browser = await p.chromium.launch(
                    headless=self.headless,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-blink-features=AutomationControlled',
                    ]
                )

                # 创建上下文，模拟真实用户
                context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
                    locale='zh-CN',
                )

                # 注入脚本隐藏自动化特征
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                    window.chrome = { runtime: {} };
                """)

                page = await context.new_page()

                # 访问页面
                logger.info(f"Navigating to: {url}")
                await page.goto(url, wait_until='networkidle', timeout=60000)

                # 等待页面加载
                await asyncio.sleep(3)

                # 根据URL类型选择不同策略
                if self.is_feishu_document(url):
                    article_data = await self._scrape_feishu(page, url)
                elif self.is_weixin_article(url):
                    article_data = await self._scrape_weixin(page, url)
                else:
                    article_data = await self._scrape_generic(page, url)

                logger.info(f"Successfully scraped: {article_data.title}")
                return article_data

            except Exception as e:
                logger.error(f"Failed to scrape {url}: {str(e)}")
                raise

            finally:
                if self.browser:
                    await self.browser.close()

    async def _scrape_weixin(self, page: Page, url: str) -> ArticleData:
        """抓取微信公众号文章"""
        logger.info("Scraping WeChat article with Playwright...")

        # 检查页面是否正常加载
        page_content = await page.content()
        error_indicators = [
            "该内容已被发布者删除",
            "此内容因违规无法查看",
            "该公众号已被封禁",
        ]

        for indicator in error_indicators:
            if indicator in page_content:
                logger.warning(f"Article unavailable: {indicator}")
                return ArticleData(
                    url=url,
                    title=f"[文章不可用] {indicator}",
                    content=f"该微信文章无法访问：{indicator}\n\n原文链接：{url}",
                    author=None,
                    publish_date=None,
                    images=[]
                )

        # 滚动页面触发懒加载
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
        await asyncio.sleep(1)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # 提取标题
        title = None
        try:
            title_elem = await page.query_selector("#activity-name")
            if title_elem:
                title = await title_elem.inner_text()
                title = title.strip()
                logger.info(f"Found title: {title}")
        except Exception as e:
            logger.warning(f"Title extraction failed: {e}")

        if not title:
            try:
                title_elem = await page.query_selector("h1.rich_media_title, h2.rich_media_title, .rich_media_title")
                if title_elem:
                    title = await title_elem.inner_text()
                    title = title.strip()
            except:
                pass

        if not title:
            title = await page.title() or "未知标题"

        # 提取作者
        author = None
        try:
            author_elem = await page.query_selector("#js_name")
            if author_elem:
                author = await author_elem.inner_text()
                author = author.strip()
                logger.info(f"Found author: {author}")
        except Exception as e:
            logger.debug(f"Author extraction failed: {e}")

        # 提取发布日期
        publish_date = None
        try:
            date_elem = await page.query_selector("#publish_time")
            if date_elem:
                publish_date = await date_elem.inner_text()
                publish_date = publish_date.strip()
                logger.info(f"Found publish_date: {publish_date}")
        except Exception as e:
            logger.debug(f"Publish date extraction failed: {e}")

        # 提取正文
        content = ""
        content_html = ""
        try:
            content_elem = await page.query_selector("#js_content")
            if content_elem:
                content = await content_elem.inner_text()
                content = content.strip()
                content_html = await content_elem.inner_html()
                content_html = content_html.strip()
                logger.info(f"Found content, length: {len(content)}")
        except Exception as e:
            logger.warning(f"Content extraction failed: {e}")

        if not content:
            try:
                content_elem = await page.query_selector(".rich_media_content")
                if content_elem:
                    content = await content_elem.inner_text()
                    content = content.strip()
                    content_html = await content_elem.inner_html()
                    content_html = content_html.strip()
            except:
                pass

        if not content:
            content = "内容提取失败"

        # 提取图片
        images = await self._extract_weixin_images(page)

        return ArticleData(
            url=url,
            title=title,
            content=content,
            content_html=content_html,
            author=author,
            publish_date=publish_date,
            images=images
        )

    async def _extract_weixin_images(self, page: Page) -> List[str]:
        """提取微信文章中的图片URL"""
        images = []
        try:
            img_elements = await page.query_selector_all("#js_content img")
            for img in img_elements:
                # 微信图片通常在data-src属性
                src = await img.get_attribute("data-src")
                if not src:
                    src = await img.get_attribute("src")

                if src and src.startswith("http"):
                    # 过滤微信图片域名
                    if 'mmbiz.qpic.cn' in src or 'mmbiz.qlogo.cn' in src:
                        images.append(src)

            logger.info(f"Found {len(images)} WeChat images")
        except Exception as e:
            logger.warning(f"Image extraction failed: {e}")

        return images

    async def _scrape_generic(self, page: Page, url: str) -> ArticleData:
        """抓取普通网页文章 - 使用 Trafilatura 提取正文"""
        import trafilatura

        logger.info("Scraping generic web article with Playwright + Trafilatura...")

        # Playwright 渲染后获取完整 HTML
        full_html = await page.content()

        # Trafilatura 提取正文 HTML（保留格式标签）
        content_html = trafilatura.extract(
            full_html,
            output_format='html',
            include_images=True,
            include_links=True,
            include_formatting=True,
            url=url,
        )

        # 提取纯文本作为 fallback
        content_text = trafilatura.extract(full_html, url=url) or ""

        # 提取元数据（标题、作者、日期）
        metadata = trafilatura.extract_metadata(full_html, default_url=url)

        title = (
            (metadata.title if metadata and metadata.title else None)
            or await self._extract_title(page)
        )
        author = (
            (metadata.author if metadata and metadata.author else None)
            or await self._extract_author(page)
        )
        publish_date = (
            (metadata.date if metadata and metadata.date else None)
            or await self._extract_publish_date(page)
        )

        # 从正文 HTML 中提取图片 URL
        images = self._extract_images_from_html(content_html) if content_html else []

        return ArticleData(
            url=url,
            title=title,
            content=content_text or "内容提取失败",
            author=author,
            publish_date=publish_date,
            images=images,
            content_html=content_html,
        )

    def _extract_images_from_html(self, html: str) -> List[str]:
        """从 HTML 内容中提取图片 URL（支持 img 和 trafilatura 的 graphic 标签）"""
        from bs4 import BeautifulSoup

        images = []
        soup = BeautifulSoup(html, 'lxml')
        for img in soup.find_all(['img', 'graphic']):
            src = img.get('src') or img.get('data-src')
            if src and src.startswith('http'):
                url_lower = src.lower()
                if not any(kw in url_lower for kw in ['icon', 'logo', 'avatar', 'emoji']):
                    images.append(src)
        return images

    async def _extract_title(self, page: Page) -> str:
        """提取标题"""
        selectors = ['h1', 'article h1', '.article-title', '.post-title']

        for selector in selectors:
            try:
                elem = await page.query_selector(selector)
                if elem:
                    text = await elem.inner_text()
                    text = text.strip()
                    if text and len(text) > 0:
                        return text
            except:
                continue

        return await page.title() or "未知标题"

    async def _extract_author(self, page: Page) -> Optional[str]:
        """提取作者"""
        selectors = ['.author', '.post-author', '[rel="author"]', '.byline']

        for selector in selectors:
            try:
                elem = await page.query_selector(selector)
                if elem:
                    text = await elem.inner_text()
                    text = text.strip()
                    if text:
                        return text
            except:
                continue

        return None

    async def _extract_publish_date(self, page: Page) -> Optional[str]:
        """提取发布日期"""
        selectors = ['time', '.publish-date', '.post-date', '.date']

        for selector in selectors:
            try:
                elem = await page.query_selector(selector)
                if elem:
                    date_str = await elem.get_attribute('datetime')
                    if date_str:
                        return date_str
                    text = await elem.inner_text()
                    if text:
                        return text.strip()
            except:
                continue

        return None

    async def _extract_content(self, page: Page) -> str:
        """提取正文内容"""
        selectors = [
            'article',
            '.article-content',
            '.post-content',
            '.content',
            'main',
            '#content'
        ]

        for selector in selectors:
            try:
                elem = await page.query_selector(selector)
                if elem:
                    text = await elem.inner_text()
                    text = text.strip()
                    if text and len(text) > 100:
                        return text
            except:
                continue

        # 如果都失败，获取body
        try:
            body = await page.query_selector('body')
            if body:
                return (await body.inner_text()).strip()
        except:
            pass

        return "内容提取失败"

    async def _extract_images(self, page: Page) -> List[str]:
        """提取文章图片"""
        images = []
        try:
            img_elements = await page.query_selector_all('img')
            for img in img_elements:
                src = await img.get_attribute('src')
                if not src:
                    src = await img.get_attribute('data-src')

                if src and src.startswith('http'):
                    url_lower = src.lower()
                    if not any(kw in url_lower for kw in ['icon', 'logo', 'avatar', 'emoji']):
                        images.append(src)

            logger.info(f"Found {len(images)} images")
        except Exception as e:
            logger.warning(f"Image extraction failed: {e}")

        return images

    async def _scrape_feishu(self, page: Page, url: str) -> ArticleData:
        """抓取飞书文档（wiki/docx）"""
        logger.info("Scraping Feishu document with Playwright...")

        # 提取标题
        title = None
        try:
            title_elem = await page.query_selector('.doc-title-wrapper, .wiki-title, [data-block-type="title"]')
            if title_elem:
                title = (await title_elem.inner_text()).strip()
        except Exception as e:
            logger.debug(f"Feishu title extraction via selector failed: {e}")

        if not title:
            title = await page.title() or "未知标题"
            # 清理飞书页面标题后缀
            for suffix in [' - 飞书云文档', ' - Feishu']:
                if title.endswith(suffix):
                    title = title[:-len(suffix)]

        logger.info(f"Feishu document title: {title}")

        # 逐步滚动收集所有块
        blocks = await self._feishu_scroll_and_collect(page)
        logger.info(f"Collected {len(blocks)} blocks from Feishu document")

        # 提取图片URL
        image_urls = [
            b['src'] for b in blocks
            if b['type'] == 'image' and b.get('src')
        ]
        logger.info(f"Found {len(image_urls)} images in Feishu document")

        # 用浏览器上下文下载飞书内部图片
        local_image_map = {}
        if image_urls:
            local_image_map = await self._download_feishu_images(page, image_urls)
            logger.info(f"Downloaded {len(local_image_map)}/{len(image_urls)} Feishu images")

        # 构建标准 HTML
        content_html = self._build_feishu_html(blocks)

        # 提取纯文本
        text_parts = []
        for b in blocks:
            if b['type'] in ('text', 'heading1', 'heading2', 'heading3', 'heading4',
                             'heading5', 'heading6', 'heading7', 'heading8', 'heading9',
                             'quote', 'bullet', 'ordered', 'code'):
                text_parts.append(b.get('text', ''))
        content_text = '\n'.join(text_parts) or "内容提取失败"

        return ArticleData(
            url=url,
            title=title,
            content=content_text,
            content_html=content_html,
            images=image_urls,
            local_image_map=local_image_map,
        )

    async def _feishu_scroll_and_collect(self, page: Page) -> List[dict]:
        """逐步滚动飞书页面，收集所有已渲染的块（按 data-block-id 去重）"""

        collect_js = """
        () => {
            const blocks = [];
            const wrapper = document.querySelector('.render-unit-wrapper');
            if (!wrapper) return blocks;

            const blockEls = wrapper.querySelectorAll('.block[data-block-type]');
            for (const el of blockEls) {
                const blockType = el.getAttribute('data-block-type');
                const blockId = el.getAttribute('data-block-id') || '';
                let text = '';
                let src = '';
                let inlineHtml = '';

                if (blockType === 'image') {
                    // 优先用 image-token 重建原始 URL（blob URL 不可外部下载）
                    const tokenEl = el.querySelector('[image-token]');
                    const imageToken = tokenEl ? tokenEl.getAttribute('image-token') : '';
                    const recordId = el.getAttribute('data-record-id') || '';
                    if (imageToken && recordId) {
                        src = 'https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/v2/cover/'
                            + imageToken + '/?fallback_source=1&height=1280&mount_node_token='
                            + recordId + '&mount_point=docx_image&policy=equal&width=1280';
                    } else {
                        const img = el.querySelector('img.docx-image, img');
                        if (img) {
                            src = img.src || img.getAttribute('data-src') || '';
                        }
                    }
                } else if (blockType === 'code') {
                    // 代码块：收集所有行文本
                    const codeLines = el.querySelectorAll('.code-line, [data-line]');
                    if (codeLines.length > 0) {
                        const lines = [];
                        for (const line of codeLines) {
                            lines.push(line.textContent || '');
                        }
                        text = lines.join('\\n');
                    } else {
                        text = el.textContent || '';
                    }
                } else {
                    text = el.textContent || '';
                    // 保留行内格式
                    const contentEl = el.querySelector('[data-string="true"]')?.parentElement || el;
                    const spans = contentEl.querySelectorAll('span');
                    if (spans.length > 0) {
                        let html = '';
                        for (const span of spans) {
                            const style = span.getAttribute('style') || '';
                            let t = span.textContent || '';
                            if (!t) continue;
                            // 转义 HTML
                            t = t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                            const bold = style.includes('font-weight') && (style.includes('bold') || style.includes('700'));
                            const italic = style.includes('font-style') && style.includes('italic');
                            if (bold) t = '<strong>' + t + '</strong>';
                            if (italic) t = '<em>' + t + '</em>';
                            html += t;
                        }
                        if (html) inlineHtml = html;
                    }
                }

                blocks.push({
                    id: blockId,
                    type: blockType,
                    text: text,
                    src: src,
                    inlineHtml: inlineHtml
                });
            }
            return blocks;
        }
        """

        seen_ids = set()
        all_blocks = []

        # 飞书的滚动容器是 .bear-web-x-container，不是 window
        scroll_info = await page.evaluate("""() => {
            const container = document.querySelector('.bear-web-x-container');
            if (!container) return null;
            return { clientHeight: container.clientHeight };
        }""")

        if not scroll_info:
            logger.warning("Feishu scroll container not found, falling back to window scroll")
            # fallback: 直接收集当前可见块
            current_blocks = await page.evaluate(collect_js)
            return current_blocks

        scroll_step = int(scroll_info['clientHeight'] * 0.7)

        max_scrolls = 200  # 安全限制
        for _ in range(max_scrolls):
            # 收集当前可见块
            current_blocks = await page.evaluate(collect_js)
            for b in current_blocks:
                bid = b.get('id', '')
                if bid and bid not in seen_ids:
                    seen_ids.add(bid)
                    all_blocks.append(b)

            # 滚动飞书容器
            prev_scroll = await page.evaluate(
                "document.querySelector('.bear-web-x-container').scrollTop"
            )
            await page.evaluate(
                f"document.querySelector('.bear-web-x-container').scrollTop += {scroll_step}"
            )
            await asyncio.sleep(0.8)

            # 检测是否到达底部
            new_scroll = await page.evaluate(
                "document.querySelector('.bear-web-x-container').scrollTop"
            )
            if new_scroll == prev_scroll:
                # 再收集一次确保最后的块也被捕获
                current_blocks = await page.evaluate(collect_js)
                for b in current_blocks:
                    bid = b.get('id', '')
                    if bid and bid not in seen_ids:
                        seen_ids.add(bid)
                        all_blocks.append(b)
                break

        # 按 block id（尝试整数排序）排序
        def sort_key(b):
            try:
                return int(b.get('id', '0'))
            except (ValueError, TypeError):
                return 0

        all_blocks.sort(key=sort_key)
        return all_blocks

    def _build_feishu_html(self, blocks: List[dict]) -> str:
        """根据块列表生成标准 HTML"""
        html_parts = []
        list_stack = []  # 当前列表类型栈: 'bullet' or 'ordered'

        def close_lists():
            while list_stack:
                tag = list_stack.pop()
                html_parts.append(f'</{tag}>')

        def ensure_list(list_type: str):
            tag = 'ul' if list_type == 'bullet' else 'ol'
            if not list_stack or list_stack[-1] != tag:
                close_lists()
                list_stack.append(tag)
                html_parts.append(f'<{tag}>')

        for b in blocks:
            block_type = b.get('type', '')
            text = b.get('text', '')
            inline_html = b.get('inlineHtml', '')
            content = inline_html if inline_html else self._escape_html(text)

            if block_type in ('bullet', 'ordered'):
                ensure_list(block_type)
                html_parts.append(f'<li>{content}</li>')
                continue

            # 非列表块，关闭之前的列表
            close_lists()

            if block_type == 'text':
                if content.strip():
                    html_parts.append(f'<p>{content}</p>')
            elif block_type.startswith('heading'):
                # heading1 ~ heading9
                level = block_type.replace('heading', '')
                try:
                    n = int(level)
                    n = min(n, 6)  # HTML 只支持 h1-h6
                except ValueError:
                    n = 2
                html_parts.append(f'<h{n}>{content}</h{n}>')
            elif block_type == 'image':
                src = b.get('src', '')
                if src:
                    html_parts.append(f'<img src="{src}">')
            elif block_type == 'quote':
                html_parts.append(f'<blockquote>{content}</blockquote>')
            elif block_type == 'code':
                escaped = self._escape_html(text)
                html_parts.append(f'<pre><code>{escaped}</code></pre>')
            elif block_type == 'divider':
                html_parts.append('<hr>')
            else:
                # 未知块类型，当作段落
                if content.strip():
                    html_parts.append(f'<p>{content}</p>')

        close_lists()
        return '\n'.join(html_parts)

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符"""
        return (
            text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )

    async def _download_feishu_images(self, page: Page, image_urls: List[str]) -> Dict[str, str]:
        """用浏览器上下文下载飞书内部图片（携带 cookies）"""
        config.ensure_directories()
        downloads_dir = config.DOWNLOADS_DIR
        local_map = {}

        for idx, img_url in enumerate(image_urls):
            try:
                url_hash = hashlib.md5(img_url.encode()).hexdigest()[:12]
                filename = f"feishu_img_{idx}_{url_hash}.png"
                save_path = os.path.join(downloads_dir, filename)

                # 用浏览器上下文发起请求（携带 cookies）
                response = await page.context.request.get(img_url)
                if response.ok:
                    body = await response.body()
                    with open(save_path, 'wb') as f:
                        f.write(body)
                    local_map[img_url] = save_path
                    logger.debug(f"Downloaded Feishu image: {filename} ({len(body)} bytes)")
                else:
                    logger.warning(f"Failed to download Feishu image (HTTP {response.status}): {img_url}")
            except Exception as e:
                logger.warning(f"Failed to download Feishu image: {img_url} - {e}")

        return local_map
