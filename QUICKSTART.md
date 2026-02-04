# 快速开始指南

5分钟快速启动飞书文章收集系统。

## 前置条件检查

确保你有：
- [ ] Python 3.11+ 已安装
- [ ] Git 已安装
- [ ] 飞书企业账号
- [ ] GitHub账号
- [ ] 稳定的网络连接

## 第一步：克隆项目

```bash
git clone https://github.com/yourusername/collector.git
cd collector
```

## 第二步：安装依赖

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate  # macOS/Linux
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

## 第三步：配置环境变量

```bash
# 复制配置模板
cp .env.example .env

# 编辑配置文件
nano .env  # 或使用你喜欢的编辑器
```

### 最小配置（本地测试）

```bash
# 飞书配置（从飞书开放平台获取）
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_KNOWLEDGE_SPACE_ID=xxx

# Jina AI配置（从 https://jina.ai 注册获取）
JINA_API_KEY=jina_xxx

# GitHub配置（从 https://github.com/settings/tokens 创建）
GITHUB_TOKEN=ghp_xxx
GITHUB_REPO=yourusername/collector-images
```

### 如何获取配置

#### 飞书配置

1. 访问 https://open.feishu.cn/
2. 创建企业自建应用
3. 记录App ID和App Secret
4. 创建或获取知识库ID（从知识库URL中提取）

#### Jina AI配置

1. 访问 https://jina.ai/
2. 使用邮箱注册（完全免费）
3. 创建API Key

#### GitHub配置

1. 创建新仓库 `collector-images`（必须公开）
2. 访问 https://github.com/settings/tokens
3. 创建Personal Access Token
4. 权限选择：`repo`, `workflow`

## 第四步：测试运行

### 测试简单网页

```bash
cd src
python main.py "https://example.com"
```

预期输出：
```
2026-02-04 10:00:00 - collector - INFO - Starting to process article: https://example.com
2026-02-04 10:00:05 - collector - INFO - ✓ Article scraped: Example Domain
...
2026-02-04 10:00:45 - collector - INFO - SUCCESS!
2026-02-04 10:00:45 - collector - INFO - Document URL: https://xxx.feishu.cn/xxx
```

### 测试微信文章（可选）

```bash
python main.py "https://mp.weixin.qq.com/s/实际的文章ID"
```

## 第五步：验证结果

1. 打开飞书知识库
2. 检查文章是否出现
3. 验证图片是否正常显示
4. 确认文章分类是否合理

## 常见问题

### Q1: 找不到Chrome浏览器

**错误信息**：
```
Could not find Chrome binary
```

**解决方案**：
```bash
# macOS
brew install --cask google-chrome

# Ubuntu/Debian
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb

# CentOS/RHEL
sudo yum install google-chrome-stable
```

### Q2: 飞书API认证失败

**错误信息**：
```
Failed to get Feishu access token
```

**检查**：
1. App ID和App Secret是否正确
2. 应用是否已启用
3. 是否有相关权限（im、docx、wiki）

### Q3: 图片上传失败

**错误信息**：
```
Failed to upload to GitHub
```

**检查**：
1. GitHub Token是否有`repo`权限
2. `collector-images`仓库是否存在
3. 仓库是否为公开（Public）

### Q4: Jina API额度用尽

**错误信息**：
```
Jina API quota exceeded
```

**说明**：
- 文章会自动进入"待整理"文件夹
- 每月1日额度自动重置
- 可在 https://jina.ai/dashboard 查看使用情况

### Q5: 找不到"待整理"文件夹

**错误信息**：
```
'待整理' folder not found in knowledge space
```

**解决方案**：
1. 在飞书知识库手动创建"待整理"文件夹
2. 确保文件夹名称完全一致（中文）
3. 或修改`.env`中的`FEISHU_UNORGANIZED_FOLDER_NAME`

## 下一步

✅ 本地测试成功后，继续：

1. **部署到生产环境**：阅读 [DEPLOYMENT.md](DEPLOYMENT.md)
2. **运行测试套件**：阅读 [TESTING.md](TESTING.md)
3. **了解架构细节**：阅读 [README.md](README.md)

## 需要帮助？

- 📖 查看完整文档：[README.md](README.md)
- 🐛 提交Issue：https://github.com/yourusername/collector/issues
- 💬 讨论区：https://github.com/yourusername/collector/discussions

## 时间线

- **第1-2周**：完成本地测试，熟悉系统
- **第3周**：部署到GitHub Actions
- **第4周**：部署Cloudflare Workers
- **第5周**：完整端到端测试和优化

祝使用愉快！🎉
