"""jsDelivr CDN链接生成器"""
from typing import List, Tuple
from urllib.parse import quote
from ..utils.logger import logger
from ..utils.config import config


class JsDelivrCDN:
    """jsDelivr CDN链接生成器"""

    def __init__(self):
        if not config.GITHUB_REPO:
            raise ValueError("GITHUB_REPO is not configured")

        self.repo_name = config.GITHUB_REPO
        self.branch = config.GITHUB_BRANCH

    def generate_cdn_url(self, github_path: str) -> str:
        """
        根据GitHub路径生成jsDelivr CDN链接

        Args:
            github_path: GitHub仓库中的文件路径（例如：images/2026/02/img_001.jpg）

        Returns:
            jsDelivr CDN URL

        示例:
            输入: "images/2026/02/img_001.jpg"
            输出: "https://cdn.jsdelivr.net/gh/username/repo@main/images/2026/02/img_001.jpg"
        """
        # URL编码路径（处理中文文件名等特殊字符）
        encoded_path = quote(github_path)

        # 生成jsDelivr CDN链接
        # 格式: https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{file}
        cdn_url = f"https://cdn.jsdelivr.net/gh/{self.repo_name}@{self.branch}/{encoded_path}"

        logger.debug(f"Generated CDN URL: {cdn_url}")
        return cdn_url

    def batch_generate_cdn_urls(
        self,
        uploaded_images: List[Tuple[str, str]]
    ) -> List[Tuple[str, str]]:
        """
        批量生成CDN链接

        Args:
            uploaded_images: [(原始URL, GitHub路径), ...] 列表

        Returns:
            [(原始URL, CDN链接), ...] 列表
        """
        if not uploaded_images:
            logger.info("No images to generate CDN URLs")
            return []

        logger.info(f"Generating CDN URLs for {len(uploaded_images)} images...")
        cdn_urls = []

        for original_url, github_path in uploaded_images:
            cdn_url = self.generate_cdn_url(github_path)
            cdn_urls.append((original_url, cdn_url))

        logger.info(f"Generated {len(cdn_urls)} CDN URLs")
        return cdn_urls

    def replace_image_urls(self, content: str, url_mapping: List[Tuple[str, str]]) -> str:
        """
        替换内容中的图片URL为CDN链接

        Args:
            content: 文章内容（Markdown格式）
            url_mapping: [(原始URL, CDN链接), ...] 映射表

        Returns:
            替换后的内容
        """
        if not url_mapping:
            return content

        logger.info(f"Replacing {len(url_mapping)} image URLs in content...")
        modified_content = content

        for original_url, cdn_url in url_mapping:
            # 替换Markdown图片语法中的URL
            # ![alt](original_url) -> ![alt](cdn_url)
            modified_content = modified_content.replace(original_url, cdn_url)

        return modified_content
