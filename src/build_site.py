#!/usr/bin/env python3
"""Entry point: fetch feeds, summarize, and render the static site."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.builder import build_all  # noqa: E402
from src.config import load_feeds, load_settings  # noqa: E402
from src.news import (  # noqa: E402
    assign_ids,
    dedupe_articles,
    download_image,
    fetch_all,
    fetch_article_details,
    image_extension,
    is_qr_image,
    rank_articles,
    select_top,
    verify_articles,
)
from src.summarizer import summarize_articles  # noqa: E402


def is_photo_image(path: Path) -> bool:
    try:
        if path.stat().st_size < 15000:
            return False
        with Image.open(path) as image:
            width, height = image.size
            if min(width, height) < 250 or max(width, height) < 450:
                return False
            if max(width, height) / max(1, min(width, height)) > 3.2:
                return False
        return True
    except Exception:
        return False


def localize_article_images(articles: list[dict], date_str: str, output_dir: Path) -> None:
    image_dir = output_dir / "assets" / "images" / date_str
    if image_dir.exists():
        shutil.rmtree(image_dir)
    image_dir.mkdir(parents=True, exist_ok=True)
    seen_hashes: set[str] = set()
    for article in articles:
        candidates = article.get("images") or ([article["image"]] if article.get("image") else [])
        chosen = None
        fallback = None
        downloaded: dict[str, str] = {}
        for url in candidates:
            if is_qr_image(url):
                continue
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
            filename = f"{article['id']}_{digest}{image_extension(url)}"
            if not download_image(url, image_dir, filename):
                continue
            file_hash = hashlib.md5((image_dir / filename).read_bytes()).hexdigest()
            downloaded[filename] = file_hash
            if file_hash in seen_hashes:
                continue
            if fallback is None:
                fallback = filename
            if is_photo_image(image_dir / filename):
                chosen = filename
                break
        chosen = chosen or fallback
        if chosen:
            seen_hashes.add(downloaded[chosen])
        article["image"] = f"assets/images/{date_str}/{chosen}" if chosen else None
        article["images"] = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成每日热点自动聚合简报站")
    parser.add_argument("--date", help="覆盖日期，格式 YYYY-MM-DD")
    parser.add_argument("--max-items", type=int, help="每类最多条数，覆盖配置")
    parser.add_argument("--no-llm", action="store_true", help="强制使用免 key 降级摘要")
    parser.add_argument("--skip-details", action="store_true", help="跳过正文/图片提取")
    parser.add_argument("--output", default=str(ROOT / "docs"), help="静态站点输出目录")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("build")

    settings = load_settings()
    feeds = load_feeds()
    tz = ZoneInfo(settings["timezone"])
    generated_at = datetime.now(tz)
    if args.date:
        generated_at = datetime.fromisoformat(args.date).replace(tzinfo=tz)
    if args.max_items:
        settings["items_per_category"] = args.max_items

    logger.info("开始抓取 %d 个信息源", len(feeds))
    raw_articles = fetch_all(feeds, settings)
    articles = dedupe_articles(raw_articles)
    articles = verify_articles(
        articles,
        min_sources=int(settings.get("min_verified_sources", 2)),
        foreign_domains=tuple(settings.get("foreign_domains", [])),
        category_priority=("policy", "world", "ai", "economy", "hot"),
    )
    articles = rank_articles(articles, generated_at.timestamp(), float(settings.get("max_age_hours", 24)))
    selected = select_top(articles, settings)
    assign_ids([article for group in selected.values() for article in group])

    unique_articles = {article["id"]: article for group in selected.values() for article in group}
    if not args.skip_details:
        logger.info("提取 %d 篇文章的正文与图片", len(unique_articles))
        for article in unique_articles.values():
            article.update(fetch_article_details(article, settings))
    else:
        for article in unique_articles.values():
            article.setdefault("resolved_link", article["link"])
            article.setdefault("text", "")
            article.setdefault("image", None)
            article.setdefault("images", [])

    date_str = generated_at.strftime("%Y-%m-%d")
    output_dir = Path(args.output)
    localize_article_images(list(unique_articles.values()), date_str, output_dir)

    use_llm = not args.no_llm and bool(os.environ.get("DEEPSEEK_API_KEY"))
    logger.info("生成摘要（%s）", "LLM" if use_llm else "降级模式")
    summaries = summarize_articles(selected, settings, force_fallback=args.no_llm)

    feed_names = sorted({feed.get("name", feed.get("id", "")) for feed in feeds})
    digest = build_all(
        settings,
        feeds,
        selected,
        summaries,
        generated_at,
        feed_names,
        output_dir,
    )
    logger.info("完成：%s", digest["date"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
