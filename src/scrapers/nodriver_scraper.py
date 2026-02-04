"""基于Nodriver的网页抓取器"""
import asyncio
import re
from typing import Optional, Dict, List
from urllib.parse import urlparse
import nodriver as uc
from ..utils.logger import logger
from ..utils.retry import async_retry_with_backoff


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
            # 启动浏览器
            self.browser = await uc.start(headless=True)
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

        # 等待内容加载
        await asyncio.sleep(2)

        # 提取标题
        try:
            title_elem = await page.find('h1#activity-name', timeout=10)
            title = (await title_elem.text).strip()
        except Exception as e:
            logger.warning(f"Failed to find WeChat title: {e}")
            title = "未知标题"

        # 提取作者
        author = None
        try:
            author_elem = await page.find('#js_name', timeout=5)
            author = (await author_elem.text).strip()
        except Exception:
            logger.debug("Author not found in WeChat article")

        # 提取发布日期
        publish_date = None
        try:
            date_elem = await page.find('#publish_time', timeout=5)
            publish_date = (await date_elem.text).strip()
        except Exception:
            logger.debug("Publish date not found in WeChat article")

        # 提取正文内容
        content = ""
        try:
            content_elem = await page.find('#js_content', timeout=10)
            content = (await content_elem.text).strip()
        except Exception as e:
            logger.error(f"Failed to extract WeChat content: {e}")
            # 尝试备用选择器
            try:
                content_elem = await page.find('.rich_media_content', timeout=5)
                content = (await content_elem.text).strip()
            except Exception:
                logger.warning("Using fallback content extraction")
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
                text = (await elem.text).strip()
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
                text = (await elem.text).strip()
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
                # 尝试获取datetime属性
                date_str = await elem.get_attribute('datetime')
                if date_str:
                    return date_str

                # 否则获取文本
                text = (await elem.text).strip()
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
                text = (await elem.text).strip()
                if text and len(text) > 100:  # 内容应该足够长
                    logger.debug(f"Content found with selector: {selector}")
                    return text
            except Exception:
                continue

        # 如果都失败，获取body文本
        try:
            body = await page.find('body')
            return (await body.text).strip()
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
