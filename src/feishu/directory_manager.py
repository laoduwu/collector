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
        space_id_str = config.FEISHU_KNOWLEDGE_SPACE_ID

        if not space_id_str:
            raise ValueError("FEISHU_KNOWLEDGE_SPACE_ID must be configured")

        # 去除可能的空格
        space_id_str = space_id_str.strip()

        # 尝试转换为整数（企业版），如果失败则使用字符串（可能是个人版）
        try:
            self.space_id = int(space_id_str)
            logger.info(f"Using integer space_id: {self.space_id} (Enterprise)")
        except ValueError:
            # 个人版可能使用字符串格式的space_id
            self.space_id = space_id_str
            logger.warning(
                f"Using string space_id: {space_id_str} (Personal Edition)\n"
                f"Note: This may work for Feishu Personal Edition, but Enterprise Edition requires integer space_id."
            )

        self.unorganized_folder_name = config.FEISHU_UNORGANIZED_FOLDER_NAME

    def _list_nodes(self, parent_node_token: Optional[str] = None) -> List:
        """
        获取指定层级的节点列表

        Args:
            parent_node_token: 父节点token，None表示获取一级节点

        Returns:
            节点列表
        """
        nodes = []
        page_token = None

        while True:
            builder = ListSpaceNodeRequest.builder() \
                .space_id(self.space_id) \
                .page_size(50)

            if parent_node_token:
                builder = builder.parent_node_token(parent_node_token)

            request = builder.build()

            if page_token:
                request.page_token = page_token

            response: ListSpaceNodeResponse = self.client.wiki.v2.space_node.list(request)

            if not response.success():
                logger.error(
                    f"Failed to list space nodes: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                raise Exception(f"Failed to get knowledge space directories: {response.msg}")

            if response.data.items:
                nodes.extend(response.data.items)
            else:
                break

            if response.data.has_more:
                page_token = response.data.page_token
            else:
                break

        return nodes

    def get_all_directories(self) -> List[Directory]:
        """
        获取知识库的一级目录

        Returns:
            目录列表

        Raises:
            Exception: 获取失败
        """
        logger.info(f"Fetching directories from knowledge space: {self.space_id}")

        try:
            directories = []
            nodes = self._list_nodes()

            for node in nodes:
                logger.debug(
                    f"Node: title={node.title}, obj_type={node.obj_type}, "
                    f"node_token={node.node_token}, has_child={node.has_child}"
                )
                directory = Directory(
                    node_token=node.node_token,
                    name=node.title,
                    is_leaf=not node.has_child,
                    parent_token=node.parent_node_token
                )
                directories.append(directory)
                logger.info(
                    f"Found directory: {directory.name} "
                    f"(type={node.obj_type}, leaf={directory.is_leaf})"
                )

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
        获取可用于匹配的二级目录和兜底目录

        Returns:
            (可匹配的二级目录列表, "待整理"目录)

        注意：
            - 文档创建在二级目录下
            - "待整理"是一级目录，直接作为兜底
            - 其它一级目录的子节点（二级目录）参与匹配
        """
        logger.info("Getting matchable directories...")

        # 获取一级目录
        top_dirs = self.get_all_directories()

        # 查找"待整理"文件夹
        unorganized = None
        parent_dirs = []
        for directory in top_dirs:
            if directory.name == self.unorganized_folder_name:
                unorganized = directory
                logger.info(f"Found unorganized folder: {directory.name}")
            else:
                parent_dirs.append(directory)

        # 获取所有一级目录的子节点（二级目录）用于匹配
        matchable_dirs = []
        for parent in parent_dirs:
            child_nodes = self._list_nodes(parent_node_token=parent.node_token)
            for node in child_nodes:
                child_dir = Directory(
                    node_token=node.node_token,
                    name=node.title,
                    is_leaf=not node.has_child,
                    parent_token=node.parent_node_token
                )
                matchable_dirs.append(child_dir)
                logger.info(
                    f"Found sub-directory: {parent.name} > {child_dir.name}"
                )

        logger.info(
            f"Got {len(matchable_dirs)} matchable sub-directories, "
            f"unorganized folder: {unorganized.name if unorganized else 'None'}"
        )

        return matchable_dirs, unorganized
