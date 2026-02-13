"""主入口 - 文章收集系统"""
import sys
import asyncio
from typing import Optional

from utils.logger import logger
from utils.config import config

# 优先使用Playwright（支持Python 3.9+），如果不可用则回退到Nodriver
try:
    from scrapers.playwright_scraper import PlaywrightScraper, ArticleData
    SCRAPER_TYPE = "playwright"
    logger.info("Using Playwright scraper")
except ImportError:
    try:
        from scrapers.nodriver_scraper import NodriverScraper as PlaywrightScraper, ArticleData
        SCRAPER_TYPE = "nodriver"
        logger.info("Using Nodriver scraper (Playwright not available)")
    except ImportError:
        raise ImportError("No scraper available. Install playwright or nodriver.")

from scrapers.image_downloader import ImageDownloader
from scrapers.media_scraper import (
    is_media_url, extract_audio, transcribe_audio,
    segments_to_text, cleanup_media_files
)
from image_pipeline.github_uploader import GitHubUploader
from image_pipeline.jsdelivr_cdn import JsDelivrCDN
from matchers.directory_matcher import DirectoryMatcher
from matchers.llm_client import LLMClient
from matchers.types import MatchResult
from feishu.auth_manager import AuthManager
from feishu.directory_manager import DirectoryManager
from feishu.document_uploader import DocumentUploader


