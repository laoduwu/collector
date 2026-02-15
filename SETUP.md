# 部署指南 - 零基础搭建飞书文章收集系统

本指南面向**非程序员**，全程在网页上操作，不需要写任何代码。

## 系统简介

向飞书机器人发送链接，系统自动抓取文章/视频内容，写入飞书知识库并智能分类。

```
你发链接给飞书机器人 → 自动抓取内容 → AI智能分类 → 写入飞书知识库
```

**完全免费**，无需绑定信用卡。

---

## 你需要准备的账号

| 服务 | 用途 | 注册地址 | 费用 |
|------|------|----------|------|
| 飞书 | 机器人 + 知识库 | https://www.feishu.cn | 免费 |
| GitHub | 代码托管 + 图片存储 | https://github.com | 免费 |
| Google | Gemini AI（文章分类） | https://aistudio.google.com | 免费 |
| Cloudflare | Webhook 转发 | https://cloudflare.com | 免费 |

---

## 第一步：复制项目到你的 GitHub

1. 打开项目主页：https://github.com/laoduwu/collector
2. 点击右上角绿色按钮 **「Use this template」** → **「Create a new repository」**
3. 填写：
   - Repository name：`collector`（或你喜欢的名字）
   - 选择 **Public**（公开仓库，GitHub Actions 免费无限制）
4. 点击 **「Create repository」**

> 现在你拥有了自己的 `collector` 仓库，记住你的仓库地址，格式为 `你的用户名/collector`

---

## 第二步：创建图片存储仓库

文章中的图片需要一个地方存放。

1. 在 GitHub 点击右上角 **「+」** → **「New repository」**
2. 填写：
   - Repository name：`collector-images`
   - 选择 **Public**（必须公开，图片才能在飞书中显示）
3. 勾选 **「Add a README file」**
4. 点击 **「Create repository」**

---

## 第三步：创建 GitHub Token

这个 Token 让系统能够上传图片和触发任务。

1. 打开：https://github.com/settings/tokens?type=beta
2. 点击 **「Generate new token」**
3. 填写：
   - Token name：`collector-bot`
   - Expiration：选择 **「No expiration」**（永不过期）
   - Repository access：选择 **「All repositories」**
   - Permissions → Repository permissions：
     - **Contents**：Read and write
     - **Actions**：Read and write
4. 点击 **「Generate token」**
5. **立即复制 Token**（以 `github_pat_` 开头），关闭页面后就看不到了

> 把这个 Token 保存到记事本，后面要用两次。

---

## 第四步：获取 Gemini API Key

Gemini 用于智能分类文章到对应目录，以及格式化视频转录文本。

1. 打开：https://aistudio.google.com/apikey
2. 用 Google 账号登录
3. 点击 **「Create API key」**
4. 复制 API Key（以 `AIza` 开头）

> 免费额度完全够用，无需绑卡。

---

## 第五步：创建飞书应用

### 5.1 创建应用

1. 打开飞书开放平台：https://open.feishu.cn/
2. 点击 **「创建自建应用」**
3. 填写应用名称（如「文章收集器」），上传一个图标
4. 创建完成后，进入应用详情页

### 5.2 记录凭证

在应用的 **「凭证与基础信息」** 页面，记录以下信息：

| 字段 | 说明 |
|------|------|
| App ID | 以 `cli_` 开头 |
| App Secret | 点击查看并复制 |

### 5.3 配置事件订阅

1. 左侧菜单点击 **「事件与回调」** → **「事件订阅」**（旧版UI路径可能不同，找到「事件订阅」即可）
2. 加密策略：
   - **Verification Token**：记录下来
   - **Encrypt Key**：记录下来（如果页面上有的话；没有可留空）
3. 请求地址先空着，等部署好 Cloudflare Worker 后再填

### 5.4 添加权限

左侧菜单点击 **「权限管理」**，搜索并开通以下权限：

