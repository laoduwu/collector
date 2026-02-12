"""HTML内容解析器 - 将HTML转换为飞书文档块"""
import re
from typing import List, Dict, Optional
from bs4 import BeautifulSoup, Tag, NavigableString
from utils.logger import logger


class ContentBlock:
    """内容块"""
    def __init__(self, block_type: str, content: str = ""):
        self.block_type = block_type  # text, heading, image, divider, list_item, code, quote
        self.content = content
        self.level = 1  # 标题级别
        self.image_url = ""  # 图片URL
        self.style = {}  # 整块样式
        self.inline_elements: List[Dict] = []  # 行内元素列表 [{'text': str, 'bold': bool, 'italic': bool}]


class HTMLToBlocksParser:
    """将HTML解析为内容块列表"""

    INLINE_TAGS = {'strong', 'b', 'em', 'i', 'span', 'a', 'u', 's', 'del', 'mark', 'sub', 'sup'}
    BLOCK_TAGS = {'p', 'div', 'section', 'article', 'main', 'header', 'footer', 'nav', 'aside'}

    def __init__(self):
        self.blocks: List[ContentBlock] = []
        self.image_url_map: Dict[str, str] = {}

    def set_image_url_map(self, url_map: Dict[str, str]):
        """设置图片URL映射"""
        self.image_url_map = url_map

    def parse(self, html_content: str) -> List[ContentBlock]:
        """解析HTML内容为块列表"""
        if not html_content:
            return []

        self.blocks = []

        try:
            soup = BeautifulSoup(html_content, 'lxml')
            self._parse_element(soup)
        except Exception as e:
            logger.error(f"Error parsing HTML: {e}")
            text = BeautifulSoup(html_content, 'lxml').get_text()
            if text.strip():
                block = ContentBlock("text", text.strip())
                self.blocks.append(block)

        return self.blocks

    def _parse_element(self, element):
        """递归解析元素"""
        if isinstance(element, NavigableString):
            text = str(element).strip()
            if text:
                self._add_text_block(text)
            return

        if not isinstance(element, Tag):
            return

        tag_name = element.name.lower() if element.name else ""

        if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self._handle_heading(element, tag_name)
        elif tag_name in ['img', 'graphic']:
            self._handle_image(element)
        elif tag_name == 'p':
            self._handle_paragraph(element)
        elif tag_name == 'section':
            self._handle_section(element)
        elif tag_name == 'br':
            pass
        elif tag_name == 'hr':
            self.blocks.append(ContentBlock("divider"))
        elif tag_name in ['ul', 'ol']:
            self._handle_list(element, ordered=(tag_name == 'ol'))
        elif tag_name == 'li':
            self._handle_list_item(element)
        elif tag_name == 'pre':
            self._handle_code(element)
        elif tag_name == 'code':
            # 独立的 code 标签（非 pre 内部）作为行内代码处理
            if element.parent and element.parent.name == 'pre':
                return  # pre 已经处理
            text = element.get_text().strip()
            if text:
                self._add_text_block(text)
        elif tag_name == 'blockquote':
            self._handle_quote(element)
        elif tag_name in self.BLOCK_TAGS:
            for child in element.children:
                self._parse_element(child)
        elif tag_name in self.INLINE_TAGS:
            # 独立出现的行内标签（不在段落内），作为文本块处理
            self._handle_standalone_inline(element)
        else:
            for child in element.children:
                self._parse_element(child)

    def _handle_heading(self, element: Tag, tag_name: str):
        """处理标题"""
        level = int(tag_name[1])

        # 标题内可能嵌套图片（微信文章常见），先提取图片
        has_img = element.find('img') or element.find('graphic')
        if has_img:
            inline_elements = []
            self._walk_with_images(element, inline_elements, {})
            if inline_elements:
                self._emit_rich_text_block(inline_elements)
            return

        text = element.get_text().strip()
        if text:
            block = ContentBlock("heading", text)
            block.level = level
            self.blocks.append(block)

    def _handle_image(self, element: Tag):
        """处理图片"""
        src = element.get('data-src') or element.get('src')
        if src and src.startswith('http'):
            cdn_url = self.image_url_map.get(src, src)
            block = ContentBlock("image")
            block.image_url = cdn_url
            self.blocks.append(block)

    def _handle_paragraph(self, element: Tag):
        """处理段落 - 支持行内混排样式"""
        has_img = element.find('img') or element.find('graphic')

        if has_img:
            # 段落内混有图片和文本，递归拆分处理
            inline_elements = []
            self._walk_with_images(element, inline_elements, {})
            if inline_elements:
                self._emit_rich_text_block(inline_elements)
            return

        # 普通段落：收集行内元素
        inline_elements = []
        self._collect_inline_elements(element, inline_elements, {})

        if inline_elements:
            self._emit_rich_text_block(inline_elements)

    def _walk_with_images(self, node, inline_elements: List[Dict], parent_style: Dict):
        """递归遍历节点，遇到图片时切分文本块"""
        if isinstance(node, NavigableString):
            text = str(node)
            if text.strip():
                clean_text = re.sub(r'\s+', ' ', text)
                if clean_text.strip():
                    inline_elements.append({
                        'text': clean_text,
                        'bold': parent_style.get('bold', False),
                        'italic': parent_style.get('italic', False),
                    })
            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower() if node.name else ""

        if tag in ['img', 'graphic']:
            # 先输出已积累的文本
            if inline_elements:
                self._emit_rich_text_block(inline_elements)
                inline_elements.clear()
            self._handle_image(node)
            return

        if tag == 'br':
            return

        # 计算样式
        current_style = dict(parent_style)
        if tag in ['strong', 'b']:
            current_style['bold'] = True
        elif tag in ['em', 'i']:
            current_style['italic'] = True

        for child in node.children:
            self._walk_with_images(child, inline_elements, current_style)

    def _handle_section(self, element: Tag):
        """处理section（微信文章常用）"""
        for child in element.children:
            self._parse_element(child)

    def _handle_standalone_inline(self, element: Tag):
        """处理独立出现的行内元素（不在 p 标签内）"""
        has_img = element.find('img') or element.find('graphic')

        if has_img:
            # 包含图片时，使用 _walk_with_images 正确拆分文本和图片
            inline_elements = []
            self._walk_with_images(element, inline_elements, {})
            if inline_elements:
                self._emit_rich_text_block(inline_elements)
            return

        inline_elements = []
        self._collect_inline_elements(element, inline_elements, {})
        if inline_elements:
            self._emit_rich_text_block(inline_elements)

    def _collect_inline_elements(self, node, elements: List[Dict], parent_style: Dict):
        """递归收集行内元素及其样式"""
        if isinstance(node, NavigableString):
            text = str(node)
            # 保留单个空格但去掉纯空白
            if text.strip() or (text == ' ' and elements):
                clean_text = re.sub(r'\s+', ' ', text)
                if clean_text.strip():
                    elements.append({
                        'text': clean_text,
                        'bold': parent_style.get('bold', False),
                        'italic': parent_style.get('italic', False),
                    })
            return

        if not isinstance(node, Tag):
            return

        tag = node.name.lower() if node.name else ""

        # 图片在行内收集中跳过（由上层处理）
        if tag in ['img', 'graphic']:
            return
        if tag == 'br':
            return

        # 计算当前样式
        current_style = dict(parent_style)
        if tag in ['strong', 'b']:
            current_style['bold'] = True
        elif tag in ['em', 'i']:
            current_style['italic'] = True

        # 递归子节点
        for child in node.children:
            self._collect_inline_elements(child, elements, current_style)

    def _emit_rich_text_block(self, inline_elements: List[Dict]):
        """从行内元素列表生成一个富文本块"""
        # 过滤空元素
        filtered = [e for e in inline_elements if e.get('text', '').strip()]
        if not filtered:
            return

        # 如果所有元素样式相同，简化为普通文本块
        all_plain = all(not e.get('bold') and not e.get('italic') for e in filtered)
        if all_plain:
            combined = ''.join(e['text'] for e in filtered).strip()
            if combined:
                self._add_text_block(combined)
            return

        # 创建富文本块
        block = ContentBlock("text")
        block.content = ''.join(e['text'] for e in filtered).strip()
        block.inline_elements = filtered
        self.blocks.append(block)

    def _handle_list(self, element: Tag, ordered: bool = False):
        """处理列表"""
        for li in element.find_all('li', recursive=False):
            text = li.get_text().strip()
            if text:
                block = ContentBlock("list_item", text)
                block.style['ordered'] = ordered
                self.blocks.append(block)

    def _handle_list_item(self, element: Tag):
        """处理列表项"""
        text = element.get_text().strip()
        if text:
            block = ContentBlock("list_item", text)
            self.blocks.append(block)

    def _handle_code(self, element: Tag):
        """处理代码块 - 支持微信 code-snippet 结构"""
        # 微信代码块结构: <pre><code><span>line1</span></code><code><span><br></span></code>...
        code_children = element.find_all('code', recursive=False)
        if code_children and len(code_children) > 1:
            lines = []
            for code_tag in code_children:
                # 检查是否是空行（只含 <br>）
                if code_tag.find('br') and not code_tag.get_text().strip():
                    lines.append('')
                else:
                    lines.append(code_tag.get_text())
            text = '\n'.join(lines)
        else:
            # 非微信结构：处理 <br> 后获取文本
            for br in element.find_all('br'):
                br.replace_with('\n')
            text = element.get_text()

        if text.strip():
            block = ContentBlock("code", text)
            self.blocks.append(block)

    def _handle_quote(self, element: Tag):
        """处理引用"""
        text = element.get_text().strip()
        if text:
            block = ContentBlock("quote", text)
            self.blocks.append(block)

    def _add_text_block(self, text: str):
        """添加纯文本块"""
        text = text.strip()
        if not text:
            return

        # 合并连续的短纯文本块
        if self.blocks and self.blocks[-1].block_type == "text":
            last = self.blocks[-1]
            if not last.style and not last.inline_elements and len(last.content) < 100:
                last.content += " " + text
                return

        block = ContentBlock("text", text)
        self.blocks.append(block)


def build_image_url_map(original_urls: List[str], cdn_urls: List[str]) -> Dict[str, str]:
    """构建原始URL到CDN URL的映射"""
    url_map = {}
    for i, orig_url in enumerate(original_urls):
        if i < len(cdn_urls):
            url_map[orig_url] = cdn_urls[i]
    return url_map
