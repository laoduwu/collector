#!/usr/bin/env python3
"""
飞书知识库Space ID获取工具（简化版）

用途：通过手动输入App ID和Secret来获取所有知识库的space_id
"""
import lark_oapi as lark
from lark_oapi.api.wiki.v2 import ListSpaceRequest


def get_space_id():
    """获取知识库Space ID"""
    print("\n" + "="*80)
    print("飞书知识库 Space ID 获取工具")
    print("="*80 + "\n")

    # 手动输入配置
    print("请输入飞书应用配置：")
    app_id = input("FEISHU_APP_ID: ").strip()
    app_secret = input("FEISHU_APP_SECRET: ").strip()

    if not app_id or not app_secret:
        print("\n❌ App ID 或 App Secret 不能为空！")
        return

    print("\n✓ 正在获取知识库列表...\n")

    try:
        # 创建客户端
        client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.ERROR) \
            .build()

        # 获取知识库列表
        request = ListSpaceRequest.builder() \
            .page_size(50) \
            .build()

        response = client.wiki.v2.space.list(request)

        if not response.success():
            print(f"❌ API调用失败: {response.msg}")
            print(f"   错误码: {response.code}")
            print(f"\n可能的原因：")
            print(f"   1. App ID 或 App Secret 错误")
            print(f"   2. 应用未启用或未发布")
            print(f"   3. 应用缺少wiki权限")
            return

        if not response.data or not response.data.items:
            print("⚠️  未找到任何知识库")
            print("\n请确认：")
            print("   1. 飞书应用是否已安装到企业")
            print("   2. 应用是否有 wiki:wiki:readonly 权限")
            print("   3. 知识库是否已创建")
            return

        print(f"✅ 找到 {len(response.data.items)} 个知识库：\n")
        print("="*80)

        for idx, space in enumerate(response.data.items, 1):
            space_id = space.space_id
            name = space.name or "(无名称)"
            space_type = space.space_type or "unknown"

            print(f"\n{idx}. 知识库名称: {name}")
            print(f"   Space ID: {space_id}  ⭐")
            print(f"   类型: {space_type}")
            print(f"   描述: {space.description or '(无描述)'}")

        print("\n" + "="*80)
        print("\n📝 配置说明：")
        print("="*80)
        print("\n请将上面显示的 Space ID（纯数字）配置到：")
        print("  GitHub Secrets → FEISHU_KNOWLEDGE_SPACE_ID")
        print("\n⚠️  重要：")
        print("  - Space ID 必须是纯数字（如：7391149998842896386）")
        print("  - 不要配置 wiki token（如：GKTiw1TSMi...）")
        print()

        # 如果只有一个知识库，给出直接的建议
        if len(response.data.items) == 1:
            space_id = response.data.items[0].space_id
            print(f"💡 你只有一个知识库，建议配置：")
            print(f"   FEISHU_KNOWLEDGE_SPACE_ID={space_id}")
            print()

    except Exception as e:
        print(f"\n❌ 发生错误: {str(e)}")
        print("\n常见错误原因：")
        print("  1. 网络连接问题")
        print("  2. App ID/Secret 格式错误")
        print("  3. 缺少 lark-oapi 依赖（运行: pip3 install lark-oapi）")


if __name__ == "__main__":
    try:
        get_space_id()
    except KeyboardInterrupt:
        print("\n\n已取消")
    except Exception as e:
        print(f"\n❌ 程序错误: {str(e)}")
