"""类型定义"""
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class Directory:
    """目录信息"""
    node_token: str  # 飞书目录节点token
    name: str  # 目录名称
    is_leaf: bool  # 是否为叶子节点
    parent_token: Optional[str] = None  # 父节点token
    embedding: Optional[List[float]] = None  # embedding向量


@dataclass
class MatchResult:
    """匹配结果"""
    directory: Directory
    similarity: float  # 相似度分数
    confidence: str  # 置信度（high/medium/low）

    def __repr__(self):
        return f"MatchResult(name='{self.directory.name}', similarity={self.similarity:.3f}, confidence='{self.confidence}')"
