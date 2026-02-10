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
from image_pipeline.github_uploader import GitHubUploader
from image_pipeline.jsdelivr_cdn import JsDelivrCDN
from matchers.jina_client import JinaClient, JinaAPIQuotaError
from matchers.similarity_matcher import SimilarityMatcher
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
        self.similarity_matcher = SimilarityMatcher()

        # 飞书组件
        self.auth_manager = AuthManager()
        self.directory_manager = DirectoryManager(self.auth_manager)
        self.document_uploader = DocumentUploader(self.auth_manager)

        logger.info("Article Collector initialized successfully")

    async def process_article(self, url: str) -> Optional[str]:
        """
        处理单篇文章的完整流程

        Args:
            url: 文章URL

        Returns:
            飞书文档URL，失败返回None
        """
        logger.info(f"=" * 80)
        logger.info(f"Starting to process article: {url}")
        logger.info(f"=" * 80)

        try:
            # Step 1: 抓取文章
            logger.info("Step 1/7: Scraping article...")
            article = await self.scraper.scrape(url)
            logger.info(f"✓ Article scraped: {article.title}")
            logger.info(f"  - Images found: {len(article.images)}")

            # Step 2: 下载图片
            logger.info("Step 2/7: Downloading images...")
            downloaded_images = []
            if article.images:
                downloaded_images = self.image_downloader.download_images(article.images)
                logger.info(f"✓ Downloaded {len(downloaded_images)}/{len(article.images)} images")
            else:
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

            doc_url = self.document_uploader.create_document(
                directory=target_directory.directory,
                title=article.title,
                content=final_content,
                author=article.author,
                publish_date=article.publish_date,
                source_url=url,
                content_html=article.content_html,
                original_images=original_images,
                cdn_urls=cdn_url_list
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
        # 初始化unorganized变量，避免异常情况下未定义
        unorganized = None

        try:
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

            # 为目录计算embeddings
            logger.info("Computing embeddings for directories...")
            matchable_dirs = self.similarity_matcher.compute_embeddings_for_directories(
                matchable_dirs
            )

            # 执行匹配（带兜底）
            match_result = self.similarity_matcher.match_directory_with_fallback(
                article_title=article_title,
                directories=matchable_dirs,
                fallback_directory=unorganized
            )

            return match_result

        except JinaAPIQuotaError:
            # API额度用尽，使用兜底目录
            logger.error("Jina API quota exceeded, using unorganized folder")
            if unorganized:
                return MatchResult(
                    directory=unorganized,
                    similarity=0.0,
                    confidence='low'
                )
            else:
                raise

        except Exception as e:
            logger.error(f"Error in directory matching: {str(e)}")
            # 任何错误都使用兜底目录
            if unorganized:
                return MatchResult(
                    directory=unorganized,
                    similarity=0.0,
                    confidence='low'
                )
            else:
                raise


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

        # 处理文章
        doc_url = await collector.process_article(url)

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
