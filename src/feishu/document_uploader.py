"""飞书文档上传器"""
from typing import Optional
import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    CreateDocumentResponse
)
from .auth_manager import AuthManager
from ..matchers.types import Directory
from ..utils.logger import logger


class DocumentUploader:
    """飞书文档上传器"""

    def __init__(self, auth_manager: AuthManager):
        self.auth_manager = auth_manager
        self.client = auth_manager.client

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
        在指定目录创建文档

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
            # 构建文档内容
            doc_content = self._build_document_content(
                title=title,
                content=content,
                author=author,
                publish_date=publish_date,
                source_url=source_url
            )

            # 构建请求
            request = CreateDocumentRequest.builder() \
                .request_body(
                    CreateDocumentRequestBody.builder()
                    .folder_token(directory.node_token)
                    .title(title)
                    .content(doc_content)
                    .build()
                ) \
                .build()

            # 发起请求
            response: CreateDocumentResponse = self.client.docx.v1.document.create(request)

            if not response.success():
                logger.error(
                    f"Failed to create document: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                raise Exception(f"Failed to create Feishu document: {response.msg}")

            # 获取文档URL
            doc_url = response.data.document.url if response.data.document else None

            if doc_url:
                logger.info(f"Document created successfully: {doc_url}")
            else:
                logger.warning("Document created but URL not available")

            return doc_url

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
