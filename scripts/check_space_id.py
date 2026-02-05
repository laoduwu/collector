#!/usr/bin/env python3
"""
飞书知识库Space ID诊断脚本

用途：帮助用户查看所有知识库并找到正确的space_id
运行：python scripts/check_space_id.py
"""
import os
import sys

# 添加src到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.config import config
from utils.logger import logger
import lark_oapi as lark
from lark_oapi.api.wiki.v2 import ListSpaceRequest


def check_space_id():
    """检查并显示所有知识库的Space ID"""
    print("\n" + "="*80)
    print("飞书知识库 Space ID 诊断工具")
    print("="*80 + "\n")

    # 检查配置
    app_id = config.FEISHU_APP_ID
    app_secret = config.FEISHU_APP_SECRET
    current_space_id = config.FEISHU_KNOWLEDGE_SPACE_ID

    if not app_id or not app_secret:
        print("❌ 错误：缺少飞书App配置")
        print("   请先配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        return

    print(f"✓ 当前配置的 FEISHU_KNOWLEDGE_SPACE_ID: {current_space_id or '(未配置)'}")
    print(f"✓ 正在获取你的所有知识库...\n")

    try:
        # 创建客户端
        client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.ERROR) \
            .build()

        # 获取tenant_access_token
        request = ListSpaceRequest.builder() \
            .page_size(50) \
            .build()

        response = client.wiki.v2.space.list(request)

        if not response.success():
            print(f"❌ API调用失败: {response.msg}")
            print(f"   错误码: {response.code}")
            return

        # 显示所有知识库
        if not response.data or not response.data.items:
            print("⚠️  未找到任何知识库")
            print("   请确认：")
            print("   1. 飞书应用是否已安装到企业")
            print("   2. 应用是否有wiki权限")
            return

        print(f"找到 {len(response.data.items)} 个知识库：\n")
        print("-" * 80)

        for idx, space in enumerate(response.data.items, 1):
            space_id = space.space_id
            name = space.name
            is_current = str(space_id) == str(current_space_id)

            status = "✓ [当前配置]" if is_current else ""
            print(f"{idx}. {name}")
            print(f"   Space ID: {space_id}  {status}")
            print(f"   类型: {space.space_type or 'unknown'}")
            print("-" * 80)

        # 提供配置建议
        print("\n" + "="*80)
        print("📝 配置建议：")
        print("="*80)
        print("\n如果要使用某个知识库，请将对应的 Space ID 配置到：")
        print("  - 本地测试: .env 文件中的 FEISHU_KNOWLEDGE_SPACE_ID")
        print("  - GitHub Actions: GitHub Secrets 中的 FEISHU_KNOWLEDGE_SPACE_ID")
        print("\n⚠️  注意：Space ID 必须是纯数字！")
        print("\n示例配置：")
        if response.data.items:
            example_id = response.data.items[0].space_id
            print(f"  FEISHU_KNOWLEDGE_SPACE_ID={example_id}")
        print()

    except Exception as e:
        print(f"\n❌ 发生错误: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    check_space_id()
