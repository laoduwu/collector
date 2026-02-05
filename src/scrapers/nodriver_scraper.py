"""基于Nodriver的网页抓取器"""
import asyncio
import re
import aiohttp
from typing import Optional, Dict, List
from urllib.parse import urlparse
import nodriver as uc
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
        images: Optional[List[str]] = None
    ):
        self.url = url
        self.title = title
        self.content = content
        self.author = author
        self.publish_date = publish_date
        self.images = images or []

    def __repr__(self):
        return f"ArticleData(title='{self.title}', images={len(self.images)})"


class NodriverScraper:
    """Nodriver网页抓取器"""

    def __init__(self):
        self.browser: Optional[uc.Browser] = None

    def is_weixin_article(self, url: str) -> bool:
        """
        判断是否为微信公众号文章

        Args:
            url: 文章URL

        Returns:
            是否为微信文章
        """
        parsed = urlparse(url)
        return 'weixin.qq.com' in parsed.netloc or 'mp.weixin.qq.com' in parsed.netloc

    async def _scrape_with_jina_reader(self, url: str) -> ArticleData:
        """
        使用 Jina Reader API 抓取文章（备用方案）

        Jina Reader 可以绑过很多反爬机制
        """
        logger.info(f"Using Jina Reader API for: {url}")
        jina_url = f"https://r.jina.ai/{url}"

        async with aiohttp.ClientSession() as session:
            async with session.get(jina_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    raise Exception(f"Jina Reader failed with status {response.status}")

                content = await response.text()

        # Jina Reader 返回 Markdown 格式
        # 解析标题（通常是第一行 # 开头）
        lines = content.strip().split('\n')
        title = "未知标题"
        content_start = 0

        for i, line in enumerate(lines):
            if line.startswith('# '):
                title = line[2:].strip()
                content_start = i + 1
                break
            elif line.startswith('Title: '):
                title = line[7:].strip()
                content_start = i + 1
                break

        # 剩余内容作为正文
        article_content = '\n'.join(lines[content_start:]).strip()

        logger.info(f"Jina Reader extracted: title='{title}', content length={len(article_content)}")

        return ArticleData(
            url=url,
            title=title,
            content=article_content,
            author=None,
            publish_date=None,
            images=[]
        )

    @async_retry_with_backoff(max_retries=3, base_delay=5.0)
    async def scrape(self, url: str) -> ArticleData:
        """
        抓取文章内容

        Args:
            url: 文章URL

        Returns:
            文章数据

        Raises:
            Exception: 抓取失败
        """
        logger.info(f"Starting to scrape: {url}")

        try:
            # 启动浏览器（支持容器环境/root用户）
            # 配置浏览器参数以兼容Docker/GitHub Actions环境
            browser_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-extensions'
            ]

            self.browser = await uc.start(
                headless=True,
                browser_args=browser_args
            )
            page = await self.browser.get(url)

            # 等待页面加载
            await asyncio.sleep(3)

            # 根据URL类型选择不同的抓取策略
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
            # 关闭浏览器
            if self.browser:
                try:
                    await self.browser.stop()
                except Exception as e:
                    logger.warning(f"Failed to close browser: {str(e)}")

    async def _scrape_weixin(self, page: uc.Tab, url: str) -> ArticleData:
        """
        抓取微信公众号文章

        Args:
            page: 浏览器页面对象
            url: 文章URL

        Returns:
            文章数据
        """
        logger.info("Scraping WeChat article...")

        # 等待页面初始加载
        await asyncio.sleep(3)

        # 滚动页面触发懒加载
        try:
            await page.scroll_down(500)
            await asyncio.sleep(1)
            await page.scroll_up(500)
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")

        # 获取页面标题用于诊断
        try:
            page_title = await page.evaluate("document.title")
            logger.info(f"Page title: {page_title}")
        except Exception as e:
            logger.warning(f"Failed to get page title: {e}")

        # 检查是否是验证页面或非文章页面
        is_blocked = False
        try:
            page_html = await page.evaluate("document.body.innerHTML.substring(0, 1000)")
            logger.debug(f"Page HTML preview: {page_html[:200]}")
            # 检查各种被拦截的情况
            blocked_indicators = [
                "验证", "请在微信客户端打开", "环境异常", "访问过于频繁",
                "Weixin Official Accounts Platform", "请使用微信扫一扫"
            ]
            for indicator in blocked_indicators:
                if indicator in page_html or indicator in page_title:
                    logger.warning(f"Detected blocked page: {indicator}")
                    is_blocked = True
                    break
        except Exception as e:
            logger.warning(f"Failed to check page content: {e}")

        # 如果被拦截，使用 Jina Reader 作为备用方案
        if is_blocked:
            logger.info("Page blocked, switching to Jina Reader API...")
            try:
                return await self._scrape_with_jina_reader(url)
            except Exception as e:
                logger.error(f"Jina Reader also failed: {e}")
                # 继续尝试原始方法

        # 额外等待确保 JavaScript 渲染完成
        await asyncio.sleep(2)

        # 提取标题 - 使用 JavaScript 直接获取更可靠
        try:
            # 先尝试 JavaScript 方式
            title = await page.evaluate("""
                (() => {
                    const el = document.getElementById('activity-name');
                    return el ? el.innerText.trim() : null;
                })()
            """)
            if not title:
                # 备用：尝试其他可能的选择器
                title = await page.evaluate("""
                    (() => {
                        const el = document.querySelector('h1.rich_media_title') ||
                                   document.querySelector('h2.rich_media_title') ||
                                   document.querySelector('.rich_media_title');
                        return el ? el.innerText.trim() : null;
                    })()
                """)
            if title:
                logger.info(f"Found title via JS: {title}")
            else:
                logger.warning("WeChat title element not found via JS")
                title = "未知标题"
        except Exception as e:
            logger.warning(f"Failed to find WeChat title: {e}")
            title = "未知标题"

        # 提取作者 - 使用 JavaScript
        author = None
        try:
            author = await page.evaluate("""
                (() => {
                    const el = document.getElementById('js_name') ||
                               document.querySelector('.rich_media_meta_text') ||
                               document.querySelector('a.weui-wa-hotarea');
                    return el ? el.innerText.trim() : null;
                })()
            """)
            if author:
                logger.info(f"Found author: {author}")
        except Exception as e:
            logger.debug(f"Author not found: {e}")

        # 提取发布日期 - 使用 JavaScript
        publish_date = None
        try:
            publish_date = await page.evaluate("""
                (() => {
                    const el = document.getElementById('publish_time') ||
                               document.querySelector('.rich_media_meta_text em.rich_media_meta_text');
                    return el ? el.innerText.trim() : null;
                })()
            """)
            if publish_date:
                logger.info(f"Found publish_date: {publish_date}")
        except Exception as e:
            logger.debug(f"Publish date not found: {e}")

        # 提取正文内容 - 使用 JavaScript 直接获取
        content = ""
        try:
            content = await page.evaluate("""
                (() => {
                    const el = document.getElementById('js_content') ||
                               document.querySelector('.rich_media_content');
                    if (!el) return null;
                    // 获取纯文本内容
                    return el.innerText.trim();
                })()
            """)
            if content:
                logger.info(f"Found content via JS, length: {len(content)}")
            else:
                logger.warning("Content element not found or empty via JS")
                # 尝试获取整个文章区域
                content = await page.evaluate("""
                    (() => {
                        const el = document.querySelector('.rich_media_area_primary') ||
                                   document.querySelector('article') ||
                                   document.querySelector('#img-content');
                        return el ? el.innerText.trim() : '内容提取失败';
                    })()
                """)
                if content and content != '内容提取失败':
                    logger.info(f"Found content via fallback JS, length: {len(content)}")
        except Exception as e:
            logger.error(f"Failed to extract WeChat content via JS: {e}")
            content = "内容提取失败"

        # 提取图片
        images = await self._extract_weixin_images(page)

        logger.info(f"Extracted WeChat article: {title}, {len(images)} images")

        return ArticleData(
            url=url,
            title=title,
            content=content,
            author=author,
            publish_date=publish_date,
            images=images
        )

    async def _extract_weixin_images(self, page: uc.Tab) -> List[str]:
        """
        提取微信文章中的图片URL

        Args:
            page: 浏览器页面对象

        Returns:
            图片URL列表
        """
        images = []

        try:
            # 查找内容区域的所有图片
            img_elements = await page.find_all('#js_content img')

            for img_elem in img_elements:
                # 微信图片通常在data-src属性中
                img_url = await img_elem.get_attribute('data-src')

                # 如果没有data-src，尝试src属性
                if not img_url:
                    img_url = await img_elem.get_attribute('src')

                if img_url and img_url.startswith('http'):
                    # 过滤掉表情图片等小图
                    if 'mmbiz.qpic.cn' in img_url or 'mmbiz.qlogo.cn' in img_url:
                        images.append(img_url)

            logger.info(f"Found {len(images)} WeChat images")

        except Exception as e:
            logger.warning(f"Failed to extract WeChat images: {e}")

        return images

    async def _scrape_generic(self, page: uc.Tab, url: str) -> ArticleData:
        """
        抓取普通网页文章

        Args:
            page: 浏览器页面对象
            url: 文章URL

        Returns:
            文章数据
        """
        logger.info("Scraping generic web article...")

        # 提取标题 - 尝试多个常见选择器
        title = await self._extract_title(page)

        # 提取作者
        author = await self._extract_author(page)

        # 提取发布日期
        publish_date = await self._extract_publish_date(page)

        # 提取正文内容
        content = await self._extract_content(page)

        # 提取图片
        images = await self._extract_images(page)

        logger.info(f"Extracted generic article: {title}, {len(images)} images")

        return ArticleData(
            url=url,
            title=title,
            content=content,
            author=author,
            publish_date=publish_date,
            images=images
        )

    async def _extract_title(self, page: uc.Tab) -> str:
        """提取标题"""
        # 常见标题选择器
        selectors = ['h1', 'article h1', '.article-title', '.post-title', 'title']

        for selector in selectors:
            try:
                elem = await page.find(selector, timeout=2)
                if elem and elem.text:
                    text = elem.text.strip()
                    if text and len(text) > 0:
                        logger.debug(f"Title found with selector: {selector}")
                        return text
            except Exception:
                continue

        # 如果都失败，使用页面标题
        try:
            title_text = await page.title
            return title_text or "未知标题"
        except Exception:
            return "未知标题"

    async def _extract_author(self, page: uc.Tab) -> Optional[str]:
        """提取作者"""
        selectors = ['.author', '.post-author', '[rel="author"]', '.byline']

        for selector in selectors:
            try:
                elem = await page.find(selector, timeout=1)
                if elem and elem.text:
                    text = elem.text.strip()
                    if text:
                        return text
            except Exception:
                continue

        return None

    async def _extract_publish_date(self, page: uc.Tab) -> Optional[str]:
        """提取发布日期"""
        selectors = ['time', '.publish-date', '.post-date', '.date']

        for selector in selectors:
            try:
                elem = await page.find(selector, timeout=1)
                if elem:
                    # 尝试获取datetime属性
                    date_str = await elem.get_attribute('datetime')
                    if date_str:
                        return date_str

                    # 否则获取文本
                    if elem.text:
                        text = elem.text.strip()
                        if text:
                            return text
            except Exception:
                continue

        return None

    async def _extract_content(self, page: uc.Tab) -> str:
        """提取正文内容"""
        # 常见内容选择器
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
                elem = await page.find(selector, timeout=2)
                if elem and elem.text:
                    text = elem.text.strip()
                    if text and len(text) > 100:  # 内容应该足够长
                        logger.debug(f"Content found with selector: {selector}")
                        return text
            except Exception:
                continue

        # 如果都失败，获取body文本
        try:
            body = await page.find('body')
            if body and body.text:
                return body.text.strip()
            return "内容提取失败"
        except Exception:
            return "内容提取失败"

    async def _extract_images(self, page: uc.Tab) -> List[str]:
        """提取文章图片"""
        images = []

        try:
            # 查找所有图片元素
            img_elements = await page.find_all('img')

            for img_elem in img_elements:
                # 尝试多个属性
                img_url = None
                for attr in ['src', 'data-src', 'data-original']:
                    img_url = await img_elem.get_attribute(attr)
                    if img_url and img_url.startswith('http'):
                        break

                if img_url and img_url.startswith('http'):
                    # 过滤掉明显的图标、logo等小图
                    # 简单过滤：跳过包含'icon'、'logo'等关键词的URL
                    url_lower = img_url.lower()
                    if not any(kw in url_lower for kw in ['icon', 'logo', 'avatar', 'emoji']):
                        images.append(img_url)

            logger.info(f"Found {len(images)} images")

        except Exception as e:
            logger.warning(f"Failed to extract images: {e}")

        return images
