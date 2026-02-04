# 部署指南

完整的系统部署步骤。

## 前置要求

- Python 3.11+
- GitHub账号
- Cloudflare账号
- 飞书开放平台账号
- Jina AI账号

## 第一步：注册所需服务

### 1. 飞书开放平台

1. 访问 https://open.feishu.cn/
2. 创建企业自建应用
3. 记录以下信息：
   - App ID
   - App Secret
   - Verification Token
   - Encrypt Key（可选）
4. 开通权限：
   - `im:message`（接收消息）
   - `im:message.group_at_msg`（群消息）
   - `docx:document`（创建文档）
   - `wiki:wiki`（知识库访问）

### 2. Jina AI

1. 访问 https://jina.ai/
2. 使用邮箱注册（完全免费）
3. 创建API Key
4. 免费额度：1M tokens/月

### 3. GitHub

1. 创建两个仓库：
   - `collector` - 主项目仓库（本仓库）
   - `collector-images` - 图片存储仓库（公开）
2. 创建Personal Access Token：
   - 访问 Settings > Developer settings > Personal access tokens
   - 权限：`repo`, `workflow`

### 4. Cloudflare

1. 注册账号：https://cloudflare.com/
2. 完全免费，无需信用卡

## 第二步：配置GitHub Secrets

在`collector`仓库的Settings > Secrets and variables > Actions中添加：

```
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=xxx
FEISHU_ENCRYPT_KEY=xxx
FEISHU_KNOWLEDGE_SPACE_ID=xxx
FEISHU_UNORGANIZED_FOLDER_NAME=待整理

JINA_API_KEY=jina_xxx

GH_TOKEN=ghp_xxx
IMAGE_REPO=yourusername/collector-images
```

## 第三步：部署Cloudflare Workers

```bash
# 进入webhook目录
cd webhook-receiver

# 安装Wrangler CLI
npm install -g wrangler

# 登录Cloudflare
wrangler login

# 配置secrets
wrangler secret put FEISHU_VERIFICATION_TOKEN
wrangler secret put GH_TOKEN
wrangler secret put GH_REPO

# 部署
wrangler deploy
```

记录部署后的URL，例如：
```
https://feishu-webhook-receiver.your-subdomain.workers.dev
```

## 第四步：配置飞书机器人

1. 进入飞书开放平台
2. 选择你的应用
3. 进入"事件订阅"
4. 填入Webhook URL（上一步的URL）
5. 添加订阅事件：
   - `im.message.receive_v1` - 接收消息
6. 保存配置

## 第五步：创建知识库目录

在飞书知识库中创建以下结构：

```
知识库/
├── 技术/
│   ├── 前端/
│   ├── 后端/
│   └── 数据库/
├── 产品/
│   ├── 需求分析/
│   └── 用户研究/
├── 业务/
│   ├── 市场分析/
│   └── 运营策略/
└── 待整理/  # 重要：必须存在
```

**注意**：
- 确保"待整理"文件夹存在（用作兜底目录）
- 只有叶子节点（末级目录）可以用于保存文档

## 第六步：测试系统

### 1. 本地测试

```bash
# 安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑.env填入实际配置

# 测试抓取
cd src
python main.py "https://example.com/article"
```

### 2. 端到端测试

1. 向飞书机器人发送消息：
   ```
   https://example.com/article
   ```
2. 查看GitHub Actions运行状态
3. 等待约30-60秒
4. 检查飞书知识库是否出现新文档

## 第七步：监控和维护

### 查看GitHub Actions日志

1. 进入仓库的Actions标签
2. 查看最近的workflow运行
3. 检查是否有错误

### 查看Cloudflare Workers日志

```bash
wrangler tail
```

### 监控API额度

- **Jina AI**: 查看 https://jina.ai/dashboard
- **GitHub Actions**: 查看仓库Settings > Actions
- **Cloudflare Workers**: 查看Cloudflare Dashboard

## 常见问题

### 1. 文章抓取失败

**原因**：可能是反爬虫限制

**解决**：
- 检查GitHub Actions日志
- 确认Chrome安装成功
- 微信文章需要等待更长时间

### 2. 图片上传失败

**原因**：GitHub Token权限不足

**解决**：
- 确认Token有`repo`权限
- 确认`collector-images`仓库存在且可访问

### 3. 目录匹配失败

**原因**：Jina API额度用尽或配置错误

**解决**：
- 检查API key是否正确
- 查看API使用量
- 文章会自动进入"待整理"文件夹

### 4. Webhook接收失败

**原因**：飞书签名验证或配置错误

**解决**：
- 检查Webhook URL是否正确
- 查看Cloudflare Workers日志
- 确认secrets配置正确

## 性能指标

- **抓取时间**：10-30秒
- **图片处理**：5-20秒（取决于图片数量）
- **AI匹配**：2-5秒
- **文档创建**：3-5秒
- **总耗时**：20-60秒

## 成本分析

所有服务完全免费：
- GitHub Actions：公开仓库无限制
- Cloudflare Workers：10万请求/天
- Jina AI：1M tokens/月
- jsDelivr CDN：无限带宽
- **总成本：$0/月**

## 扩展建议

1. **批量处理**：添加队列系统处理多篇文章
2. **进度反馈**：通过飞书卡片显示处理进度
3. **统计报告**：定期发送匹配准确率报告
4. **手动调整**：添加命令移动文章到其他目录
