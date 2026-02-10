"""基于Playwright的网页抓取器 - 支持微信公众号文章"""
import asyncio
import re
from typing import Optional, List
from urllib.parse import urlparse

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
        content_html: Optional[str] = None
    ):
        self.url = url
        self.title = title
        self.content = content  # 纯文本内容
        self.content_html = content_html  # HTML内容（保留格式）
        self.author = author
        self.publish_date = publish_date
        self.images = images or []

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
                if self.is_weixin_article(url):
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
        """抓取普通网页文章"""
        logger.info("Scraping generic web article with Playwright...")

        # 提取标题
        title = await self._extract_title(page)

        # 提取作者
        author = await self._extract_author(page)

        # 提取发布日期
        publish_date = await self._extract_publish_date(page)

        # 提取正文
        content = await self._extract_content(page)

        # 提取图片
        images = await self._extract_images(page)

        return ArticleData(
            url=url,
            title=title,
            content=content,
            author=author,
            publish_date=publish_date,
            images=images
        )

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