class ArticleCollector:
    """文章收集器主类"""

    def __init__(self):
        """初始化所有组件"""
        logger.info("Initializing Article Collector...")

        # 验证配置
        missing_config = config.validate()
        if missing_config:
            logger.error(f"Missing required configuration: {', '.join(missing_config)}")
            raise ValueError(f"Missing configuration: {', '.join(missing_config)}")

        # 确保目录存在
        config.ensure_directories()

        # 初始化组件
        self.scraper = PlaywrightScraper(headless=True)
        self.image_downloader = ImageDownloader()
        self.github_uploader = GitHubUploader()
        self.cdn_generator = JsDelivrCDN()
        self.directory_matcher = DirectoryMatcher()

        # 飞书组件
        self.auth_manager = AuthManager()
        self.directory_manager = DirectoryManager(self.auth_manager)
        self.document_uploader = DocumentUploader(self.auth_manager)

        logger.info("Article Collector initialized successfully")

    async def process_url(self, url: str) -> Optional[str]:
        """
        处理 URL 的统一入口，自动判断是文章还是媒体

        Args:
            url: 待处理的 URL

        Returns:
            飞书文档URL，失败返回None
        """
        if is_media_url(url):
            logger.info(f"Detected media URL: {url}")
            return await self.process_media(url)
        return await self.process_article(url)

    async def process_media(self, url: str) -> Optional[str]:
        """
        处理媒体链接（视频/音频/播客）的完整流程

        Args:
            url: 媒体 URL

        Returns:
            飞书文档URL，失败返回None
        """
        logger.info("=" * 80)
        logger.info(f"Starting to process media: {url}")
        logger.info("=" * 80)

        audio_path = None
        try:
            # Step 1: 提取音频
            logger.info("Step 1/5: Extracting audio...")
            metadata = extract_audio(url)
            audio_path = metadata.audio_path
            logger.info(f"✓ Audio extracted: {metadata.title}")
            if metadata.duration:
                logger.info(f"  - Duration: {metadata.duration:.0f}s")

            # Step 2: 转录
            logger.info("Step 2/5: Transcribing audio...")
            segments = transcribe_audio(audio_path)
            raw_text = segments_to_text(segments)
            logger.info(f"✓ Transcribed: {len(raw_text)} chars, {len(segments)} segments")

            # Step 3: LLM 语义排版
            logger.info("Step 3/5: Formatting transcript with LLM...")
            llm_client = LLMClient()
            formatted_md = llm_client.format_transcript(raw_text, metadata.title)
            logger.info(f"✓ Formatted: {len(formatted_md)} chars")

            # Markdown → HTML
            import markdown2
            content_html = markdown2.markdown(formatted_md)

            # Step 4: AI 匹配目录
            logger.info("Step 4/5: Matching directory with AI...")
            target_directory = await self._match_directory(metadata.title)
            logger.info(f"✓ Target directory: {target_directory.directory.name}")

            # Step 5: 创建飞书文档
            logger.info("Step 5/5: Creating Feishu document...")
            doc_url = self.document_uploader.create_document(
                directory=target_directory.directory,
                title=metadata.title,
                content=raw_text,
                author=metadata.author,
                source_url=url,
                content_html=content_html,
            )

            if doc_url:
                logger.info("✓ Document created successfully!")
                logger.info("=" * 80)
                logger.info("SUCCESS!")
                logger.info(f"Document URL: {doc_url}")
                logger.info(f"Directory: {target_directory.directory.name}")
                logger.info("=" * 80)
                return doc_url
            else:
                logger.error("Failed to create document")
                return None

        except Exception as e:
            logger.error(f"Failed to process media: {str(e)}", exc_info=True)
            return None

        finally:
            if audio_path:
                cleanup_media_files(audio_path)

    async def process_article(self, url: str) -> Optional[str]:
        """
        处理单篇文章的完整流程

        Args:
            url: 文章URL

        Returns:
            飞书文档URL，失败返回None
        """
        logger.info("=" * 80)
        logger.info(f"Starting to process article: {url}")
        logger.info("=" * 80)

        try:
            # Step 1: 抓取文章
            logger.info("Step 1/7: Scraping article...")
            article = await self.scraper.scrape(url)
            logger.info(f"✓ Article scraped: {article.title}")
            logger.info(f"  - Images found: {len(article.images)}")

            # Step 2: 下载图片
            logger.info("Step 2/7: Downloading images...")
            downloaded_images = []
            # 飞书文档图片已由 scraper 预下载（需浏览器 cookies）
            pre_downloaded = getattr(article, 'local_image_map', {})
            if pre_downloaded:
                downloaded_images = [(url, path) for url, path in pre_downloaded.items()]
                logger.info(f"✓ {len(downloaded_images)} images pre-downloaded by scraper")

            # 下载未预下载的图片
            remaining_urls = [
                url for url in article.images
                if url not in pre_downloaded
            ]
            if remaining_urls:
                extra = self.image_downloader.download_images(remaining_urls)
                downloaded_images.extend(extra)
                logger.info(f"✓ Downloaded {len(extra)}/{len(remaining_urls)} additional images")

            if not downloaded_images and not article.images:
                logger.info("✓ No images to download")

            # Step 3: 上传图片到GitHub
            logger.info("Step 3/7: Uploading images to GitHub...")
            uploaded_images = []
            if downloaded_images:
                uploaded_images = self.github_uploader.batch_upload_images(downloaded_images)
                logger.info(f"✓ Uploaded {len(uploaded_images)} images to GitHub")
            else:
                logger.info("✓ No images to upload")

            # Step 4: 生成CDN链接
            logger.info("Step 4/7: Generating CDN URLs...")
            cdn_urls = []
            if uploaded_images:
                cdn_urls = self.cdn_generator.batch_generate_cdn_urls(uploaded_images)
                logger.info(f"✓ Generated {len(cdn_urls)} CDN URLs")
            else:
                logger.info("✓ No CDN URLs to generate")

            # Step 5: 替换内容中的图片URL
            logger.info("Step 5/7: Replacing image URLs in content...")
            final_content = article.content
            if cdn_urls:
                final_content = self.cdn_generator.replace_image_urls(article.content, cdn_urls)
                logger.info(f"✓ Replaced image URLs in content")
            else:
                logger.info("✓ No URLs to replace")

            # Step 6: 智能匹配目录
            logger.info("Step 6/7: Matching directory with AI...")
            target_directory = await self._match_directory(article.title)
            logger.info(f"✓ Target directory: {target_directory.directory.name}")

            # Step 7: 创建飞书文档
            logger.info("Step 7/7: Creating Feishu document...")

            # 构建原始图片URL和CDN URL列表
            original_images = [orig for orig, _ in cdn_urls] if cdn_urls else []
            cdn_url_list = [cdn for _, cdn in cdn_urls] if cdn_urls else []

            # 构建原始图片URL到本地路径的映射
            local_image_map = {orig: local for orig, local in downloaded_images} if downloaded_images else {}

            doc_url = self.document_uploader.create_document(
                directory=target_directory.directory,
                title=article.title,
                content=final_content,
                author=article.author,
                publish_date=article.publish_date,
                source_url=url,
                content_html=article.content_html,
                original_images=original_images,
                cdn_urls=cdn_url_list,
                local_image_map=local_image_map
            )

            if doc_url:
                logger.info(f"✓ Document created successfully!")
                logger.info(f"=" * 80)
                logger.info(f"SUCCESS!")
                logger.info(f"Document URL: {doc_url}")
                logger.info(f"Directory: {target_directory.directory.name}")
                logger.info(f"Similarity: {target_directory.similarity:.3f}")
                logger.info(f"Confidence: {target_directory.confidence}")
                logger.info(f"=" * 80)
                return doc_url
            else:
                logger.error("Failed to create document")
                return None

        except Exception as e:
            logger.error(f"Failed to process article: {str(e)}", exc_info=True)
            return None

        finally:
            # 清理下载的图片
            self.image_downloader.cleanup_downloads()

    async def _match_directory(self, article_title: str) -> MatchResult:
        """
        匹配目录（内部方法）

        Args:
            article_title: 文章标题

        Returns:
            匹配结果（保证有返回值）
        """
        # 获取可匹配的目录和兜底目录
        matchable_dirs, unorganized = self.directory_manager.get_matchable_directories()

        # 确保有兜底目录
        if not unorganized:
            logger.error("Unorganized folder not found! Cannot proceed.")
            raise ValueError(
                f"'{config.FEISHU_UNORGANIZED_FOLDER_NAME}' folder not found in knowledge space"
            )

        # 如果没有可匹配的目录，直接使用兜底目录
        if not matchable_dirs:
            logger.warning("No matchable directories found, using unorganized folder")
            return MatchResult(
                directory=unorganized,
                similarity=0.0,
                confidence='low'
            )

        # 使用 LLM 分类匹配（带兜底）
        return self.directory_matcher.match_directory_with_fallback(
            article_title=article_title,
            directories=matchable_dirs,
            fallback_directory=unorganized
        )


async def main():
    """主函数"""
    # 检查命令行参数
    if len(sys.argv) < 2:
        logger.error("Usage: python main.py <article_url>")
        sys.exit(1)

    url = sys.argv[1]

    # 验证URL
    if not url.startswith('http'):
        logger.error(f"Invalid URL: {url}")
        sys.exit(1)

    try:
        # 创建收集器
        collector = ArticleCollector()

        # 处理 URL（自动判断文章/媒体）
        doc_url = await collector.process_url(url)

        if doc_url:
            logger.info("Article processing completed successfully!")
            sys.exit(0)
        else:
            logger.error("Article processing failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
