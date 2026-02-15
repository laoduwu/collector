"""相似度匹配器"""
import math
from typing import List, Optional
from .types import Directory, MatchResult
from .jina_client import JinaClient, JinaAPIQuotaError
from utils.logger import logger
from utils.config import config


class SimilarityMatcher:
    """语义相似度匹配器"""

    def __init__(self):
        self.jina_client = JinaClient()
        self.threshold = config.SIMILARITY_THRESHOLD

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        计算两个向量的余弦相似度

        Args:
            vec1: 向量1
            vec2: 向量2

        Returns:
            余弦相似度（0-1之间）
        """
        if len(vec1) != len(vec2):
            raise ValueError("Vectors must have the same dimension")

        # 计算点积
        dot_product = sum(a * b for a, b in zip(vec1, vec2))

        # 计算模长
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))

        # 避免除零
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        # 余弦相似度
        similarity = dot_product / (magnitude1 * magnitude2)

        return max(0.0, min(1.0, similarity))  # 确保在[0,1]范围内

    def _determine_confidence(self, similarity: float) -> str:
        """
        根据相似度确定置信度

        Args:
            similarity: 相似度分数

        Returns:
            置信度等级（high/medium/low）
        """
        if similarity >= 0.85:
            return 'high'
        elif similarity >= 0.70:
            return 'medium'
        else:
            return 'low'

    def compute_embeddings_for_directories(self, directories: List[Directory]) -> List[Directory]:
        """
        为目录计算embedding向量

        Args:
            directories: 目录列表

        Returns:
            带embedding的目录列表
        """
        if not directories:
            return []

        logger.info(f"Computing embeddings for {len(directories)} directories...")

        try:
            # 提取目录名称
            dir_names = [d.name for d in directories]

            # 批量获取embeddings
            embeddings = self.jina_client.get_embeddings_batch(dir_names)

            # 为每个目录设置embedding
            for directory, embedding in zip(directories, embeddings):
                directory.embedding = embedding

            logger.info(f"Successfully computed embeddings for {len(directories)} directories")
            return directories

        except JinaAPIQuotaError:
            logger.error("Jina API quota exceeded while computing directory embeddings")
            raise
        except Exception as e:
            logger.error(f"Failed to compute directory embeddings: {str(e)}")
            raise

    def match_directory(
        self,
        article_title: str,
        directories: List[Directory]
    ) -> Optional[MatchResult]:
        """
        为文章标题匹配最合适的目录

        Args:
            article_title: 文章标题
            directories: 目录列表（必须已包含embedding）

        Returns:
            匹配结果，如果相似度低于阈值则返回None

        Raises:
            JinaAPIQuotaError: API额度耗尽
        """
        if not directories:
            logger.warning("No directories to match")
            return None

        # 确保所有目录都有embedding
        if not all(d.embedding for d in directories):
            logger.error("Not all directories have embeddings")
            raise ValueError("All directories must have embeddings computed")

        try:
            # 获取文章标题的embedding
            logger.info(f"Getting embedding for article title: {article_title}")
            title_embedding = self.jina_client.get_embedding(article_title)

            # 计算与每个目录的相似度
            similarities = []
            for directory in directories:
                if directory.embedding:
                    similarity = self._cosine_similarity(title_embedding, directory.embedding)
                    similarities.append((directory, similarity))

            # 按相似度排序
            similarities.sort(key=lambda x: x[1], reverse=True)

            # 输出所有目录的匹配分数
            logger.info("Similarity scores for all directories:")
            for directory, sim in similarities:
                logger.info(f"  {directory.name}: {sim:.3f}")

            # 获取最佳匹配
            best_directory, best_similarity = similarities[0]

            logger.info(
                f"Best match: '{best_directory.name}' with similarity {best_similarity:.3f}"
            )

            # 判断是否超过阈值
            if best_similarity >= self.threshold:
                confidence = self._determine_confidence(best_similarity)
                match_result = MatchResult(
                    directory=best_directory,
                    similarity=best_similarity,
                    confidence=confidence
                )
                logger.info(f"Match successful: {match_result}")
                return match_result
            else:
                logger.info(
                    f"Similarity {best_similarity:.3f} below threshold {self.threshold}, "
                    "no match found"
                )
                return None

        except JinaAPIQuotaError:
            logger.error("Jina API quota exceeded during matching")
            raise
        except Exception as e:
            logger.error(f"Failed to match directory: {str(e)}")
            raise

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
                # 相似度低于阈值，使用兜底目录
                logger.info(f"Using fallback directory: {fallback_directory.name}")
                return MatchResult(
                    directory=fallback_directory,
                    similarity=0.0,
                    confidence='low'
                )

        except JinaAPIQuotaError:
            # API额度耗尽，使用兜底目录
            logger.warning("Jina API quota exceeded, using fallback directory")
            return MatchResult(
                directory=fallback_directory,
                similarity=0.0,
                confidence='low'
            )
        except Exception as e:
            # 任何其他错误，使用兜底目录
            logger.error(f"Matching failed with error: {str(e)}, using fallback directory")
            return MatchResult(
                directory=fallback_directory,
                similarity=0.0,
                confidence='low'
            )
