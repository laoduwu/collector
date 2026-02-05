"""飞书文档上传器"""
from typing import Optional
import lark_oapi as lark
from lark_oapi.api.wiki.v2 import (
    CreateSpaceNodeRequest,
    Node
)
from .auth_manager import AuthManager
from matchers.types import Directory
from utils.logger import logger
from utils.config import config


class DocumentUploader:
    """飞书文档上传器"""

    def __init__(self, auth_manager: AuthManager):
        self.auth_manager = auth_manager
        self.client = auth_manager.client
        self.space_id = config.FEISHU_KNOWLEDGE_SPACE_ID

    def _build_document_content(
        self,
        title: str,
        content: str,
        author: Optional[str] = None,
        publish_date: Optional[str] = None,
        source_url: Optional[str] = None
    ) -> str:
        """
        构建飞书文档内容（Markdown格式）

        Args:
            title: 文章标题
            content: 文章内容
            author: 作者
            publish_date: 发布日期
            source_url: 原文链接

        Returns:
            格式化的Markdown内容
        """
        # 构建元信息
        meta_info = []
        if author:
            meta_info.append(f"**作者**: {author}")
        if publish_date:
            meta_info.append(f"**发布日期**: {publish_date}")
        if source_url:
            meta_info.append(f"**原文链接**: {source_url}")

        # 组装完整内容
        parts = [f"# {title}"]

        if meta_info:
            parts.append("\n---\n")
            parts.extend(meta_info)
            parts.append("\n---\n")

        parts.append(f"\n{content}\n")

        return "\n".join(parts)

    def create_document(
        self,
        directory: Directory,
        title: str,
        content: str,
        author: Optional[str] = None,
        publish_date: Optional[str] = None,
        source_url: Optional[str] = None
    ) -> Optional[str]:
        """
        在指定目录创建文档（使用知识库 wiki API）

        Args:
            directory: 目标目录
            title: 文章标题
            content: 文章内容（可包含CDN图片链接）
            author: 作者
            publish_date: 发布日期
            source_url: 原文链接

        Returns:
            文档URL，失败返回None

        Raises:
            Exception: 创建失败
        """
        logger.info(f"Creating document '{title}' in directory '{directory.name}'")

        try:
            # 构建文档内容（用于后续添加到文档）
            doc_content = self._build_document_content(
                title=title,
                content=content,
                author=author,
                publish_date=publish_date,
                source_url=source_url
            )

            # 使用 wiki API 创建知识库节点
            request = CreateSpaceNodeRequest.builder() \
                .space_id(self.space_id) \
                .request_body(
                    Node.builder()
                    .obj_type("docx")  # 创建新版文档
                    .parent_node_token(directory.node_token)
                    .title(title)
                    .build()
                ) \
                .build()

            # 发起请求
            response = self.client.wiki.v2.space_node.create(request)

            if not response.success():
                logger.error(
                    f"Failed to create wiki node: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                raise Exception(f"Failed to create wiki node: {response.msg}")

            # 获取创建的节点信息
            node = response.data.node if response.data else None
            if node:
                # 构建文档 URL
                doc_url = f"https://feishu.cn/wiki/{node.node_token}"
                logger.info(f"Wiki node created successfully: {doc_url}")
                logger.info(f"  - node_token: {node.node_token}")
                logger.info(f"  - obj_token: {node.obj_token}")

                # TODO: 后续可以使用 docx block API 添加内容
                # 目前先创建空文档，内容通过标题体现

                return doc_url
            else:
                logger.warning("Wiki node created but node info not available")
                return None

        except Exception as e:
            logger.error(f"Error creating document: {str(e)}")
            raise

    def create_document_simple(
        self,
        directory_token: str,
        title: str,
        content: str
    ) -> Optional[str]:
        """
        简化版文档创建（仅需目录token）

        Args:
            directory_token: 目录节点token
            title: 标题
            content: 内容

        Returns:
            文档URL
        """
        # 创建临时Directory对象
        temp_directory = Directory(
            node_token=directory_token,
            name="unknown",
            is_leaf=True
        )

        return self.create_document(
            directory=temp_directory,
            title=title,
            content=content
        )
