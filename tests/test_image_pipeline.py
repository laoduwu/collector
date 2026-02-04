"""测试图片处理管道"""
import pytest
from src.image_pipeline.jsdelivr_cdn import JsDelivrCDN


def test_generate_cdn_url():
    """测试CDN URL生成"""
    cdn = JsDelivrCDN()

    # 测试GitHub路径转换
    github_path = "images/2026/02/img_001.jpg"
    cdn_url = cdn.generate_cdn_url(github_path)

    assert cdn_url.startswith("https://cdn.jsdelivr.net/gh/")
    assert github_path in cdn_url


def test_replace_image_urls():
    """测试图片URL替换"""
    cdn = JsDelivrCDN()

    content = """
    这是一篇文章
    ![图片1](https://example.com/img1.jpg)
    一些文字
    ![图片2](https://example.com/img2.jpg)
    """

    url_mapping = [
        ("https://example.com/img1.jpg", "https://cdn.jsdelivr.net/gh/user/repo/img1.jpg"),
        ("https://example.com/img2.jpg", "https://cdn.jsdelivr.net/gh/user/repo/img2.jpg"),
    ]

    result = cdn.replace_image_urls(content, url_mapping)

    assert "https://example.com/img1.jpg" not in result
    assert "https://example.com/img2.jpg" not in result
    assert "https://cdn.jsdelivr.net/gh/user/repo/img1.jpg" in result
    assert "https://cdn.jsdelivr.net/gh/user/repo/img2.jpg" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
