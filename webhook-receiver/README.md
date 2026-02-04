# Cloudflare Workers Webhook接收器

飞书机器人消息的Webhook接收器，用于触发GitHub Actions。

## 部署步骤

### 1. 安装Wrangler CLI

```bash
npm install -g wrangler
```

### 2. 登录Cloudflare

```bash
wrangler login
```

### 3. 配置Secrets

```bash
# 飞书验证token
wrangler secret put FEISHU_VERIFICATION_TOKEN

# 飞书加密key（可选）
wrangler secret put FEISHU_ENCRYPT_KEY

# GitHub Personal Access Token
wrangler secret put GH_TOKEN

# GitHub仓库名（格式：owner/repo）
wrangler secret put GH_REPO
```

### 4. 部署

```bash
wrangler deploy
```

部署成功后会得到一个URL，类似：
```
https://feishu-webhook-receiver.your-subdomain.workers.dev
```

### 5. 配置飞书机器人

1. 进入飞书开放平台
2. 选择你的应用
3. 进入"事件订阅"设置
4. 填入Webhook URL（上一步得到的URL）
5. 添加订阅事件：`im.message.receive_v1`
6. 保存配置

## 本地测试

```bash
# 启动本地开发服务器
wrangler dev

# 使用curl测试
curl -X POST http://localhost:8787 \
  -H "Content-Type: application/json" \
  -d '{"event":{"message":{"content":"{\"text\":\"https://example.com/article\"}"}}}'
```

## 日志查看

```bash
# 查看实时日志
wrangler tail
```

## 工作流程

1. 用户向飞书机器人发送包含URL的消息
2. 飞书服务器发送POST请求到Cloudflare Workers
3. Workers验证请求并提取URL
4. Workers调用GitHub API触发repository_dispatch事件
5. GitHub Actions开始执行文章抓取流程

## CPU时间分析

- 接收请求：~5ms
- 验证签名：~2-5ms
- 解析JSON：~1ms
- 调用GitHub API：~10-20ms
- 返回响应：~2ms
- **总计**：约20-35ms（远低于50ms限制）
