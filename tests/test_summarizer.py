from src.summarizer import (
    fallback_summary,
    normalize_result,
    parse_llm_json,
    truncate_sentences,
)


def test_parse_llm_json_fenced():
    content = '```json\n{"title": "测试", "importance": 80}\n```'
    assert parse_llm_json(content) == {"title": "测试", "importance": 80}


def test_parse_llm_json_ignores_surrounding_text():
    content = '好的，结果如下：{"title":"x","summary":"y"} 以上。'
    assert parse_llm_json(content) == {"title": "x", "summary": "y"}


def test_parse_llm_json_rejects_invalid():
    assert parse_llm_json("不是 JSON") is None
    assert parse_llm_json("") is None


def test_normalize_result_clamps_values():
    category = {"id": "hot", "name": "社会热点"}
    article = {"title": "原标题", "summary": "原摘要"}
    result = normalize_result(
        {
            "title": "很" * 50,
            "summary": "简短",
            "detail": "详细",
            "tags": ["标签一", "标签二"],
            "importance": 999,
        },
        article,
        category,
    )
    assert len(result["title"]) == 40
    assert result["importance"] == 100
    assert result["tags"] == ["标签一", "标签二"]


def test_fallback_summary_uses_text():
    category = {"id": "hot", "name": "社会热点"}
    article = {
        "title": "示例新闻",
        "source_name": "测试源",
        "text": "这是一段正文，说明事件经过。后面还有更多内容可以解释影响。",
        "score": 82,
    }
    result = fallback_summary(article, category)
    assert result["title"] == "示例新闻"
    assert "正文" in result["summary"]
    assert result["importance"] == 82
    assert category["name"] in result["tags"]


def test_truncate_sentences_ends_at_boundary():
    text = "一二三四五六七八。九十九十。更多内容。"
    result = truncate_sentences(text, 10)
    assert result.endswith("。")
    assert len(result) <= 12
