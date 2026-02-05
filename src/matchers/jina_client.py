"""Jina AI Embeddings客户端"""
import requests
from typing import List, Optional
from utils.logger import logger
from utils.config import config
from utils.retry import retry_with_backoff


class JinaAPIQuotaError(Exception):
    """Jina API额度耗尽错误"""
    pass


class JinaClient:
    """Jina AI Embeddings API客户端"""

    def __init__(self):
        if not config.JINA_API_KEY:
            raise ValueError("JINA_API_KEY is not configured")

        self.api_key = config.JINA_API_KEY
        self.model = config.JINA_MODEL
        self.api_url = "https://api.jina.ai/v1/embeddings"

    @retry_with_backoff(
        max_retries=3,
        base_delay=2.0,
        exceptions=(requests.RequestException,)
    )
    def get_embedding(self, text: str) -> List[float]:
        """
        获取文本的embedding向量

        Args:
            text: 输入文本

        Returns:
            embedding向量

        Raises:
            JinaAPIQuotaError: API额度耗尽
            Exception: 其他错误
        """
        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.model,
                'input': [text],
                'encoding_format': 'float'
            }

            logger.debug(f"Requesting embedding for text: {text[:100]}...")

            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30
            )

            # 检查API额度
            if response.status_code == 429:
                logger.error("Jina API quota exceeded")
                raise JinaAPIQuotaError("Jina API quota exceeded")

            response.raise_for_status()

            data = response.json()

            # 提取embedding
            if 'data' in data and len(data['data']) > 0:
                embedding = data['data'][0]['embedding']
                logger.debug(f"Got embedding vector of dimension {len(embedding)}")
                return embedding
            else:
                raise ValueError("Invalid response format from Jina API")

        except JinaAPIQuotaError:
            raise
        except requests.RequestException as e:
            logger.error(f"Jina API request failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to get embedding: {str(e)}")
            raise

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量获取embedding向量

        Args:
            texts: 文本列表

        Returns:
            embedding向量列表

        Raises:
            JinaAPIQuotaError: API额度耗尽
            Exception: 其他错误
        """
        if not texts:
            return []

        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.model,
                'input': texts,
                'encoding_format': 'float'
            }

            logger.info(f"Requesting embeddings for {len(texts)} texts...")

            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=60
            )

            # 检查API额度
            if response.status_code == 429:
                logger.error("Jina API quota exceeded")
                raise JinaAPIQuotaError("Jina API quota exceeded")

            response.raise_for_status()

            data = response.json()

            # 提取embeddings
            if 'data' in data:
                embeddings = [item['embedding'] for item in data['data']]
                logger.info(f"Got {len(embeddings)} embedding vectors")
                return embeddings
            else:
                raise ValueError("Invalid response format from Jina API")

        except JinaAPIQuotaError:
            raise
        except requests.RequestException as e:
            logger.error(f"Jina API batch request failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to get batch embeddings: {str(e)}")
            raise
