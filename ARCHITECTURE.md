# 系统架构文档

飞书文章收集系统的详细技术架构。

## 系统概览

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户层                                    │
│  用户向飞书机器人发送包含文章URL的消息                             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Webhook接收层                                 │
│  Cloudflare Workers (免费 10万请求/天)                           │
│  - 接收飞书POST请求                                              │
│  - 验证签名                                                      │
│  - 提取URL                                                       │
│  - 触发GitHub Actions                                            │
│  CPU时间: ~20-35ms                                               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    执行层                                        │
│  GitHub Actions (免费 公开仓库无限分钟)                          │
│  - Ubuntu 22.04 Runner                                          │
│  - Python 3.11 + Chrome                                         │
│  - 执行Python脚本                                                │
│  超时: 10分钟                                                    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    处理层 (Python)                               │
│                                                                  │
│  1️⃣  抓取模块 (Nodriver)                                         │
│     - 启动无头Chrome                                             │
│     - 抓取普通网页/微信文章                                       │
│     - 提取标题、内容、图片                                        │
│     - 检测率: 1-5%                                               │
│     时间: 10-30秒                                                │
│                                                                  │
│  2️⃣  图片处理管道                                                │
│     - 下载所有图片 (处理Referrer)                                │
│     - 上传到GitHub仓库                                           │
│     - 生成jsDelivr CDN链接                                       │
│     - 替换文章中的图片URL                                         │
│     时间: 5-20秒                                                 │
│                                                                  │
│  3️⃣  AI匹配模块 (Jina AI)                                        │
│     - 获取文章标题embedding                                       │
│     - 获取所有目录embedding                                       │
│     - 计算余弦相似度                                              │
│     - 找到最佳匹配目录                                            │
│     - 阈值: 0.7                                                  │
│     时间: 2-5秒                                                  │
│                                                                  │
│  4️⃣  飞书集成模块                                                │
│     - 获取access token                                           │
│     - 获取知识库目录树                                            │
│     - 创建飞书文档                                                │
│     - 保存到匹配的目录                                            │
│     时间: 3-5秒                                                  │
│                                                                  │
│  总耗时: 20-60秒                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 组件详细设计

### 1. Webhook接收器 (Cloudflare Workers)

**职责**：
- 接收飞书服务器的POST请求
- 验证请求签名（防篡改）
- 解析消息内容提取URL
- 触发GitHub Actions

**技术栈**：
- JavaScript/Cloudflare Workers
- Fetch API
- GitHub REST API

**限制与应对**：
- CPU时间限制50ms → 实际使用20-35ms ✅
- 内存限制128MB → 仅处理JSON ✅
- 10万请求/天 → 远超日常使用 ✅

**代码流程**：
```javascript
request → 验证签名 → 解析JSON → 提取URL →
调用GitHub API → 返回200 OK
```

### 2. GitHub Actions执行环境

**职责**：
- 提供稳定的Linux执行环境
- 安装系统依赖（Chrome）
- 运行Python脚本
- 保存日志

**配置**：
```yaml
runs-on: ubuntu-latest
timeout: 10分钟
Python: 3.11
Chrome: stable
```

**触发方式**：
1. `repository_dispatch` - Webhook触发（生产）
2. `workflow_dispatch` - 手动触发（测试）

**环境变量**：通过GitHub Secrets安全传递

### 3. 抓取模块 (Nodriver)

**架构**：
```
NodriverScraper
├── scrape() - 主入口
├── _scrape_weixin() - 微信特化
├── _scrape_generic() - 通用抓取
├── _extract_title()
├── _extract_content()
├── _extract_images()
└── is_weixin_article() - URL判断
```

**微信文章特殊处理**：
- 识别`mp.weixin.qq.com`域名
- 使用微信特定选择器
  - 标题: `h1#activity-name`
  - 内容: `#js_content`
  - 图片: `data-src`属性
- 等待更长时间（避免检测）

**反检测策略**：
- 使用Nodriver（最佳工具）
- 无头模式运行
- 随机User-Agent
- 模拟真实浏览器行为

### 4. 图片处理管道

**流程**：
```
原始图片URL → 下载 → 上传GitHub → 生成CDN链接 → 替换
```

**组件**：

