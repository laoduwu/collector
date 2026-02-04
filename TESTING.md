# 测试指南

系统测试的详细说明。

## 测试环境设置

```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_scraper.py -v

# 带覆盖率
pytest tests/ --cov=src --cov-report=html
```

## 单元测试

### 1. 抓取器测试

```bash
pytest tests/test_scraper.py -v
```

测试内容：
- ✅ 普通网页抓取
- ✅ 微信文章识别
- ✅ 图片URL提取

### 2. 匹配器测试

```bash
pytest tests/test_matcher.py -v
```

测试内容：
- ✅ 余弦相似度计算
- ✅ 置信度判断
- ⚠️  Jina API集成（需要真实API key）

### 3. 图片管道测试

```bash
pytest tests/test_image_pipeline.py -v
```

测试内容：
- ✅ CDN URL生成
- ✅ 图片URL替换

## 集成测试

### 1. 本地完整流程测试

```bash
# 测试普通网页
python src/main.py "https://example.com"

# 测试微信文章（需要真实URL）
python src/main.py "https://mp.weixin.qq.com/s/xxxxx"
```

### 2. GitHub Actions手动触发

1. 进入仓库Actions标签
2. 选择"Scrape Article"workflow
3. 点击"Run workflow"
4. 输入测试URL
5. 等待执行完成

### 3. Webhook测试

使用curl模拟飞书消息：

```bash
curl -X POST https://your-webhook-url.workers.dev \
  -H "Content-Type: application/json" \
  -d '{
    "header": {
      "event_type": "im.message.receive_v1"
    },
    "event": {
      "message": {
        "content": "{\"text\":\"https://example.com/article\"}"
      }
    }
  }'
```

## 端到端测试

### 测试用例

准备20-30篇测试文章，涵盖不同类型：

#### 技术类文章
1. React教程
2. Python爬虫
3. Docker入门
4. 数据库优化
5. 前端性能

#### 产品类文章
1. 产品设计原则
2. 需求分析方法
3. 用户研究案例
4. MVP开发
5. 产品迭代

#### 业务类文章
1. 市场分析报告
2. 运营策略
3. 数据驱动决策
4. 增长黑客
5. 商业模式

### 验证清单

对每篇文章，检查：

- [ ] 文章成功抓取
- [ ] 标题正确
- [ ] 内容完整
- [ ] 图片全部显示
- [ ] 目录匹配准确
- [ ] 文档创建成功
- [ ] 元信息完整（作者、日期、原文链接）

### 准确率计算

```python
# 匹配准确率
accuracy = correct_matches / total_articles * 100

# 目标：≥ 80%
```

## 性能测试

### 1. 单篇处理时间

使用time命令测试：

```bash
time python src/main.py "https://example.com/article"
```

目标：
- 普通文章：< 30秒
- 微信文章：< 60秒

### 2. 并发处理

模拟多篇文章同时处理（GitHub Actions限制20个并发）：

```bash
# 触发多个workflow
for i in {1..5}; do
  gh workflow run scrape-article.yml -f article_url="https://example.com/article$i"
done
```

### 3. API额度监控

记录API调用次数：
- Jina AI：每次约200 tokens
- 500篇/月 = 100K tokens（远低于1M限制）

## 错误场景测试

### 1. 无效URL

```bash
python src/main.py "not-a-url"
# 预期：错误提示并退出
```

### 2. 无法访问的网站

```bash
python src/main.py "https://this-site-does-not-exist-12345.com"
# 预期：重试3次后失败
```

### 3. 微信文章抓取失败

```bash
python src/main.py "https://mp.weixin.qq.com/s/invalid"
# 预期：重试后失败，记录日志
```

### 4. Jina API额度用尽

模拟API 429错误：
```python
# 在jina_client.py中临时修改
response.status_code = 429
```

预期：文章自动进入"待整理"文件夹

### 5. GitHub上传失败

断开网络或使用无效token

预期：重试3次后失败，记录错误

## 回归测试

在每次代码更新后运行：

```bash
# 快速测试
pytest tests/ -v -m "not slow"

# 完整测试
pytest tests/ -v

# 端到端测试
python src/main.py "https://example.com/test-article"
```

## 测试报告模板

```markdown
## 测试报告

**日期**：2026-02-04
**测试人**：XXX
**版本**：v0.1.0

### 测试结果

| 测试类型 | 通过 | 失败 | 跳过 |
|---------|------|------|------|
| 单元测试 | 15 | 0 | 2 |
| 集成测试 | 5 | 0 | 0 |
| 端到端测试 | 25 | 2 | 0 |

### 匹配准确率

- 总文章数：30
- 正确匹配：25
- 进入待整理：5
- **准确率：83.3%** ✅

### 性能指标

- 平均处理时间：42秒
- 最快：18秒
- 最慢：68秒

### 发现的问题

1. 微信文章偶尔超时（2/10次）
2. 某些网站反爬虫较强

### 建议

1. 增加微信文章等待时间
2. 添加更多重试逻辑
```

## 持续集成

可以在GitHub Actions中添加测试步骤：

```yaml
# .github/workflows/test.yml
name: Run Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v
```
