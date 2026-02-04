"""测试AI匹配器"""
import pytest
from src.matchers.jina_client import JinaClient
from src.matchers.similarity_matcher import SimilarityMatcher
from src.matchers.types import Directory


def test_cosine_similarity():
    """测试余弦相似度计算"""
    matcher = SimilarityMatcher()

    # 相同向量，相似度应为1
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [1.0, 0.0, 0.0]
    similarity = matcher._cosine_similarity(vec1, vec2)
    assert abs(similarity - 1.0) < 0.001

    # 正交向量，相似度应为0
    vec3 = [1.0, 0.0, 0.0]
    vec4 = [0.0, 1.0, 0.0]
    similarity = matcher._cosine_similarity(vec3, vec4)
    assert abs(similarity - 0.0) < 0.001


def test_determine_confidence():
    """测试置信度判断"""
    matcher = SimilarityMatcher()

    assert matcher._determine_confidence(0.9) == 'high'
    assert matcher._determine_confidence(0.75) == 'medium'
    assert matcher._determine_confidence(0.5) == 'low'


@pytest.mark.skipif(
    not pytest.config.getoption("--run-api-tests", default=False),
    reason="需要--run-api-tests标志来运行API测试"
)
def test_jina_api_integration():
    """测试Jina API集成（需要真实API key）"""
    client = JinaClient()

    text = "人工智能技术发展"
    embedding = client.get_embedding(text)

    assert embedding is not None
    assert len(embedding) > 0
    assert isinstance(embedding[0], float)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
