"""LLM 目录匹配器"""
from typing import List, Optional
from .types import Directory, MatchResult
from .llm_client import LLMClient
from utils.logger import logger
from utils.config import config


class DirectoryMatcher:
    """基于 LLM 的目录匹配器"""

    def __init__(self):
        self.llm_client = LLMClient()

    def match_directory(
        self,
        article_title: str,
        directories: List[Directory]
    ) -> Optional[MatchResult]:
        """
        使用 LLM 为文章标题匹配最合适的目录

        Args:
            article_title: 文章标题
            directories: 目录列表

        Returns:
            匹配结果，无匹配则返回None
        """
        if not directories:
            logger.warning("No directories to match")
            return None

        dir_names = [d.name for d in directories]
        dir_map = {d.name: d for d in directories}

        result = self.llm_client.classify_article(
            article_title=article_title,
            directory_names=dir_names,
            fallback_name=config.FEISHU_UNORGANIZED_FOLDER_NAME
        )

        logger.info(
            f"Classification result: directory={result.directory_name}, "
            f"confidence={result.confidence}, reason={result.reason}"
        )

        if result.directory_name and result.directory_name in dir_map:
            return MatchResult(
                directory=dir_map[result.directory_name],
                similarity=1.0,
                confidence=result.confidence
            )

        return None

    def match_directory_with_fallback(
        self,
        article_title: str,
        directories: List[Directory],
        fallback_directory: Directory
    ) -> MatchResult:
        """
        匹配目录，失败时返回兜底目录

        Args:
            article_title: 文章标题
            directories: 目录列表
            fallback_directory: 兜底目录（"待整理"）

        Returns:
            匹配结果（保证有返回值）
        """
        try:
            match_result = self.match_directory(article_title, directories)

            if match_result:
                return match_result
            else:
                logger.info(f"Using fallback directory: {fallback_directory.name}")
                return MatchResult(
                    directory=fallback_directory,
                    similarity=0.0,
                    confidence='low'
                )

        except Exception as e:
            logger.error(f"Matching failed with error: {str(e)}, using fallback directory")
            return MatchResult(
                directory=fallback_directory,
                similarity=0.0,
                confidence='low'
            )
