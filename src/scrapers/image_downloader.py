"""图片下载器"""
import os
import hashlib
from typing import List, Tuple
import requests
from utils.logger import logger
from utils.config import config
from utils.retry import retry_with_backoff


class ImageDownloader:
    """图片下载器"""

    def __init__(self):
        config.ensure_directories()
        self.downloads_dir = config.DOWNLOADS_DIR

    def _generate_filename(self, image_url: str, index: int) -> str:
        """
        生成唯一的图片文件名

        Args:
            image_url: 图片URL
            index: 图片索引

        Returns:
            文件名
        """
        # 使用URL的hash作为文件名，确保唯一性
        url_hash = hashlib.md5(image_url.encode()).hexdigest()

        # 尝试从URL中提取扩展名
        ext = '.jpg'  # 默认扩展名
        if '.' in image_url.split('/')[-1]:
            possible_ext = image_url.split('/')[-1].split('.')[-1].lower()
            # 验证是否为常见图片格式
            if possible_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']:
                ext = f'.{possible_ext}'

        return f"img_{index}_{url_hash[:12]}{ext}"

    @retry_with_backoff(max_retries=3, base_delay=2.0)
    def _download_single_image(self, image_url: str, save_path: str) -> bool:
        """
        下载单张图片

        Args:
            image_url: 图片URL
            save_path: 保存路径

        Returns:
            是否下载成功
        """
        try:
            # 设置请求头，模拟浏览器行为
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': image_url,  # 对于微信图片很重要
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            }

            # 发起请求
            response = requests.get(
                image_url,
                headers=headers,
                timeout=30,
                stream=True
            )
            response.raise_for_status()

            # 检查内容类型
            content_type = response.headers.get('Content-Type', '')
            if not content_type.startswith('image/'):
                logger.warning(f"URL is not an image: {image_url} (Content-Type: {content_type})")
                return False

            # 保存图片
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            file_size = os.path.getsize(save_path)
            logger.debug(f"Downloaded image: {os.path.basename(save_path)} ({file_size} bytes)")
            return True

        except requests.RequestException as e:
            logger.warning(f"Failed to download image {image_url}: {str(e)}")
            # 删除可能部分下载的文件
            if os.path.exists(save_path):
                os.remove(save_path)
            raise

    def download_images(self, image_urls: List[str]) -> List[Tuple[str, str]]:
        """
        下载多张图片

        Args:
            image_urls: 图片URL列表

        Returns:
            成功下载的图片列表 [(原始URL, 本地路径), ...]
        """
        if not image_urls:
            logger.info("No images to download")
            return []

        logger.info(f"Starting to download {len(image_urls)} images...")
        downloaded = []

        for index, image_url in enumerate(image_urls):
            try:
                # 生成文件名
                filename = self._generate_filename(image_url, index)
                save_path = os.path.join(self.downloads_dir, filename)

                # 如果文件已存在，跳过下载
                if os.path.exists(save_path):
                    logger.debug(f"Image already exists: {filename}")
                    downloaded.append((image_url, save_path))
                    continue

                # 下载图片
                if self._download_single_image(image_url, save_path):
                    downloaded.append((image_url, save_path))

            except Exception as e:
                logger.error(f"Failed to download image {image_url}: {str(e)}")
                continue

        logger.info(f"Successfully downloaded {len(downloaded)}/{len(image_urls)} images")
        return downloaded

    def cleanup_downloads(self):
        """清理下载目录"""
        try:
            if os.path.exists(self.downloads_dir):
                for filename in os.listdir(self.downloads_dir):
                    file_path = os.path.join(self.downloads_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                logger.info("Cleaned up downloads directory")
        except Exception as e:
            logger.warning(f"Failed to cleanup downloads: {str(e)}")
