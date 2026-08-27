import time

from src.news import (
    dedupe_articles,
    decode_html_bytes,
    images_from_markdown,
    is_qr_image,
    normalize_title,
    normalize_url,
    rank_articles,
    select_for_category,
    select_top,
    source_domain,
    verify_articles,
)


def test_normalize_url_removes_tracking_params():
    url = "https://example.com/story?id=1&utm_source=x&fbclid=abc&gclid=def&spm=z"
    assert normalize_url(url) == "https://example.com/story?id=1"


def test_normalize_url_keeps_relevant_query():
    url = "https://example.com/story?q=news&utm_medium=email"
    assert normalize_url(url) == "https://example.com/story?q=news"


def test_normalize_title_strips_punctuation():
    assert normalize_title("中国：新政策！") == normalize_title("中国 新政策")
    assert normalize_title("A-B_C") == "abc"


def test_images_from_markdown_returns_absolute_urls():
    markdown = "![](//example.com/a.jpg)\n![新闻照片](https://example.com/b.png)\n没有图的段落"
    images = images_from_markdown(markdown)
    assert [item["url"] for item in images] == ["https://example.com/a.jpg", "https://example.com/b.png"]
    assert images[1]["alt"] == "新闻照片"


def test_is_qr_image_detects_qr_url_and_alt():
    assert is_qr_image("https://example.com/qrcode.png")
    assert is_qr_image("https://example.com/a.jpg", "扫码关注")
    assert not is_qr_image("https://example.com/photo.jpg", "现场照片")


def test_decode_html_bytes_prefers_utf8_over_wrong_declared():
    raw = "文汇网测试内容".encode("utf-8")
    assert decode_html_bytes(raw, declared="cp775", apparent="cp775") == "文汇网测试内容"


def test_dedupe_keeps_higher_weight_source():
    articles = [
        {"title": "同一新闻", "link": "https://example.com/a", "weight": 1.0},
        {"title": "同一新闻", "link": "https://example.com/b", "weight": 2.0},
    ]
    result = dedupe_articles(articles)
    assert len(result) == 1
    assert result[0]["weight"] == 2.0


def test_dedupe_by_url_prefers_first_high_weight():
    articles = [
        {"title": "标题A", "link": "https://example.com/x", "weight": 1.0},
        {"title": "标题B", "link": "https://example.com/x?utm_source=app", "weight": 2.0},
    ]
    result = dedupe_articles(articles)
    assert len(result) == 1
    assert result[0]["weight"] == 2.0


def test_rank_scores_favor_fresh_news():
    now = time.time()
    articles = [
        {"title": "新", "link": "https://example.com/new", "weight": 1.0, "published": time.gmtime(now)},
        {"title": "旧", "link": "https://example.com/old", "weight": 1.0, "published": time.gmtime(now - 48 * 3600)},
        {"title": "无日期", "link": "https://example.com/none", "weight": 1.0, "published": None},
    ]
    ranked = rank_articles(articles, now)
    scores = {article["title"]: article["score"] for article in ranked}
    assert scores["新"] > scores["旧"]
    assert scores["旧"] == 0.0
    assert scores["无日期"] == 0.0


def test_select_excludes_stale_and_missing_dates():
    now = time.time()
    settings = {
        "items_per_category": 2,
        "categories": [{"id": "hot", "name": "社会热点"}],
    }
    articles = rank_articles(
        [
            {"title": "新", "link": "https://example.com/new", "weight": 1.0, "published": time.gmtime(now - 3600), "categories": ["hot"]},
            {"title": "旧", "link": "https://example.com/old", "weight": 1.0, "published": time.gmtime(now - 96 * 3600), "categories": ["hot"]},
            {"title": "无日期", "link": "https://example.com/none", "weight": 1.0, "published": None, "categories": ["hot"]},
        ],
        now,
    )
    selected = select_top(articles, settings)
    assert [item["title"] for item in selected["hot"]] == ["新"]


def test_select_top_respects_limit_and_categories():
    settings = {
        "items_per_category": 2,
        "categories": [
            {"id": "hot", "name": "社会热点"},
            {"id": "economy", "name": "世界经济"},
        ],
    }
    articles = [
        {"title": f"热{i}", "link": f"https://example.com/hot{i}", "score": 10 - i, "categories": ["hot"]}
        for i in range(4)
    ]
    articles.append({"title": "经济", "link": "https://example.com/e", "score": 9, "categories": ["economy"]})
    selected = select_top(articles, settings)
    assert set(selected) == {"hot", "economy"}
    assert len(selected["hot"]) == 2
    assert selected["hot"][0]["score"] >= selected["hot"][1]["score"]


def test_select_for_category_filters_and_sorts():
    articles = [
        {"title": "a", "link": "https://example.com/a", "score": 1, "categories": ["hot"]},
        {"title": "b", "link": "https://example.com/b", "score": 5, "categories": ["world"]},
        {"title": "c", "link": "https://example.com/c", "score": 3, "categories": ["hot"]},
    ]
    result = select_for_category(articles, "hot", 10)
    assert [item["title"] for item in result] == ["c", "a"]


def test_source_domain_strips_www():
    assert source_domain("https://www.zaobao.com.sg/news/world/x") == "zaobao.com.sg"
    assert source_domain("https://china.kyodonews.net/rss/news.xml") == "china.kyodonews.net"


def test_verify_articles_requires_multiple_domains():
    articles = [
        {"title": "日本遭遇强降雨", "link": "https://china.kyodonews.net/a", "source_name": "共同社", "weight": 1.2, "categories": ["world"]},
        {"title": "日本 遭遇强降雨", "link": "https://www.zaobao.com.sg/b", "source_name": "联合早报", "weight": 1.2, "categories": ["world"]},
        {"title": "单独一条新闻", "link": "https://example.com/c", "source_name": "单源", "weight": 1.0, "categories": ["hot"]},
    ]
    verified = verify_articles(articles, min_sources=2, foreign_domains=("china.kyodonews.net", "zaobao.com.sg"))
    assert len(verified) == 1
    assert verified[0]["verification_count"] == 2
    assert verified[0]["source_domain"] == "china.kyodonews.net"
    assert verified[0]["categories"] == ["world"]


def test_select_for_category_caps_per_source():
    settings = {
        "items_per_category": 4,
        "categories": [{"id": "hot", "name": "社会热点"}],
    }
    articles = [
        {"title": f"热{i}", "link": f"https://example.com/{i}", "score": 10 - i, "verification_count": 2, "source_domain": "example.com", "categories": ["hot"]}
        for i in range(4)
    ]
    selected = select_top(articles, settings)
    assert len(selected["hot"]) == 2


def test_select_foreign_only_prefers_foreign_member():
    settings = {
        "items_per_category": 4,
        "min_verified_sources": 2,
        "max_per_source": 2,
        "foreign_domains": ["china.kyodonews.net"],
        "categories": [
            {"id": "world", "name": "世界格局", "limit": 4, "foreign_only": True}
        ],
    }
    articles = [
        {"title": "日本遭遇强降雨", "link": "https://www.chinanews.com.cn/a", "source_name": "中新网", "weight": 1.2, "categories": ["policy"]},
        {"title": "日本 遭遇强降雨", "link": "https://china.kyodonews.net/b", "source_name": "共同社", "weight": 1.1, "categories": ["world"]},
    ]
    verified = verify_articles(articles, min_sources=2, foreign_domains=("china.kyodonews.net",))
    selected = select_top(verified, settings)["world"]
    assert len(selected) == 1
    assert selected[0]["source_domain"] == "china.kyodonews.net"
    assert selected[0]["verification_count"] == 2