#### ImageDownloader
```python
download_images(urls: List[str]) -> List[Tuple[str, str]]
# 返回: [(原始URL, 本地路径), ...]
```

- 设置正确Referer（绕过防盗链）
- 验证Content-Type
- 处理下载失败（重试3次）

#### GitHubUploader
```python
batch_upload_images(paths: List) -> List[Tuple[str, str]]
# 返回: [(原始URL, GitHub路径), ...]
```

- 使用PyGithub SDK
- 文件路径：`images/YYYY/MM/filename.jpg`
- 检查文件是否已存在（去重）

#### JsDelivrCDN
```python
generate_cdn_url(github_path: str) -> str
# 格式: https://cdn.jsdelivr.net/gh/user/repo@branch/path
```

- jsDelivr全球CDN
- 永久免费
- 100% SLA保证

**为什么要重新托管图片？**

问题：
- 微信图片有Referrer防盗链
- 图片URL可能包含临时token
- 原站图片可能失效

解决：
- 下载到本地（浏览器上下文自动处理Referrer）
- 上传到GitHub永久存储
- 通过jsDelivr CDN加速访问

### 5. AI匹配模块 (Jina AI)

**架构**：
```
JinaClient
├── get_embedding(text) - 单个文本
└── get_embeddings_batch(texts) - 批量

SimilarityMatcher
├── compute_embeddings_for_directories() - 目录embeddings
├── match_directory() - 匹配逻辑
├── _cosine_similarity() - 余弦相似度
└── _determine_confidence() - 置信度
```

**匹配算法**：

1. **生成embeddings**：
   ```python
   title_embedding = jina.get_embedding(article_title)
   dir_embeddings = [jina.get_embedding(d.name) for d in directories]
   ```

2. **计算相似度**：
   ```python
   similarity = cosine_similarity(title_embedding, dir_embedding)
   # 范围: 0.0 - 1.0
   ```

3. **阈值判断**：
   ```python
   if similarity >= 0.7:  # 用户指定
       return matched_directory
   else:
       return unorganized_folder  # 兜底
   ```

4. **置信度**：
   - `high`: similarity >= 0.85
   - `medium`: 0.70 <= similarity < 0.85
   - `low`: similarity < 0.70

**为什么用Jina AI？**
- 免费额度充足（1M tokens/月）
- 中文支持优秀
- API简单易用
- 无需本地GPU

**成本控制**：
- 每次处理约200 tokens
- 500篇/月 = 100K tokens
- 远低于免费额度 ✅

### 6. 飞书集成模块

**组件**：

#### AuthManager
- 管理tenant_access_token
- 自动刷新（有效期2小时）
- 提前5分钟刷新

#### DirectoryManager
```python
get_all_directories() - 递归获取所有目录
get_leaf_directories() - 仅叶子节点
find_unorganized_folder() - 查找"待整理"
get_matchable_directories() - 返回(可匹配目录, 兜底目录)
```

**为什么只匹配叶子节点？**
- 飞书限制：只有叶子节点可创建文档
- 非叶子节点是文件夹，不能直接保存文档

#### DocumentUploader
```python
create_document(
    directory: Directory,
    title: str,
    content: str,
    author: Optional[str],
    publish_date: Optional[str],
    source_url: Optional[str]
) -> str  # 返回文档URL
```

- 构建Markdown格式
- 添加元信息（作者、日期、原文链接）
- 嵌入CDN图片链接
- 调用飞书API创建

## 数据流

### 完整处理流程

```
1. 用户 → 飞书机器人: "https://example.com/article"

2. 飞书 → Cloudflare Workers: POST /webhook
   {
     "event": {
       "message": {
         "content": {"text": "https://example.com/article"}
       }
     }
   }

3. Cloudflare Workers → GitHub API: POST /repos/.../dispatches
   {
     "event_type": "scrape-article",
     "client_payload": {
       "url": "https://example.com/article"
     }
   }

4. GitHub Actions 触发 → Python脚本:
   python src/main.py "https://example.com/article"

5. Python脚本执行:
   a. Nodriver抓取
      → ArticleData(title="...", content="...", images=[...])

   b. 下载图片
      → [(url1, local_path1), (url2, local_path2), ...]

   c. 上传GitHub
      → [(url1, github_path1), (url2, github_path2), ...]

   d. 生成CDN链接
      → [(url1, cdn_url1), (url2, cdn_url2), ...]

   e. 替换图片URL
      → content_with_cdn_images

   f. Jina AI匹配
      → MatchResult(directory="技术/前端", similarity=0.85)

   g. 创建飞书文档
      → doc_url: "https://xxx.feishu.cn/xxx"

6. 完成 → 飞书知识库中出现新文档
```

