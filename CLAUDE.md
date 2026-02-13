# Collector - 飞书文章收集系统

通过飞书机器人自动收集网页/微信公众号文章到飞书知识库。

## 架构

```
URL → Cloudflare Workers → GitHub Actions → Python脚本 → 飞书知识库
```

核心流程:
- 文章: 抓取文章 → 下载图片 → 上传GitHub CDN → AI匹配目录 → 写入飞书
- 媒体: yt-dlp提取音频 → faster-whisper转录 → Gemini排版 → AI匹配目录 → 写入飞书

## 输入处理

用户通过飞书机器人发送消息，内容可能是纯URL，也可能包含额外文本（如分享时附带的标题、描述等）。
Webhook接收器需要从消息中**提取第一个有效URL**，忽略其余文本。
- 支持中文文本混排（中文无空格分隔，需正确截断URL边界）
- 支持常见分享格式：`《标题》链接`、`标题\n链接`、`链接+中文描述`等

## 知识库目录结构与匹配规则

```
知识库
├── 一级目录A
│   ├── 二级目录A1  ← 文档创建在这里
│   └── 二级目录A2  ← 文档创建在这里
├── 一级目录B
│   ├── 二级目录B1
│   └── 二级目录B2
└── 待整理          ← 兜底目录（一级）
```

- 匹配范围: 所有一级目录下的**二级目录**参与匹配
- 文档归属: 新建文档放到匹配的二级目录下
- 兜底逻辑: "待整理"是一级目录，LLM 无法匹配或异常时归入此目录
- 匹配方式: LLM 分类（非 Embedding 相似度），将文章标题+目录列表发给 LLM 判断归属
  - 使用 LLM 的世界知识理解文章主题（如"Trae"→AI编程工具）
  - 目录增删无需维护额外描述，自动适应
  - LLM 返回最匹配的目录名，无匹配则归入"待整理"

## 媒体转录

支持视频/音频/播客链接自动转录为格式化文本写入飞书文档。

- 支持平台: YouTube, Bilibili, Apple Podcasts, SoundCloud, Spotify 等 (yt-dlp 1700+ 平台)
- 处理流程: yt-dlp 提取音频 → faster-whisper 本地转录 → Gemini 语义排版 → Markdown → HTML → 飞书文档
- 全部免费，无需额外 API Key（faster-whisper 本地运行，Gemini 免费额度）
- 媒体文档无图片流程（跳过图片下载/上传/CDN 步骤）
- 降级策略: 媒体提取失败时自动降级为 Playwright 文章抓取

### Bilibili 反爬处理

B 站对非中国 IP 返回 HTTP 412，要求完成 JS 验证挑战生成验证 cookie。
GitHub Actions（美国 IP）必须先获取 cookie 才能下载。

解决方案: 用 Playwright 无头浏览器先访问 B 站视频页，完成 JS 验证后导出 cookies 文件给 yt-dlp。
- Playwright 访问视频页 → 等待 JS 验证完成 → 导出 Netscape cookies.txt
- yt-dlp 使用 `--cookies cookies.txt` 参数下载
- 项目已有 Playwright 依赖，无需新增

## 项目结构

```
src/
├── main.py                    # 入口
├── scrapers/                  # 网页抓取 (Playwright/Nodriver) + 媒体转录 (yt-dlp/faster-whisper)
├── feishu/                    # 飞书API (认证/目录/文档上传/HTML解析)
├── image_pipeline/            # 图片处理 (GitHub上传/jsDelivr CDN)
├── matchers/                  # AI目录匹配 (LLM分类) + 转录排版
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
- `LLM_API_KEY` - Google Gemini API密钥（目录分类匹配，免费，无需绑卡）
- `LLM_BASE_URL` - LLM API地址（默认Gemini OpenAI兼容接口）
- `LLM_MODEL` - LLM模型（默认gemini-2.5-flash）
- `GH_TOKEN/IMAGE_REPO` - GitHub图片托管

## 沟通语言

- 回复统一使用中文

## 技术栈

- Python 3.11+, Playwright/Nodriver, Google Gemini API (免费), 飞书 lark-oapi
- 部署: GitHub Actions + Cloudflare Workers