| 权限名称 | 权限标识 |
|----------|----------|
| 获取与发送单聊、群组消息 | `im:message` |
| 获取群组中所有消息 | `im:message.group_at_msg` 或 `im:message.p2p_msg` |
| 查看、评论、编辑和管理知识库 | `wiki:wiki` |
| 查看、评论、编辑和管理文档 | `docx:document` |
| 上传、下载文件及管理文件权限 | `drive:drive` |

### 5.5 创建机器人

1. 左侧菜单点击 **「应用功能」** → **「机器人」**
2. 开启机器人功能

### 5.6 发布应用

1. 左侧菜单点击 **「版本管理与发布」**
2. 创建版本并提交审核
3. 管理员审批通过后，应用上线

### 5.7 获取知识库 Space ID

1. 在飞书中打开你的知识库
2. 看浏览器地址栏，找到类似 `https://xxx.feishu.cn/wiki/space/7xxx` 的 URL
3. 最后的数字 `7xxx...` 就是 **知识库 Space ID**

---

## 第六步：创建知识库目录

在飞书知识库中创建你想要的分类结构，**必须是两级目录**：

```
你的知识库
├── AI相关/
│   ├── AI编程类/
│   ├── AI产品/
│   └── AI论文/
├── 技术/
│   ├── 前端开发/
│   ├── 后端开发/
│   └── 数据库/
├── 商业/
│   ├── 创业/
│   └── 投资/
└── 待整理/          ← 【必须有】兜底目录
```

**重要规则**：
- 文章会被分类到**二级目录**下（如「AI编程类」）
- **「待整理」是一级目录**，AI 无法分类时文章会放在这里
- 「待整理」这个名字必须准确匹配（或者你在后面配置中自定义名字）

---

## 第七步：部署 Cloudflare Worker

Cloudflare Worker 负责接收飞书消息并转发给 GitHub Actions。

### 7.1 登录 Cloudflare

1. 打开：https://dash.cloudflare.com/
2. 注册或登录

### 7.2 创建 Worker

1. 左侧菜单点击 **「Workers 和 Pages」** → **「创建」**
2. 选择 **「创建 Worker」**
3. 名称填：`feishu-webhook`（或其他你喜欢的名字）
4. 点击 **「部署」**（先用默认代码部署）
5. 部署成功后点击 **「编辑代码」**

### 7.3 粘贴代码

1. 删除编辑器中的所有默认代码
2. 打开你仓库中的文件：`https://github.com/你的用户名/collector/blob/main/webhook-receiver/index.js`
3. 点击 **「Raw」** 按钮查看原始代码
4. 全选复制，粘贴到 Cloudflare 编辑器中
5. 点击右上角 **「部署」**

### 7.4 配置环境变量

1. 回到 Worker 页面，点击 **「设置」** → **「变量和机密」**
2. 点击 **「添加」**，逐一添加以下变量（类型选**机密**）：

| 变量名 | 值 |
|--------|-----|
| `FEISHU_VERIFICATION_TOKEN` | 第五步记录的 Verification Token |
| `FEISHU_ENCRYPT_KEY` | 第五步记录的 Encrypt Key（没有则跳过） |
| `GH_TOKEN` | 第三步创建的 GitHub Token |
| `GH_REPO` | `你的用户名/collector`（你的仓库地址） |

3. 保存后，点击 **「部署」** 使变量生效

### 7.5 记录 Worker URL

在 Worker 概览页面，找到你的 Worker URL，格式类似：
```
https://feishu-webhook.你的子域名.workers.dev
```

### 7.6 回填飞书 Webhook 地址

1. 回到飞书开放平台，进入你的应用
2. 找到 **「事件订阅」** 页面
3. 在 **「请求地址」** 中填入上面的 Worker URL
4. 点击保存，飞书会自动发送验证请求

> 如果验证通过，会显示绿色「已验证」。如果失败，检查 Worker URL 和 Verification Token 是否正确。

5. 在下方 **「添加事件」** 中，添加：`im.message.receive_v1`（接收消息）

---

## 第八步：配置 GitHub Actions Secrets

这是最关键的一步，把所有凭证配置到 GitHub 仓库中。

1. 打开你的 `collector` 仓库
2. 点击 **「Settings」** → 左侧 **「Secrets and variables」** → **「Actions」**
3. 点击 **「New repository secret」**，逐一添加：