## 错误处理策略

### 多层兜底机制

```
Level 1: 重试机制
├── 网络请求: 3次重试
├── API调用: 3次重试
└── 抓取失败: 3次重试

Level 2: 降级处理
├── Jina API失败 → 使用"待整理"文件夹
├── 图片上传失败 → 跳过该图片，继续其他
└── 部分内容失败 → 保存已获取的部分

Level 3: 通知用户
├── 完全失败 → 记录日志，通知用户
└── 部分成功 → 创建文档，备注问题
```

### 异常类型

```python
class JinaAPIQuotaError(Exception):
    """Jina API额度耗尽 → 自动使用待整理文件夹"""

class ScrapingError(Exception):
    """抓取失败 → 重试3次后通知用户"""

class UploadError(Exception):
    """上传失败 → 跳过图片或重试"""
```

## 性能优化

### 1. 并行处理
```python
# 图片下载可并行
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(download, url) for url in urls]
```

### 2. 缓存策略
```python
# 目录embeddings不缓存（每次重新计算）
# 原因：目录结构变化时自动更新
# Jina API足够快（<5秒）
```

### 3. 资源管理
```python
# 及时清理下载的图片
try:
    process_article(url)
finally:
    cleanup_downloads()
```

## 安全考虑

### 1. 认证
- GitHub Token: 最小权限原则（repo, workflow）
- 飞书App Secret: 存储在GitHub Secrets
- Jina API Key: 环境变量，不提交代码

### 2. 验证
- Webhook签名验证（防篡改）
- URL格式验证（防注入）
- 图片Content-Type验证（防恶意文件）

### 3. 限制
- 超时控制（10分钟）
- 重试上限（3次）
- 文件大小限制（图片5MB）

## 可扩展性

### 横向扩展
- GitHub Actions支持20个并发
- Cloudflare Workers无限请求（10万/天免费）
- 可添加队列系统处理批量请求

### 纵向扩展
- 替换为更强大的模型
- 添加更多抓取源
- 增加更复杂的匹配逻辑

### 未来增强
1. **批量处理**：一次发送多个URL
2. **进度反馈**：飞书卡片显示实时进度
3. **手动调整**：命令移动文章到其他目录
4. **统计报告**：定期发送匹配准确率
5. **学习优化**：基于用户调整改进匹配

## 监控与维护

### 关键指标
- 处理成功率: 目标 > 95%
- 平均处理时间: 目标 < 60秒
- 匹配准确率: 目标 >= 80%
- API额度使用: 监控防止耗尽

### 日志级别
- DEBUG: 开发调试
- INFO: 正常流程（生产默认）
- WARNING: 可恢复的错误
- ERROR: 需要关注的失败

### 告警机制
- GitHub Actions失败 → 邮件通知
- API额度告警 → 80%时预警
- 连续失败 → 检查系统状态

## 成本分析

### 完全免费架构

| 服务 | 免费额度 | 实际使用 | 余量 | 成本 |
|------|----------|----------|------|------|
| GitHub Actions | 无限（公开） | 20分钟/天 | 无限 | $0 |
| Cloudflare Workers | 10万请求/天 | 17请求/天 | 99.98% | $0 |
| Jina AI | 1M tokens/月 | 100K/月 | 90% | $0 |
| GitHub存储 | 无限（公开） | 5GB/月 | 无限 | $0 |
| jsDelivr | 无限带宽 | 5GB/月 | 无限 | $0 |
| **总计** | - | - | - | **$0** |

### 可扩展性分析

支持规模：
- 每天处理: 100篇文章
- 每月处理: 3000篇文章
- 成本增加: $0

瓶颈：
- Jina API额度（1M tokens/月）
- GitHub Actions并发（20个）
- Cloudflare Workers请求（10万/天）

结论：**完全满足个人/小团队使用** ✅
