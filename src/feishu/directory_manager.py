"""飞书知识库目录管理器"""
from typing import List, Optional
import lark_oapi as lark
from lark_oapi.api.wiki.v2 import ListSpaceNodeRequest, ListSpaceNodeResponse
from .auth_manager import AuthManager
from matchers.types import Directory
from utils.logger import logger
from utils.config import config


class DirectoryManager:
    """飞书知识库目录管理器"""

    def __init__(self, auth_manager: AuthManager):
        self.auth_manager = auth_manager
        self.client = auth_manager.client
        # 飞书API要求space_id为整数（纯数字）
        space_id_str = config.FEISHU_KNOWLEDGE_SPACE_ID
        if not space_id_str:
            raise ValueError("FEISHU_KNOWLEDGE_SPACE_ID must be configured")

        # 去除可能的空格
        space_id_str = space_id_str.strip()

        try:
            self.space_id = int(space_id_str)
            logger.info(f"Knowledge space ID: {self.space_id}")
        except ValueError:
            # 提供详细的错误诊断
            error_msg = (
                f"\n{'='*80}\n"
                f"❌ FEISHU_KNOWLEDGE_SPACE_ID配置错误！\n"
                f"{'='*80}\n"
                f"当前配置值: {space_id_str}\n"
                f"错误原因: 该值不是纯数字，无法转换为整数\n\n"
                f"常见错误:\n"
                f"  1. 配置了node_token而不是space_id (如: wikcnXxx)\n"
                f"  2. 配置了doc_token而不是space_id (如: doxcnXxx)\n"
                f"  3. 包含了额外的字符或空格\n\n"
                f"✅ 如何获取正确的space_id:\n"
                f"  方法1: 从知识库URL获取\n"
                f"    - URL格式: https://xxx.feishu.cn/wiki/[space_id]\n"
                f"    - space_id是URL中的纯数字部分\n"
                f"    - 示例: https://xxx.feishu.cn/wiki/1234567890\n"
                f"           → space_id = 1234567890\n\n"
                f"  方法2: 使用飞书开放平台API\n"
                f"    - 调用获取知识库列表API\n"
                f"    - 从返回结果中找到space_id字段\n\n"
                f"请修改GitHub Secrets中的FEISHU_KNOWLEDGE_SPACE_ID配置为纯数字！\n"
                f"{'='*80}\n"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        self.unorganized_folder_name = config.FEISHU_UNORGANIZED_FOLDER_NAME

    def get_all_directories(self) -> List[Directory]:
        """
        获取知识库的所有目录（递归遍历）

        Returns:
            目录列表

        Raises:
            Exception: 获取失败
        """
        logger.info(f"Fetching directories from knowledge space: {self.space_id}")

        try:
            directories = []
            page_token = None

            while True:
                # 构建请求
                request = ListSpaceNodeRequest.builder() \
                    .space_id(self.space_id) \
                    .page_size(50) \
                    .build()

                if page_token:
                    request.page_token = page_token

                # 发起请求
                response: ListSpaceNodeResponse = self.client.wiki.v2.space_node.list(request)

                if not response.success():
                    logger.error(
                        f"Failed to list space nodes: code={response.code}, "
                        f"msg={response.msg}, log_id={response.get_log_id()}"
                    )
                    raise Exception(f"Failed to get knowledge space directories: {response.msg}")

                # 解析节点
                if response.data.items:
                    for node in response.data.items:
                        # 只收集文件夹类型的节点
                        if node.obj_type == 'wiki':
                            directory = Directory(
                                node_token=node.node_token,
                                name=node.title,
                                is_leaf=not node.has_child,  # 没有子节点即为叶子节点
                                parent_token=node.parent_node_token
                            )
                            directories.append(directory)
                            logger.debug(
                                f"Found directory: {directory.name} "
                                f"(leaf={directory.is_leaf})"
                            )

                # 检查是否有下一页
                if response.data.has_more:
                    page_token = response.data.page_token
                else:
                    break

            logger.info(f"Found {len(directories)} directories")
            return directories

        except Exception as e:
            logger.error(f"Error fetching directories: {str(e)}")
            raise

    def get_leaf_directories(self) -> List[Directory]:
        """
        获取所有叶子节点目录（可以创建文档的目录）

        Returns:
            叶子目录列表
        """
        all_dirs = self.get_all_directories()
        leaf_dirs = [d for d in all_dirs if d.is_leaf]

        logger.info(f"Found {len(leaf_dirs)} leaf directories out of {len(all_dirs)} total")
        return leaf_dirs

    def find_unorganized_folder(self) -> Optional[Directory]:
        """
        查找"待整理"文件夹

        Returns:
            "待整理"目录，如果不存在则返回None
        """
        logger.info(f"Looking for unorganized folder: '{self.unorganized_folder_name}'")

        try:
            all_dirs = self.get_all_directories()

            for directory in all_dirs:
                if directory.name == self.unorganized_folder_name:
                    logger.info(f"Found unorganized folder: {directory.node_token}")
                    return directory

            logger.warning(f"Unorganized folder '{self.unorganized_folder_name}' not found")
            return None

        except Exception as e:
            logger.error(f"Error finding unorganized folder: {str(e)}")
            return None

    def get_matchable_directories(self) -> tuple[List[Directory], Optional[Directory]]:
        """
        获取可用于匹配的目录和兜底目录

        Returns:
            (可匹配的叶子目录列表, "待整理"目录)

        注意：
            - 可匹配目录列表不包含"待整理"文件夹
            - 如果"待整理"不存在，会返回None
        """
        logger.info("Getting matchable directories...")

        # 获取所有叶子目录
        leaf_dirs = self.get_leaf_directories()

        # 查找"待整理"文件夹
        unorganized = None
        matchable_dirs = []

        for directory in leaf_dirs:
            if directory.name == self.unorganized_folder_name:
                unorganized = directory
            else:
                matchable_dirs.append(directory)

        logger.info(
            f"Got {len(matchable_dirs)} matchable directories, "
            f"unorganized folder: {unorganized.name if unorganized else 'None'}"
        )

        return matchable_dirs, unorganized
