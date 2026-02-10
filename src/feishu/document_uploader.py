"""飞书文档上传器"""
import io
import re
import requests
from typing import Optional, List, Dict
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
    TextElementStyle,
    Divider,
    Image,
)
from lark_oapi.api.drive.v1 import (
    UploadAllMediaRequest,
    UploadAllMediaRequestBody,
)
from .auth_manager import AuthManager
from .html_parser import HTMLToBlocksParser, ContentBlock, build_image_url_map
from matchers.types import Directory
from utils.logger import logger
from utils.config import config


class DocumentUploader:
    """飞书文档上传器"""

    def __init__(self, auth_manager: AuthManager):
        self.auth_manager = auth_manager
        self.client = auth_manager.client
        self.space_id = config.FEISHU_KNOWLEDGE_SPACE_ID

    def create_document(
        self,
        directory: Directory,
        title: str,
        content: str,
        author: Optional[str] = None,
        publish_date: Optional[str] = None,
        source_url: Optional[str] = None,
        content_html: Optional[str] = None,
        original_images: Optional[List[str]] = None,
        cdn_urls: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        在指定目录创建文档（使用知识库 wiki API）

        Args:
            directory: 目标目录
            title: 文章标题
            content: 文章纯文本内容
            author: 作者
            publish_date: 发布日期
            source_url: 原文链接
            content_html: HTML格式内容（保留格式）
            original_images: 原始图片URL列表
            cdn_urls: CDN图片URL列表

        Returns:
            文档URL，失败返回None

        Raises:
            Exception: 创建失败
        """
        logger.info(f"Creating document '{title}' in directory '{directory.name}'")

        try:
            # 使用 wiki API 创建知识库节点
            space_id_str = str(self.space_id)
            logger.info(f"Creating wiki node with space_id={space_id_str}, parent={directory.node_token}")

            request = CreateSpaceNodeRequest.builder() \
                .space_id(space_id_str) \
                .request_body(
                    Node.builder()
                    .obj_type("docx")
                    .node_type("origin")
                    .parent_node_token(directory.node_token)
                    .title(title)
                    .build()
                ) \
                .build()

            response = self.client.wiki.v2.space_node.create(request)

            if not response.success():
                logger.error(
                    f"Failed to create wiki node: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                raise Exception(f"Failed to create wiki node: {response.msg}")

            node = response.data.node if response.data else None
            if node:
                doc_url = f"https://feishu.cn/wiki/{node.node_token}"
                logger.info(f"Wiki node created successfully: {doc_url}")

                # 构建图片URL映射
                image_url_map = {}
                if original_images and cdn_urls:
                    image_url_map = build_image_url_map(original_images, cdn_urls)
                    logger.info(f"Built image URL map with {len(image_url_map)} entries")

                # 使用 docx block API 添加内容
                self._add_structured_content(
                    document_id=node.obj_token,
                    title=title,
                    content=content,
                    content_html=content_html,
                    author=author,
                    publish_date=publish_date,
                    source_url=source_url,
                    image_url_map=image_url_map
                )

                return doc_url
            else:
                logger.warning("Wiki node created but node info not available")
                return None

        except Exception as e:
            logger.error(f"Error creating document: {str(e)}")
            raise

    def _add_structured_content(
        self,
        document_id: str,
        title: str,
        content: str,
        content_html: Optional[str],
        author: Optional[str],
        publish_date: Optional[str],
        source_url: Optional[str],
        image_url_map: Dict[str, str]
    ) -> bool:
        """
        向文档添加结构化内容

        Args:
            document_id: 文档ID
            title: 标题
            content: 纯文本内容
            content_html: HTML内容
            author: 作者
            publish_date: 发布日期
            source_url: 原文链接
            image_url_map: 图片URL映射
        """
        logger.info(f"Adding structured content to document: {document_id}")

        blocks = []

        # 添加元信息
        meta_blocks = self._create_meta_blocks(author, publish_date, source_url)
        blocks.extend(meta_blocks)

        # 添加分割线
        if meta_blocks:
            blocks.append(self._create_divider_block())

        # 解析HTML内容或使用纯文本
        if content_html:
            logger.info("Parsing HTML content for formatting")
            parser = HTMLToBlocksParser()
            parser.set_image_url_map(image_url_map)
            content_blocks = parser.parse(content_html)
            logger.info(f"Parsed {len(content_blocks)} content blocks from HTML")

            # 转换为飞书块
            for cb in content_blocks:
                feishu_block = self._content_block_to_feishu(cb, document_id)
                if feishu_block:
                    blocks.append(feishu_block)
        else:
            # 降级：使用纯文本
            logger.info("No HTML content, using plain text")
            text_blocks = self._parse_plain_text(content)
            blocks.extend(text_blocks)

        if not blocks:
            logger.warning("No content blocks to add")
            return True

        logger.info(f"Prepared {len(blocks)} content blocks to add")

        # 分批添加blocks
        return self._batch_add_blocks(document_id, blocks)

    def _create_meta_blocks(
        self,
        author: Optional[str],
        publish_date: Optional[str],
        source_url: Optional[str]
    ) -> List[Block]:
        """创建元信息块"""
        blocks = []

        if author:
            blocks.append(self._create_text_block(f"作者: {author}", bold=True))

        if publish_date:
            blocks.append(self._create_text_block(f"发布日期: {publish_date}", bold=True))

        if source_url:
            blocks.append(self._create_text_block(f"原文链接: {source_url}", bold=True))

        return blocks

    def _content_block_to_feishu(self, cb: ContentBlock, document_id: str = "") -> Optional[Block]:
        """将ContentBlock转换为飞书Block"""
        try:
            if cb.block_type == "text":
                return self._create_rich_text_block(cb)

            elif cb.block_type == "heading":
                block_type = 2 + cb.level  # level 1 -> block_type 3
                if block_type > 11:
                    block_type = 11
                return self._create_heading_block(cb.content, block_type=block_type)

            elif cb.block_type == "image":
                if cb.image_url and document_id:
                    image_block = self._create_image_block(cb.image_url, document_id)
                    if image_block:
                        return image_block
                    # 上传失败时降级为链接
                    return self._create_text_block(f"[图片] {cb.image_url}")
                return None

            elif cb.block_type == "divider":
                return self._create_divider_block()

            elif cb.block_type == "list_item":
                return self._create_bullet_block(cb.content)

            elif cb.block_type == "code":
                return self._create_code_block(cb.content)

            elif cb.block_type == "quote":
                return self._create_quote_block(cb.content)

            else:
                if cb.content:
                    return self._create_text_block(cb.content)
                return None

        except Exception as e:
            logger.warning(f"Error converting block: {e}")
            if cb.content:
                return self._create_text_block(cb.content)
            return None

    def _create_image_block(self, image_url: str, document_id: str) -> Optional[Block]:
        """下载图片并上传到飞书，创建图片块"""
        try:
            # 下载图片
            logger.info(f"Downloading image for Feishu upload: {image_url[:80]}...")
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()
            image_data = resp.content
            file_size = len(image_data)

            # 从URL推断文件名
            url_path = image_url.split('?')[0]
            filename = url_path.split('/')[-1] or "image.jpg"
            if '.' not in filename:
                content_type = resp.headers.get('Content-Type', '')
                if 'png' in content_type:
                    filename += '.png'
                elif 'gif' in content_type:
                    filename += '.gif'
                elif 'webp' in content_type:
                    filename += '.webp'
                else:
                    filename += '.jpg'

            # 上传到飞书
            logger.info(f"Uploading image to Feishu: {filename} ({file_size} bytes)")
            request = UploadAllMediaRequest.builder() \
                .request_body(
                    UploadAllMediaRequestBody.builder()
                    .file_name(filename)
                    .parent_type("docx_image")
                    .parent_node(document_id)
                    .size(file_size)
                    .file(io.BytesIO(image_data))
                    .build()
                ) \
                .build()

            response = self.client.drive.v1.media.upload_all(request)

            if not response.success():
                logger.error(
                    f"Failed to upload image to Feishu: code={response.code}, "
                    f"msg={response.msg}"
                )
                return None

            file_token = response.data.file_token
            logger.info(f"Image uploaded to Feishu, token: {file_token}")

            # 创建图片块
            return Block.builder() \
                .block_type(27) \
                .image(
                    Image.builder()
                    .token(file_token)
                    .build()
                ) \
                .build()

        except Exception as e:
            logger.warning(f"Failed to create image block: {e}")
            return None

    def _create_rich_text_block(self, cb: ContentBlock) -> Block:
        """创建支持行内样式的富文本块"""
        # 如果有行内元素（来自改进后的 HTML parser），使用它们
        if hasattr(cb, 'inline_elements') and cb.inline_elements:
            elements = []
            for elem in cb.inline_elements:
                text = self._clean_text(elem.get('text', ''))
                if not text:
                    continue
                style_builder = TextElementStyle.builder()
                if elem.get('bold'):
                    style_builder.bold(True)
                if elem.get('italic'):
                    style_builder.italic(True)
                text_run = TextRun.builder() \
                    .content(text) \
                    .text_element_style(style_builder.build()) \
                    .build()
                elements.append(
                    TextElement.builder().text_run(text_run).build()
                )
            if elements:
                text_obj = Text.builder() \
                    .style(TextStyle.builder().build()) \
                    .elements(elements) \
                    .build()
                return Block.builder().block_type(2).text(text_obj).build()

        # 降级为简单文本块
        return self._create_text_block(
            cb.content,
            bold=cb.style.get('bold', False)
        )

    def _parse_plain_text(self, content: str) -> List[Block]:
        """解析纯文本内容"""
        blocks = []
        paragraphs = content.strip().split('\n')

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 限制长度
            max_len = 10000
            if len(para) > max_len:
                para = para[:max_len] + "..."

            # 识别简单的markdown格式
            if para.startswith('# '):
                continue  # 跳过一级标题
            elif para.startswith('## '):
                blocks.append(self._create_heading_block(para[3:], block_type=4))
            elif para.startswith('### '):
                blocks.append(self._create_heading_block(para[4:], block_type=5))
            elif para.startswith('---'):
                blocks.append(self._create_divider_block())
            else:
                blocks.append(self._create_text_block(para))

        return blocks

    def _batch_add_blocks(self, document_id: str, blocks: List[Block]) -> bool:
        """分批添加块"""
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
                continue

            total_added += len(batch)
            current_index += len(batch)

        if total_added > 0:
            logger.info(f"Successfully added {total_added}/{len(blocks)} content blocks")
            return True
        else:
            logger.error("Failed to add any content blocks")
            return False

    def _create_text_block(self, text: str, bold: bool = False) -> Block:
        """创建文本块"""
        text = self._clean_text(text)
        if not text:
            text = " "  # 避免空文本

        # 构建文本样式
        text_elem_style = None
        if bold:
            text_elem_style = TextElementStyle.builder().bold(True).build()

        text_run_builder = TextRun.builder().content(text)
        if text_elem_style:
            text_run_builder.text_element_style(text_elem_style)

        text_element = TextElement.builder() \
            .text_run(text_run_builder.build()) \
            .build()

        text_obj = Text.builder() \
            .style(TextStyle.builder().build()) \
            .elements([text_element]) \
            .build()

        return Block.builder() \
            .block_type(2) \
            .text(text_obj) \
            .build()

    def _create_heading_block(self, text: str, block_type: int = 4) -> Block:
        """创建标题块"""
        text = self._clean_text(text)
        if not text:
            text = " "

        text_element = TextElement.builder() \
            .text_run(TextRun.builder().content(text).build()) \
            .build()

        text_obj = Text.builder() \
            .style(TextStyle.builder().build()) \
            .elements([text_element]) \
            .build()

        builder = Block.builder().block_type(block_type)

        if block_type == 3:
            builder.heading1(text_obj)
        elif block_type == 4:
            builder.heading2(text_obj)
        elif block_type == 5:
            builder.heading3(text_obj)
        elif block_type == 6:
            builder.heading4(text_obj)
        elif block_type == 7:
            builder.heading5(text_obj)
        elif block_type == 8:
            builder.heading6(text_obj)
        elif block_type == 9:
            builder.heading7(text_obj)
        elif block_type == 10:
            builder.heading8(text_obj)
        elif block_type == 11:
            builder.heading9(text_obj)
        else:
            builder.text(text_obj)

        return builder.build()

    def _create_divider_block(self) -> Block:
        """创建分割线块"""
        return Block.builder() \
            .block_type(22) \
            .divider(Divider.builder().build()) \
            .build()

    def _create_bullet_block(self, text: str) -> Block:
        """创建项目符号块"""
        text = self._clean_text(text)
        if not text:
            text = " "

        text_element = TextElement.builder() \
            .text_run(TextRun.builder().content(text).build()) \
            .build()

        text_obj = Text.builder() \
            .style(TextStyle.builder().build()) \
            .elements([text_element]) \
            .build()

        return Block.builder() \
            .block_type(12) \
            .bullet(text_obj) \
            .build()

    def _create_code_block(self, text: str) -> Block:
        """创建代码块"""
        text = self._clean_text(text)
        if not text:
            text = " "

        text_element = TextElement.builder() \
            .text_run(TextRun.builder().content(text).build()) \
            .build()

        text_obj = Text.builder() \
            .style(TextStyle.builder().build()) \
            .elements([text_element]) \
            .build()

        return Block.builder() \
            .block_type(14) \
            .code(text_obj) \
            .build()

    def _create_quote_block(self, text: str) -> Block:
        """创建引用块"""
        text = self._clean_text(text)
        if not text:
            text = " "

        text_element = TextElement.builder() \
            .text_run(TextRun.builder().content(text).build()) \
            .build()

        text_obj = Text.builder() \
            .style(TextStyle.builder().build()) \
            .elements([text_element]) \
            .build()

        return Block.builder() \
            .block_type(15) \
            .quote(text_obj) \
            .build()

    def _clean_text(self, text: str) -> str:
        """清理文本中的特殊字符"""
        if not text:
            return ""
        # 移除零宽字符
        text = re.sub(r'[\u200b\u200c\u200d\ufeff\u00ad]', '', text)
        # 移除控制字符
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        return text.strip()

    def create_document_simple(
        self,
        directory_token: str,
        title: str,
        content: str
    ) -> Optional[str]:
        """简化版文档创建"""
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
