# 飞书文章收集系统

通过飞书机器人自动收集文章到知识库，支持智能目录匹配和图片托管。

## ✨ 功能特性

- ✅ 支持普通网页和微信公众号文章抓取（含图片）
- ✅ 基于AI语义理解的智能目录匹配（目标准确率≥80%）
- ✅ 自动下载图片并托管到GitHub + jsDelivr CDN
- ✅ 完全免费，无需信用卡（所有服务均免费）
- ✅ GitHub Actions云端部署（20-60秒完成处理）
- ✅ 微信文章图片防盗链处理
- ✅ 自动兜底机制（无法匹配时进入"待整理"）

## 🚀 快速开始

### 1. 环境配置

```bash
# 克隆仓库
git clone https://github.com/yourusername/collector.git
cd collector

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际配置
```

### 2. 本地测试

```bash
# 测试普通网页
cd src
python main.py "https://example.com/article"

# 测试微信文章
python main.py "https://mp.weixin.qq.com/s/xxxxx"
```

### 3. 部署到生产环境

详见 [DEPLOYMENT.md](DEPLOYMENT.md) 完整部署指南

## 📋 系统架构

```
用户发送URL → 飞书机器人 → Webhook
                              ↓
                  Cloudflare Workers接收验证
                              ↓
                  触发GitHub Actions
                              ↓
              GitHub Actions执行Python脚本：
              1. Nodriver抓取文章
              2. 下载所有图片
              3. 上传图片到GitHub
              4. 生成jsDelivr CDN链接
              5. 替换图片URL
              6. Jina AI语义匹配目录
              7. 保存到飞书知识库
                              ↓
              20-60秒后完成处理
```

## 🛠 技术栈

| 组件 | 技术选型 | 理由 |
|------|---------|------|
| 编程语言 | Python 3.11+ | Nodriver最佳支持 |
| 网页抓取 | Nodriver | 1-5%检测率，微信95%+成功率 |
| AI匹配 | Jina AI Embeddings API | 免费1M tokens/月，中文支持 |
| 图片托管 | GitHub + jsDelivr CDN | 永久免费，100%可用性 |
| 部署环境 | GitHub Actions | 公开仓库无限分钟 |
| Webhook | Cloudflare Workers | 免费10万请求/天 |
| 飞书SDK | lark-oapi | 官方Python SDK |

## 📁 项目结构

```
collector/
├── src/                             # 源代码
│   ├── main.py                      # 主入口
│   ├── scrapers/
│   │   ├── nodriver_scraper.py      # Nodriver抓取器
│   │   └── image_downloader.py      # 图片下载器
│   ├── matchers/
│   │   ├── jina_client.py           # Jina AI客户端
│   │   ├── similarity_matcher.py    # 相似度匹配
│   │   └── types.py                 # 类型定义
│   ├── feishu/
│   │   ├── auth_manager.py          # 认证管理
│   │   ├── directory_manager.py     # 目录管理
│   │   └── document_uploader.py     # 文档上传
│   ├── image_pipeline/
│   │   ├── github_uploader.py       # GitHub上传
│   │   └── jsdelivr_cdn.py          # CDN链接生成
│   └── utils/
│       ├── config.py                # 配置管理
│       ├── logger.py                # 日志系统
│       └── retry.py                 # 重试逻辑
├── webhook-receiver/                # Cloudflare Workers
│   ├── index.js                     # Webhook接收器
│   ├── wrangler.toml                # CF配置
│   └── README.md                    # 部署说明
├── .github/workflows/
│   └── scrape-article.yml           # GitHub Actions配置
├── tests/                           # 测试用例
│   ├── test_scraper.py
│   ├── test_matcher.py
│   └── test_image_pipeline.py
├── requirements.txt                 # Python依赖
├── .env.example                     # 环境变量模板
├── DEPLOYMENT.md                    # 部署指南
├── TESTING.md                       # 测试指南
└── README.md                        # 本文件
```

## 📖 文档

- [DEPLOYMENT.md](DEPLOYMENT.md) - 完整部署指南
- [TESTING.md](TESTING.md) - 测试指南
- [webhook-receiver/README.md](webhook-receiver/README.md) - Webhook部署说明

## 🔧 环境变量

```bash
# 飞书配置
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_KNOWLEDGE_SPACE_ID=xxx
FEISHU_UNORGANIZED_FOLDER_NAME=待整理

# Jina AI配置
JINA_API_KEY=jina_xxx
JINA_MODEL=jina-embeddings-v2-base-zh
SIMILARITY_THRESHOLD=0.7

# GitHub配置
GH_TOKEN=ghp_xxx
IMAGE_REPO=yourusername/collector-images
IMAGE_BRANCH=main
```

详见 `.env.example`

## 🧪 测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_scraper.py -v

# 带覆盖率报告
pytest tests/ --cov=src --cov-report=html
```

详见 [TESTING.md](TESTING.md)

## 💰 成本分析

**完全免费 - $0/月**

| 服务 | 免费额度 | 预估使用 | 状态 |
|------|----------|----------|------|
| GitHub Actions | 无限（公开仓库） | ~20分钟/天 | ✅ 充足 |
| Cloudflare Workers | 10万请求/天 | ~17请求/天 | ✅ 充足 |
| Jina AI | 1M tokens/月 | 100K tokens/月 | ✅ 充足 |
| GitHub存储 | 无限（公开仓库） | ~5GB/月 | ✅ 充足 |
| jsDelivr CDN | 无限带宽 | ~5GB/月 | ✅ 充足 |

## ⚡️ 性能指标

- 单篇处理时间：20-60秒
- 抓取时间：10-30秒
- 图片处理：5-20秒（取决于数量）
- AI匹配：2-5秒
- 文档创建：3-5秒

## 🎯 开发状态

- [x] 项目初始化与架构设计
- [x] 核心抓取功能（Nodriver）
- [x] 图片托管管道（GitHub + CDN）
- [x] Jina AI智能匹配
- [x] 飞书API集成
- [x] GitHub Actions工作流
- [x] Cloudflare Workers Webhook
- [x] 测试框架
- [ ] 生产环境部署
- [ ] 准确率验证（目标≥80%）

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- [Nodriver](https://github.com/ultrafunkamsterdam/nodriver) - 出色的反检测浏览器自动化工具
- [Jina AI](https://jina.ai/) - 免费的高质量Embeddings API
- [jsDelivr](https://www.jsdelivr.com/) - 可靠的免费CDN服务
- [飞书开放平台](https://open.feishu.cn/) - 强大的企业协作平台

## 📞 联系方式

如有问题或建议，请提交[Issue](https://github.com/yourusername/collector/issues)。
