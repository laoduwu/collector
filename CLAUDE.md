# Collector - 飞书文章收集系统

通过飞书机器人自动收集网页/微信公众号文章到飞书知识库。

## 架构

```
URL → Cloudflare Workers → GitHub Actions → Python脚本 → 飞书知识库
```

核心流程: 抓取文章 → 下载图片 → 上传GitHub CDN → AI匹配目录 → 写入飞书

## 项目结构

```
src/
├── main.py                    # 入口
├── scrapers/                  # 网页抓取 (Playwright/Nodriver)
├── feishu/                    # 飞书API (认证/目录/文档上传/HTML解析)
├── image_pipeline/            # 图片处理 (GitHub上传/jsDelivr CDN)
├── matchers/                  # AI语义目录匹配 (Jina Embeddings)
└── utils/                     # 配置/日志/重试
```

## 开发命令

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python src/main.py "<url>"           # 本地运行
pytest tests/                        # 运行测试
```

## 环境变量

配置在 `.env` 文件中:
- `FEISHU_APP_ID/APP_SECRET` - 飞书应用凭证
- `FEISHU_KNOWLEDGE_SPACE_ID` - 知识库空间ID
- `JINA_API_KEY` - Jina AI嵌入API
- `GH_TOKEN/IMAGE_REPO` - GitHub图片托管

## 技术栈

- Python 3.11+, Playwright/Nodriver, Jina AI Embeddings, 飞书 lark-oapi
- 部署: GitHub Actions + Cloudflare Workers
