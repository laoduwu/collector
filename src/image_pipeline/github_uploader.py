"""GitHub图片上传器"""
import os
import base64
from datetime import datetime
from typing import Tuple, Optional
from github import Github, GithubException, Repository
from utils.logger import logger
from utils.config import config
from utils.retry import retry_with_backoff


class GitHubUploader:
    """GitHub图片上传器"""

    def __init__(self):
        if not config.GH_TOKEN:
            raise ValueError("GH_TOKEN is not configured")
        if not config.IMAGE_REPO:
            raise ValueError("IMAGE_REPO is not configured")

        self.github = Github(config.GH_TOKEN)
        self.repo_name = config.IMAGE_REPO
        self.branch = config.IMAGE_BRANCH
        self._repo: Optional[Repository.Repository] = None

    @property
    def repo(self) -> Repository.Repository:
        """获取GitHub仓库对象（懒加载）"""
        if self._repo is None:
            try:
                self._repo = self.github.get_repo(self.repo_name)
                logger.info(f"Connected to GitHub repo: {self.repo_name}")
            except GithubException as e:
                logger.error(f"Failed to access GitHub repo {self.repo_name}: {str(e)}")
                raise

        return self._repo

    def _generate_github_path(self, filename: str) -> str:
        """
        生成GitHub仓库中的文件路径

        Args:
            filename: 文件名

        Returns:
            GitHub路径（例如：images/2026/02/filename.jpg）
        """
        now = datetime.now()
        year = now.strftime('%Y')
        month = now.strftime('%m')

        return f"images/{year}/{month}/{filename}"

    @retry_with_backoff(max_retries=3, base_delay=2.0, exceptions=(GithubException,))
    def upload_image(self, local_path: str, original_url: str) -> str:
        """
        上传图片到GitHub仓库

        Args:
            local_path: 本地图片路径
            original_url: 原始图片URL（用于commit消息）

        Returns:
            GitHub中的文件路径

        Raises:
            Exception: 上传失败
        """
        try:
            # 读取文件内容
            with open(local_path, 'rb') as f:
                content = f.read()

            # 生成GitHub路径
            filename = os.path.basename(local_path)
            github_path = self._generate_github_path(filename)

            # 检查文件是否已存在
            try:
                existing_file = self.repo.get_contents(github_path, ref=self.branch)
                logger.info(f"File already exists in GitHub: {github_path}")
                return github_path
            except GithubException as e:
                if e.status != 404:
                    raise
                # 文件不存在，继续上传

            # 创建commit消息
            commit_message = f"Add image from {original_url[:100]}"

            # 上传文件
            logger.info(f"Uploading to GitHub: {github_path}")
            result = self.repo.create_file(
                path=github_path,
                message=commit_message,
                content=content,
                branch=self.branch
            )

            logger.info(f"Successfully uploaded to GitHub: {github_path}")
            return github_path

        except GithubException as e:
            logger.error(f"GitHub API error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to upload {local_path}: {str(e)}")
            raise

    def batch_upload_images(self, image_paths: list[Tuple[str, str]]) -> list[Tuple[str, str]]:
        """
        批量上传图片

        Args:
            image_paths: [(原始URL, 本地路径), ...] 列表

        Returns:
            [(原始URL, GitHub路径), ...] 列表
        """
        if not image_paths:
            logger.info("No images to upload")
            return []

        logger.info(f"Starting to upload {len(image_paths)} images to GitHub...")
        uploaded = []

        for original_url, local_path in image_paths:
            try:
                github_path = self.upload_image(local_path, original_url)
                uploaded.append((original_url, github_path))
            except Exception as e:
                logger.error(f"Failed to upload {local_path}: {str(e)}")
                # 继续处理其他图片
                continue

        logger.info(f"Successfully uploaded {len(uploaded)}/{len(image_paths)} images to GitHub")
        return uploaded

    def delete_image(self, github_path: str) -> bool:
        """
        删除GitHub中的图片（可选功能）

        Args:
            github_path: GitHub中的文件路径

        Returns:
            是否删除成功
        """
        try:
            file = self.repo.get_contents(github_path, ref=self.branch)
            self.repo.delete_file(
                path=github_path,
                message=f"Delete image: {github_path}",
                sha=file.sha,
                branch=self.branch
            )
            logger.info(f"Deleted image from GitHub: {github_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete {github_path}: {str(e)}")
            return False