### 必填项

| Name | Value | 说明 |
|------|-------|------|
| `FEISHU_APP_ID` | `cli_xxx` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | `xxx` | 飞书应用 App Secret |
| `FEISHU_VERIFICATION_TOKEN` | `xxx` | 飞书 Verification Token |
| `FEISHU_KNOWLEDGE_SPACE_ID` | `7xxx...` | 知识库 Space ID |
| `LLM_API_KEY` | `AIza...` | Gemini API Key |
| `GH_TOKEN` | `github_pat_xxx` | GitHub Token |
| `IMAGE_REPO` | `你的用户名/collector-images` | 图片仓库地址 |

### 可选项（有默认值，通常不需要改）

| Name | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_ENCRYPT_KEY` | 空 | 飞书 Encrypt Key |
| `FEISHU_UNORGANIZED_FOLDER_NAME` | `待整理` | 兜底目录名称 |
| `LLM_BASE_URL` | Gemini 地址 | LLM API 地址 |
| `LLM_MODEL` | `gemini-2.5-flash` | LLM 模型名 |
| `IMAGE_BRANCH` | `main` | 图片仓库分支 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

---

## 第九步：测试

### 给机器人发消息

1. 在飞书中搜索你创建的机器人名称
2. 给它发送一个文章链接，例如：
   ```
   https://sspai.com/post/44428
   ```
3. 等待 30-60 秒

### 查看运行状态

1. 打开 GitHub 仓库 → **「Actions」** 标签页
2. 应该能看到一个正在运行或已完成的 `Scrape Article` 任务
3. 点进去可以看详细日志

### 检查结果

打开飞书知识库，查看是否出现了新文档。文档会自动：
- 放入 AI 判断最合适的二级目录
- 保留原文格式和图片
- 在文末标注来源链接

---

## 支持的链接类型

| 类型 | 示例 | 处理方式 |
|------|------|----------|
| 普通网页文章 | 少数派、知乎专栏、博客 | 抓取全文 + 图片 |
| 微信公众号 | `mp.weixin.qq.com` | 抓取全文 + 图片 |
| Bilibili 视频 | `bilibili.com`, `b23.tv` | 提取音频 → 语音转文字 → AI排版 |
| YouTube 视频 | `youtube.com`, `youtu.be` | 提取音频 → 语音转文字 → AI排版 |
| 播客 | Apple Podcasts, Spotify 等 | 提取音频 → 语音转文字 → AI排版 |

---

## 常见问题

### 机器人收到消息但没反应

- 检查飞书应用的 **事件订阅** 是否添加了 `im.message.receive_v1`
- 检查 Webhook URL 是否正确（浏览器直接打开应该显示 `Worker is running!`）
- 检查 Cloudflare Worker 的环境变量 `GH_TOKEN` 和 `GH_REPO` 是否正确

### GitHub Actions 运行失败

- 点进失败的运行查看日志
- 最常见原因：Secrets 配置缺失或错误
- 确认所有必填 Secrets 都已添加

### 文章分类不准确

- AI 分类基于文章标题，标题越明确分类越准
- 无法确定时会放入「待整理」目录
- 你可以手动在飞书中移动文档到正确目录

### 视频转录效果不好

- 转录质量取决于视频中的语音清晰度
- 背景音乐太响或多人同时说话会降低准确率
- AI 会尽量修正识别错误并格式化输出

### 图片显示不出来

- 确认 `collector-images` 仓库是 **Public**（公开）
- 确认 GitHub Token 有 `Contents: Read and write` 权限

---

## 成本说明

| 服务 | 免费额度 | 说明 |
|------|----------|------|
| GitHub Actions | 公开仓库无限制 | 每次运行约 1-4 分钟 |
| Cloudflare Workers | 10 万次请求/天 | 远超日常使用 |
| Gemini API | 免费额度充足 | 每篇文章调用 1-2 次 |
| jsDelivr CDN | 无限带宽 | 用于图片加速 |
| **总计** | **$0/月** | |
