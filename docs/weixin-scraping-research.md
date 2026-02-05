# 微信公众号文章爬取研究报告

**日期**: 2026-02-05
**状态**: ✅ 已解决

## 研究结论

经过多种方案测试，**Playwright + 反检测配置** 是当前最可靠的微信公众号文章爬取方案。

### 最终测试结果

| 方案 | 成功率 | 说明 |
|------|--------|------|
| **Playwright (推荐)** | **100%** | 配合反检测脚本，无头模式可用 |
| Nodriver | 需Python 3.10+ | 当前环境不支持 |
| Jina Reader API | 0% | 被微信CAPTCHA拦截 |
| undetected-chromedriver | 版本兼容问题 | ChromeDriver版本不匹配 |

### 成功配置

```python
# Playwright 成功配置
browser = await p.chromium.launch(
    headless=True,  # 无头模式也可以工作！
    args=[
        '--no-sandbox',
        '--disable-blink-features=AutomationControlled',
    ]
)

# 关键：注入反检测脚本
await context.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    window.chrome = { runtime: {} };
""")
```

### 测试验证

```
URL: https://mp.weixin.qq.com/s/EZMRd5EHz89kWZS4f6BVvA
✓ 标题: 2026年中国人工智能市场总规模预计将超264.4亿美元
✓ 作者: IDC咨询
✓ 发布日期: 2023年3月30日 11:40
✓ 内容长度: 2888 字符
✓ 图片数量: 8 张
```

## 实现方案

### 核心文件

- `src/scrapers/playwright_scraper.py` - Playwright抓取器（主要方案）
- `src/scrapers/nodriver_scraper.py` - Nodriver抓取器（备用，需Python 3.10+）

### 依赖

```bash
# requirements.txt
playwright>=1.40.0

# 安装浏览器
python -m playwright install chromium
```

### 使用方式

```python
from scrapers.playwright_scraper import PlaywrightScraper

scraper = PlaywrightScraper(headless=True)
article = await scraper.scrape("https://mp.weixin.qq.com/s/xxx")

print(article.title)       # 文章标题
print(article.author)      # 公众号名称
print(article.content)     # 正文内容
print(article.images)      # 图片URL列表
```

## 关键发现

### 1. 无头模式可以工作

之前认为需要非无头模式，但测试表明 **Playwright 的无头模式配合正确的反检测脚本也能成功抓取**。

### 2. 反检测脚本是关键

必须注入以下脚本隐藏自动化特征：
- 移除 `navigator.webdriver` 属性
- 模拟 `navigator.plugins`
- 添加 `window.chrome` 对象

### 3. 页面滚动触发懒加载

微信文章图片使用懒加载，需要滚动页面才能获取所有图片：

```python
await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
await asyncio.sleep(2)
```

### 4. 图片在 data-src 属性

微信图片URL存储在 `data-src` 属性而非 `src`：

```python
src = await img.get_attribute("data-src") or await img.get_attribute("src")
```

## 错误排查

### 问题1: 文章显示"已被删除"

**原因**: 测试的URL对应的文章真的被删除了
**解决**: 使用有效的文章URL测试

### 问题2: Nodriver 报 TypeError

**原因**: Nodriver 使用了 Python 3.10+ 的类型语法 (`str | Path`)
**解决**: 使用 Playwright 替代，支持 Python 3.9+

### 问题3: ChromeDriver 版本不匹配

**原因**: undetected-chromedriver 下载的驱动版本与本地Chrome不匹配
**解决**: 使用 Playwright，它自动管理浏览器版本

## 参考资料

- [Playwright Python 文档](https://playwright.dev/python/)
- [nodriver GitHub](https://github.com/ultrafunkamsterdam/nodriver)
- [wechat-article-exporter](https://github.com/wechat-article/wechat-article-exporter)
