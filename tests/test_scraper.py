"""测试抓取器"""
import pytest
import asyncio
from src.scrapers.nodriver_scraper import NodriverScraper


@pytest.mark.asyncio
async def test_scrape_generic_website():
    """测试普通网站抓取"""
    scraper = NodriverScraper()
    url = "https://example.com"

    article = await scraper.scrape(url)

    assert article is not None
    assert article.title
    assert article.content
    assert article.url == url


@pytest.mark.asyncio
async def test_scrape_weixin_article():
    """测试微信公众号文章抓取"""
    scraper = NodriverScraper()
    # 需要替换为实际的微信文章URL
    url = "https://mp.weixin.qq.com/s/xxxxx"

    # 跳过实际测试（需要真实URL）
    pytest.skip("需要真实的微信文章URL")

    article = await scraper.scrape(url)

    assert article is not None
    assert article.title
    assert len(article.images) > 0


def test_is_weixin_article():
    """测试微信文章识别"""
    scraper = NodriverScraper()

    assert scraper.is_weixin_article("https://mp.weixin.qq.com/s/xxxxx")
    assert scraper.is_weixin_article("https://weixin.qq.com/xxxxx")
    assert not scraper.is_weixin_article("https://example.com")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
