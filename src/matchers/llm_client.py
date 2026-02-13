"""LLM 目录分类客户端"""
import json
import requests
from typing import List, Optional
from dataclasses import dataclass
from utils.logger import logger
from utils.config import config
from utils.retry import retry_with_backoff


@dataclass(frozen=True)
class ClassificationResult:
    """分类结果"""
    directory_name: Optional[str]  # 匹配的目录名，None表示无匹配
    confidence: str  # high/medium/low
    reason: str  # LLM给出的分类理由


class LLMClient:
    """LLM 目录分类客户端（OpenAI兼容接口）"""

    def __init__(self):
        if not config.LLM_API_KEY:
            raise ValueError("LLM_API_KEY is not configured")

        self.api_key = config.LLM_API_KEY
        self.base_url = config.LLM_BASE_URL.rstrip('/')
        self.model = config.LLM_MODEL

    @retry_with_backoff(
        max_retries=3,
        base_delay=30.0,
        exceptions=(requests.RequestException,)
    )
    def classify_article(
        self,
        article_title: str,
        directory_names: List[str],
        fallback_name: str
    ) -> ClassificationResult:
        """
        使用 LLM 将文章标题分类到最匹配的目录

        Args:
            article_title: 文章标题
            directory_names: 可选目录名列表
            fallback_name: 兜底目录名称

        Returns:
            分类结果
        """
        dir_list = "\n".join(f"- {name}" for name in directory_names)

        prompt = f"""你是一个文章分类助手。请根据文章标题，从以下目录列表中选择最匹配的一个目录。

文章标题：{article_title}

可选目录：
{dir_list}

分类规则：
1. 根据文章标题的主题和语义，选择最相关的目录
2. 需要运用你的知识来理解标题中的专有名词（如产品名、技术术语等）
3. 如果确实没有合适的目录，返回"{fallback_name}"
4. 只有在完全无法判断时才选择"{fallback_name}"

请严格按以下JSON格式返回，不要包含其他内容：
{{"directory": "目录名", "confidence": "high/medium/low", "reason": "简短理由"}}"""

        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.model,
                'messages': [
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0
            }

            logger.info(f"Classifying article: {article_title}")
            logger.debug(f"Available directories: {directory_names}")

            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code == 429:
                logger.error("LLM API rate limited")
                raise requests.RequestException("LLM API rate limited")

            response.raise_for_status()

            data = response.json()
            content = data['choices'][0]['message']['content'].strip()

            logger.info(f"LLM response: {content}")

            return self._parse_response(content, directory_names, fallback_name)

        except requests.RequestException:
            raise
        except Exception as e:
            logger.error(f"Failed to classify article: {str(e)}")
            raise

    @retry_with_backoff(
        max_retries=3,
        base_delay=30.0,
        exceptions=(requests.RequestException,)
    )
    def format_transcript(self, raw_text: str, title: str) -> str:
        """
        调用 LLM 对转录文本做语义排版

        Args:
            raw_text: 原始转录文本
            title: 媒体标题

        Returns:
            Markdown 格式的排版文本
        """
        # 截断过长文本，避免超出上下文限制
        max_chars = 50000
        truncated = raw_text[:max_chars] if len(raw_text) > max_chars else raw_text

        prompt = f"""你是一个专业的文本编辑。请对以下语音转录文本进行语义排版。

标题：{title}

转录原文：
{truncated}

排版要求：
1. 将文本组织成有逻辑的段落
2. 添加合适的小标题（用 ## 标记）
3. 修正明显的语音识别错误（错别字、断句不当等）
4. 保留原文的所有信息，不要删减内容
5. 输出纯 Markdown 格式，不要用代码块包裹
6. 第一行用 # 标记标题"""

        try:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            payload = {
                'model': self.model,
                'messages': [
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.3
            }

            logger.info(f"Formatting transcript: {title} ({len(raw_text)} chars)")

            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120  # 排版可能较慢
            )

            if response.status_code == 429:
                raise requests.RequestException("LLM API rate limited")

            response.raise_for_status()

            data = response.json()
            content = data['choices'][0]['message']['content'].strip()

            logger.info(f"Transcript formatted: {len(content)} chars")
            return content

        except requests.RequestException:
            raise
        except Exception as e:
            logger.error(f"Failed to format transcript: {str(e)}")
            raise

    def _parse_response(
        self,
        content: str,
        directory_names: List[str],
        fallback_name: str
    ) -> ClassificationResult:
        """解析 LLM 返回的 JSON 结果"""
        try:
            # 尝试提取 JSON（处理可能的 markdown 代码块包裹）
            if '```' in content:
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()

            result = json.loads(content)

            directory = result.get('directory', '').strip()
            confidence = result.get('confidence', 'low').strip()
            reason = result.get('reason', '').strip()

            # 验证目录名有效
            if directory in directory_names:
                return ClassificationResult(
                    directory_name=directory,
                    confidence=confidence,
                    reason=reason
                )
            elif directory == fallback_name:
                return ClassificationResult(
                    directory_name=None,
                    confidence='low',
                    reason=reason
                )
            else:
                logger.warning(
                    f"LLM returned unknown directory: '{directory}', using fallback"
                )
                return ClassificationResult(
                    directory_name=None,
                    confidence='low',
                    reason=f"LLM returned invalid directory: {directory}"
                )

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse LLM response: {content}, error: {e}")
            return ClassificationResult(
                directory_name=None,
                confidence='low',
                reason=f"Failed to parse LLM response"
            )
