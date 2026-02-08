"""飞书文档上传器"""
from typing import Optional, List
import lark_oapi as lark
from lark_oapi.api.wiki.v2 import (
    CreateSpaceNodeRequest,
    Node
)
from lark_oapi.api.docx.v1 import (
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    Block,
    Text,
    TextElement,
    TextRun,
    TextStyle,
    Divider,
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
            # space_id 必须是字符串格式
            space_id_str = str(self.space_id)
            logger.info(f"Creating wiki node with space_id={space_id_str}, parent={directory.node_token}")

            request = CreateSpaceNodeRequest.builder() \
                .space_id(space_id_str) \
                .request_body(
                    Node.builder()
                    .obj_type("docx")  # 创建新版文档
                    .node_type("origin")  # 原创节点
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

                # 使用 docx block API 添加内容
                self._add_content_to_document(node.obj_token, doc_content)

                return doc_url
            else:
                logger.warning("Wiki node created but node info not available")
                return None

        except Exception as e:
            logger.error(f"Error creating document: {str(e)}")
            raise

    def _add_content_to_document(self, document_id: str, content: str) -> bool:
        """
        向文档添加内容

        Args:
            document_id: 文档ID (obj_token)
            content: 要添加的内容（纯文本，按段落分割）

        Returns:
            是否成功
        """
        logger.info(f"Adding content to document: {document_id}")

        try:
            # 将内容按段落分割
            paragraphs = content.strip().split('\n')

            # 构建block列表
            blocks = []
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                # 限制单个段落长度（飞书API限制）
                max_text_len = 10000
                if len(para) > max_text_len:
                    para = para[:max_text_len] + "..."

                # 判断是否是标题
                if para.startswith('# '):
                    # 一级标题 - 跳过，因为文档已有标题
                    continue
                elif para.startswith('## '):
                    # 二级标题
                    block = self._create_heading_block(para[3:], block_type=4)  # heading2
                elif para.startswith('### '):
                    # 三级标题
                    block = self._create_heading_block(para[4:], block_type=5)  # heading3
                elif para.startswith('---'):
                    # 分割线
                    block = Block.builder().block_type(22).divider(Divider.builder().build()).build()
                elif para.startswith('**') and para.endswith('**'):
                    # 粗体行作为普通文本
                    block = self._create_text_block(para[2:-2])
                else:
                    # 普通段落
                    block = self._create_text_block(para)

                blocks.append(block)

            if not blocks:
                logger.warning("No content blocks to add")
                return True

            logger.info(f"Prepared {len(blocks)} content blocks to add")

            # 分批添加blocks，每批最多10个
            batch_size = 10
            total_added = 0
            current_index = 0

            for i in range(0, len(blocks), batch_size):
                batch = blocks[i:i + batch_size]
                logger.info(f"Adding batch {i // batch_size + 1}: {len(batch)} blocks")

                request = CreateDocumentBlockChildrenRequest.builder() \
                    .document_id(document_id) \
                    .block_id(document_id) \
                    .document_revision_id(-1) \
                    .request_body(
                        CreateDocumentBlockChildrenRequestBody.builder()
                        .children(batch)
                        .index(current_index)
                        .build()
                    ) \
                    .build()

                response = self.client.docx.v1.document_block_children.create(request)

                if not response.success():
                    logger.error(
                        f"Failed to add content batch: code={response.code}, "
                        f"msg={response.msg}, log_id={response.get_log_id()}"
                    )
                    # 继续尝试添加后续批次
                    continue

                total_added += len(batch)
                current_index += len(batch)

            if total_added > 0:
                logger.info(f"Successfully added {total_added}/{len(blocks)} content blocks")
                return True
            else:
                logger.error("Failed to add any content blocks")
                return False

        except Exception as e:
            logger.error(f"Error adding content to document: {str(e)}")
            return False

    def _create_text_block(self, text: str, bold: bool = False) -> Block:
        """创建文本块"""
        # 清理文本中的特殊字符
        text = self._clean_text(text)

        text_element = TextElement.builder() \
            .text_run(
                TextRun.builder()
                .content(text)
                .build()
            ) \
            .build()

        text_obj = Text.builder() \
            .style(TextStyle.builder().build()) \
            .elements([text_element]) \
            .build()

        return Block.builder() \
            .block_type(2) \
            .text(text_obj) \
            .build()

    def _clean_text(self, text: str) -> str:
        """清理文本中的特殊字符"""
        if not text:
            return ""
        # 移除零宽字符和其他不可见字符
        import re
        # 移除零宽字符
        text = re.sub(r'[\u200b\u200c\u200d\ufeff\u00ad]', '', text)
        # 移除其他控制字符（保留换行和制表符）
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        return text.strip()

    def _create_heading_block(self, text: str, block_type: int = 4) -> Block:
        """
        创建标题块

        Args:
            text: 标题文本
            block_type: 3=heading1, 4=heading2, 5=heading3, ...
        """
        # 清理文本
        text = self._clean_text(text)

        text_element = TextElement.builder() \
            .text_run(
                TextRun.builder()
                .content(text)
                .build()
            ) \
            .build()

        text_obj = Text.builder() \
            .style(TextStyle.builder().build()) \
            .elements([text_element]) \
            .build()

        # 根据block_type设置对应的heading属性
        builder = Block.builder().block_type(block_type)

        if block_type == 3:
            builder.heading1(text_obj)
        elif block_type == 4:
            builder.heading2(text_obj)
        elif block_type == 5:
            builder.heading3(text_obj)
        elif block_type == 6:
            builder.heading4(text_obj)
        else:
            builder.text(text_obj)

        return builder.build()

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
