"""配置管理模块"""
import os
from typing import Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Config:
    """系统配置"""

    # 飞书配置
    FEISHU_APP_ID: str = os.getenv('FEISHU_APP_ID', '')
    FEISHU_APP_SECRET: str = os.getenv('FEISHU_APP_SECRET', '')
    FEISHU_VERIFICATION_TOKEN: str = os.getenv('FEISHU_VERIFICATION_TOKEN', '')
    FEISHU_ENCRYPT_KEY: str = os.getenv('FEISHU_ENCRYPT_KEY', '')
    FEISHU_KNOWLEDGE_SPACE_ID: str = os.getenv('FEISHU_KNOWLEDGE_SPACE_ID', '')
    FEISHU_UNORGANIZED_FOLDER_NAME: str = os.getenv('FEISHU_UNORGANIZED_FOLDER_NAME', '待整理')

    # LLM配置（目录分类匹配）
    LLM_API_KEY: str = os.getenv('LLM_API_KEY', '')
    LLM_BASE_URL: str = os.getenv('LLM_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai')
    LLM_MODEL: str = os.getenv('LLM_MODEL', 'gemini-2.5-flash')

    # GitHub配置（图片托管）
    GH_TOKEN: str = os.getenv('GH_TOKEN', '')
    IMAGE_REPO: str = os.getenv('IMAGE_REPO', '')
    IMAGE_BRANCH: str = os.getenv('IMAGE_BRANCH', 'main')

    # 日志配置
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    # 目录配置
    DOWNLOADS_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
    CACHE_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'cache')

    @classmethod
    def validate(cls) -> list[str]:
        """
        验证必需的配置项

        Returns:
            缺失的配置项列表
        """
        missing = []

        # 必需的配置项
        required_fields = [
            'FEISHU_APP_ID',
            'FEISHU_APP_SECRET',
            'FEISHU_KNOWLEDGE_SPACE_ID',
            'LLM_API_KEY',
            'GH_TOKEN',
            'IMAGE_REPO',
        ]

        for field in required_fields:
            value = getattr(cls, field, '')
            if not value or value == '':
                missing.append(field)

        return missing

    @classmethod
    def ensure_directories(cls):
        """确保必要的目录存在"""
        os.makedirs(cls.DOWNLOADS_DIR, exist_ok=True)
        os.makedirs(cls.CACHE_DIR, exist_ok=True)


# 创建全局配置实例
config = Config()
