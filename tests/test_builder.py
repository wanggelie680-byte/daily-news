import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.builder import build_all, make_digest, prune_old


def sample_settings():
    return {
        "site_title": "每日热点简报",
        "site_tagline": "自动聚合",
        "timezone": "Asia/Shanghai",
        "items_per_category": 1,
        "retention_days": 90,
        "categories": [
            {"id": "hot", "name": "社会热点", "color": "#d92c20", "description": "民生"},
            {"id": "economy", "name": "世界经济", "color": "#0e8a5f", "description": "市场"},
        ],
    }


def sample_article():
    return {
        "id": "abc123",
        "title": "原标题",
        "link": "https://example.com/story",
        "resolved_link": "https://example.com/story",
        "source_name": "测试源",
        "feed_name": "测试源",
        "published": time.gmtime(),
        "score": 80,
        "summary": "RSS 摘要",
        "text": "正文内容较长，用于生成摘要。",
        "image": "https://example.com/image.jpg",
        "categories": ["hot", "economy"],
    }


def sample_summaries():
    return {
        "abc123": {
            "title": "新标题",
            "summary": "一句话简短解释。",
            "detail": "详细解释第一段。\n\n详细解释第二段。",
            "tags": ["标签"],
            "importance": 90,
        }
    }


def generated_at():
    return datetime(2026, 8, 27, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_make_digest_contains_hero_and_categories():
    settings = sample_settings()
    article = sample_article()
    digest = make_digest(
        "2026-08-27",
        generated_at(),
        settings,
        {"hot": [article], "economy": []},
        sample_summaries(),
        ["测试源"],
    )
    assert digest["hero"]["id"] == "abc123"
    assert len(digest["categories"]) == 2
    assert digest["categories"][0]["events"][0]["title"] == "新标题"
    assert digest["categories"][0]["events"][0]["source_url"] == "https://example.com/story"


def test_build_all_writes_site(tmp_path):
    settings = sample_settings()
    article = sample_article()
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "docs"
    digest = build_all(
        settings,
        [{"id": "f1", "name": "测试源"}],
        {"hot": [article], "economy": []},
        sample_summaries(),
        generated_at(),
        ["测试源"],
        output_dir,
        data_dir,
    )
    assert digest["date"] == "2026-08-27"
    assert (data_dir / "2026-08-27.json").exists()
    assert (output_dir / "index.html").exists()
    assert (output_dir / "archive" / "index.html").exists()
    assert (output_dir / "archive" / "2026-08-27.html").exists()
    assert (output_dir / "assets" / "style.css").exists()
    assert (output_dir / ".nojekyll").exists()
    assert (output_dir / "assets" / "images" / "placeholder-hot.svg").exists()

    html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "新标题" in html
    assert "展开详细解释" in html
    assert "阅读原文" in html
    assert "https://example.com/story" in html
    assert "day-menu" in html


def test_prune_old_removes_expired_digests(tmp_path):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "docs"
    data_dir.mkdir(parents=True)
    archive_dir = output_dir / "archive"
    archive_dir.mkdir(parents=True)

    (data_dir / "2020-01-01.json").write_text("{}", encoding="utf-8")
    (data_dir / "2026-08-27.json").write_text("{}", encoding="utf-8")
    (archive_dir / "2020-01-01.html").write_text("x", encoding="utf-8")
    (archive_dir / "2026-08-27.html").write_text("x", encoding="utf-8")
    (archive_dir / "index.html").write_text("x", encoding="utf-8")

    prune_old(sample_settings(), data_dir, output_dir)

    assert not (data_dir / "2020-01-01.json").exists()
    assert (data_dir / "2026-08-27.json").exists()
    assert not (archive_dir / "2020-01-01.html").exists()
    assert (archive_dir / "2026-08-27.html").exists()
    assert (archive_dir / "index.html").exists()
