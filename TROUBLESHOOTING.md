# 故障排除指南

系统常见问题的诊断和解决方案。

## 目录

- [抓取问题](#抓取问题)
- [图片问题](#图片问题)
- [API问题](#api问题)
- [飞书问题](#飞书问题)
- [部署问题](#部署问题)
- [性能问题](#性能问题)

## 抓取问题

### 问题1：无法抓取网页内容

**症状**：
```
Failed to scrape https://example.com: Timeout
```

**可能原因**：
1. 网站反爬虫限制
2. 网络连接问题
3. 页面加载时间过长

**解决方案**：

```python
# 方案1：增加等待时间（修改 nodriver_scraper.py）
await asyncio.sleep(5)  # 从3秒增加到5秒

# 方案2：添加更多重试
@retry_with_backoff(max_retries=5, base_delay=10.0)  # 增加重试次数

# 方案3：更换User-Agent
headers = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)'
}
```

### 问题2：微信文章抓取失败率高

**症状**：
```
WeChat article scraping failed: Element not found
```

**原因**：微信反爬虫机制更新

**解决方案**：

```bash
# 1. 更新Nodriver到最新版本
pip install --upgrade nodriver

# 2. 增加随机延迟
import random
await asyncio.sleep(random.uniform(5, 10))

# 3. 使用备用选择器
try:
    content = await page.find('#js_content')
except:
    content = await page.find('.rich_media_content')
```

### 问题3：提取的内容不完整

**症状**：内容只有开头几段

**原因**：
1. 懒加载内容未加载
2. 动态内容未触发

**解决方案**：

```python
# 滚动页面触发懒加载
async def scroll_page(page):
    for _ in range(3):
        await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        await asyncio.sleep(2)

# 使用
await scroll_page(page)
content = await extract_content(page)
```

## 图片问题

### 问题4：图片下载失败

**症状**：
```
Failed to download image: 403 Forbidden
```

**原因**：Referrer防盗链

**解决方案**：

```python
# 确保设置正确的Referer
headers = {
    'User-Agent': '...',
    'Referer': image_url,  # 使用图片URL自身作为Referer
    'Accept': 'image/*'
}
```

### 问题5：GitHub上传超时

**症状**：
```
GitHub API error: timeout
```

**解决方案**：

```bash
# 1. 检查网络连接
ping github.com

# 2. 使用代理（如果在受限网络）
export HTTPS_PROXY=http://proxy.example.com:8080

# 3. 减小图片大小
from PIL import Image

def compress_image(path):
    img = Image.open(path)
    img.save(path, quality=85, optimize=True)
```

### 问题6：jsDelivr CDN链接无法访问

**症状**：图片在飞书中显示失败

**原因**：
1. GitHub仓库未公开
2. 文件路径错误
3. jsDelivr缓存未更新

**解决方案**：

```bash
# 1. 确认仓库为Public
gh repo view yourusername/collector-images

# 2. 清除jsDelivr缓存（需要等待）
# 访问：https://purge.jsdelivr.net/gh/user/repo@branch/path

# 3. 使用备用CDN
# 修改 jsdelivr_cdn.py
cdn_url = f"https://raw.githubusercontent.com/{self.repo_name}/{self.branch}/{github_path}"
```

## API问题

### 问题7：Jina AI 429错误

**症状**：
```
Jina API quota exceeded
```

**影响**：文章会自动进入"待整理"文件夹

**检查额度**：
```bash
# 访问Jina AI Dashboard
open https://jina.ai/dashboard

# 查看当前使用量和限制
```

**解决方案**：
1. 等待月初额度重置
2. 升级到付费计划（如需要）
3. 暂时接受所有文章进入"待整理"

### 问题8：飞书API 401/403错误

**症状**：
```
Failed to get Feishu access token: Invalid credentials
```

**检查清单**：
- [ ] App ID正确
- [ ] App Secret正确
- [ ] 应用已发布/启用
- [ ] 权限已开通（im, docx, wiki）

**解决方案**：

```bash
# 1. 重新获取配置
# 访问：https://open.feishu.cn/app

# 2. 测试API连接
curl -X POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal \
  -H "Content-Type: application/json" \
  -d '{"app_id":"cli_xxx","app_secret":"xxx"}'

# 3. 检查权限
# 应用管理 -> 权限管理 -> 确认所需权限已开通
```

### 问题9：GitHub API Rate Limit

**症状**：
```
GitHub API error: 403 rate limit exceeded
```

**检查限制**：
```bash
curl -H "Authorization: Bearer $GH_TOKEN" \
  https://api.github.com/rate_limit
```

**解决方案**：
1. 使用Personal Access Token（限制提高到5000/小时）
2. 等待限制重置（每小时重置）
3. 批量操作减少API调用

## 飞书问题

### 问题10：找不到知识库目录

**症状**：
```
'待整理' folder not found in knowledge space
```

**检查**：
```bash
# 运行调试脚本
cd src
python -c "
from feishu.auth_manager import AuthManager
from feishu.directory_manager import DirectoryManager
auth = AuthManager()
dir_mgr = DirectoryManager(auth)
dirs = dir_mgr.get_all_directories()
for d in dirs:
    print(f'{d.name} - {d.node_token}')
"
```

**解决方案**：
1. 在飞书中手动创建"待整理"文件夹
2. 确保文件夹名称完全一致（包括中文字符）
3. 检查Space ID是否正确

### 问题11：无法创建文档

**症状**：
```
Failed to create Feishu document: Permission denied
```

**原因**：
1. 目录不是叶子节点
2. 权限不足
3. 知识库设置限制

**解决方案**：

```python
# 检查目录是否为叶子节点
dirs = dir_mgr.get_leaf_directories()
print(f"Leaf directories: {[d.name for d in dirs]}")

# 确保有docx权限
# 飞书开放平台 -> 应用管理 -> 权限管理 -> docx:document
```

### 问题12：Webhook未触发

**症状**：向机器人发送URL后无响应

**检查清单**：
- [ ] Webhook URL配置正确
- [ ] 事件订阅已启用
- [ ] `im.message.receive_v1`已订阅
- [ ] 机器人已拉入群聊或单聊

**调试步骤**：

```bash
# 1. 查看Cloudflare Workers日志
wrangler tail

# 2. 测试Webhook
curl -X POST https://your-webhook.workers.dev \
  -H "Content-Type: application/json" \
  -d '{"header":{"event_type":"im.message.receive_v1"},"event":{"message":{"content":"{\"text\":\"https://example.com\"}"}}}'

# 3. 检查GitHub Actions是否触发
gh run list --limit 5
```

## 部署问题

### 问题13：GitHub Actions失败

**症状**：Workflow运行失败

**查看日志**：
```bash
gh run view <run_id> --log
```

**常见错误**：

#### 错误A：Chrome未安装
```
google-chrome: command not found
```

**解决**：检查workflow中的Chrome安装步骤

#### 错误B：Python依赖安装失败
```
ERROR: Could not find a version that satisfies the requirement nodriver
```

**解决**：
```yaml
# 使用pip缓存加速
- uses: actions/setup-python@v5
  with:
    python-version: '3.11'
    cache: 'pip'
```

#### 错误C：Secrets未配置
```
Missing required configuration: JINA_API_KEY
```

**解决**：
```bash
# 在GitHub仓库中配置Secrets
# Settings -> Secrets and variables -> Actions -> New repository secret
```

### 问题14：Cloudflare Workers部署失败

**症状**：
```
wrangler deploy failed: Unauthorized
```

**解决方案**：

```bash
# 1. 重新登录
wrangler logout
wrangler login

# 2. 检查wrangler.toml配置
cat wrangler.toml

# 3. 确认Secrets已设置
wrangler secret list
```

## 性能问题

### 问题15：处理时间过长

**症状**：单篇文章处理超过2分钟

**性能分析**：

```python
import time

# 在main.py中添加计时
start = time.time()
article = await self.scraper.scrape(url)
print(f"Scraping: {time.time() - start:.2f}s")

start = time.time()
downloaded = self.image_downloader.download_images(article.images)
print(f"Download: {time.time() - start:.2f}s")

# ... 其他步骤
```

**优化方案**：

```python
# 1. 并行下载图片
import concurrent.futures

def download_parallel(image_urls):
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(download_image, url) for url in image_urls]
        return [f.result() for f in futures]

# 2. 减少不必要的等待
await asyncio.sleep(2)  # 从5秒减少到2秒

# 3. 使用更快的模型
JINA_MODEL=jina-embeddings-v2-small-zh  # 更小更快
```

### 问题16：内存使用过高

**症状**：GitHub Actions OOM killed

**解决方案**：

```python
# 1. 分批处理大图片
def process_images_in_batches(images, batch_size=5):
    for i in range(0, len(images), batch_size):
        batch = images[i:i+batch_size]
        yield batch

# 2. 及时清理
downloaded_images = download_images(urls)
upload_images(downloaded_images)
cleanup_downloads()  # 立即清理

# 3. 限制图片大小
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
```

## 诊断工具

### 完整系统健康检查

创建 `scripts/healthcheck.py`：

```python
#!/usr/bin/env python3
"""系统健康检查脚本"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.config import config
from feishu.auth_manager import AuthManager
from matchers.jina_client import JinaClient
from github import Github

def check_config():
    print("检查配置...")
    missing = config.validate()
    if missing:
        print(f"❌ 缺少配置: {', '.join(missing)}")
        return False
    print("✅ 配置完整")
    return True

def check_feishu():
    print("检查飞书连接...")
    try:
        auth = AuthManager()
        token = auth.get_access_token()
        print(f"✅ 飞书连接成功")
        return True
    except Exception as e:
        print(f"❌ 飞书连接失败: {e}")
        return False

def check_jina():
    print("检查Jina AI...")
    try:
        client = JinaClient()
        embedding = client.get_embedding("测试")
        print(f"✅ Jina AI工作正常 (维度: {len(embedding)})")
        return True
    except Exception as e:
        print(f"❌ Jina AI失败: {e}")
        return False

def check_github():
    print("检查GitHub连接...")
    try:
        g = Github(config.GH_TOKEN)
        repo = g.get_repo(config.IMAGE_REPO)
        print(f"✅ GitHub连接成功: {repo.name}")
        return True
    except Exception as e:
        print(f"❌ GitHub连接失败: {e}")
        return False

if __name__ == "__main__":
    results = [
        check_config(),
        check_feishu(),
        check_jina(),
        check_github()
    ]

    if all(results):
        print("\n🎉 所有检查通过！")
        sys.exit(0)
    else:
        print("\n❌ 部分检查失败，请查看上方错误信息")
        sys.exit(1)
```

运行健康检查：
```bash
python scripts/healthcheck.py
```

## 获取帮助

如果以上方案都无法解决问题：

1. **收集信息**：
   - 完整错误日志
   - 系统环境（OS, Python版本）
   - 配置文件（移除敏感信息）

2. **提交Issue**：
   - https://github.com/yourusername/collector/issues
   - 使用Issue模板
   - 提供详细复现步骤

3. **社区支持**：
   - GitHub Discussions
   - 查看已有Issue

## 预防措施

### 最佳实践

1. **定期更新依赖**：
```bash
pip list --outdated
pip install --upgrade nodriver lark-oapi
```

2. **监控API额度**：
- 每周检查Jina AI使用量
- 设置GitHub Actions通知

3. **备份重要数据**：
- 定期导出知识库
- 保存重要文章链接

4. **测试后部署**：
- 本地完整测试
- 小规模生产测试
- 逐步扩大使用

5. **日志记录**：
```python
# 保持详细日志
LOG_LEVEL=DEBUG  # 开发环境
LOG_LEVEL=INFO   # 生产环境
```
