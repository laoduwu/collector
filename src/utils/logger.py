"""日志系统"""
import logging
import sys
from typing import Optional
from .config import config


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""

    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m',       # 重置
    }

    def format(self, record):
        # 添加颜色
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)


def setup_logger(name: Optional[str] = None) -> logging.Logger:
    """
    设置日志记录器

    Args:
        name: 日志记录器名称，默认为根记录器

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 设置日志级别
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)

    # 创建控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # 设置格式
    formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)

    # 添加handler
    logger.addHandler(console_handler)

    return logger


# 创建默认logger
logger = setup_logger('collector')
