"""Assemble digest data and render the static site."""

from __future__ import annotations

import calendar
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .summarizer import fallback_summary

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates"
DATA_DIR = ROOT / "data" / "digests"


def display_date(date_str: str) -> str:
    year, month, day = date_str.split("-")
    return f"{int(year)}年{int(month)}月{int(day)}日"


def short_date(date_str: str) -> str:
    year, month, day = date_str.split("-")
    return f"{int(month)}月{int(day)}日"


def relative_label(published_epoch: float, now_epoch: float) -> str:
    delta = max(0, int(now_epoch - published_epoch))
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{delta // 60} 分钟前"
    if delta < 86400:
        return f"{delta // 3600} 小时前"
    return f"{delta // 86400} 天前"


def ensure_placeholders(settings: dict, output_dir: Path) -> None:
    image_dir = Path(output_dir) / "assets" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for category in settings["categories"]:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500">'
            f'<rect width="800" height="500" fill="{category["color"]}"/>'
            f'<text x="400" y="250" font-size="42" fill="white" text-anchor="middle" '
            f'font-family="Microsoft YaHei,sans-serif">{category["name"]}</text>'
            "</svg>"
        )
        (image_dir / f"placeholder-{category['id']}.svg").write_text(svg, encoding="utf-8")


def day_nav_items(today: date, data_dir: Path, prefix: str = "") -> list[dict]:
    labels = {0: "今天", 1: "昨天", 2: "前天"}
    items = []
    for offset in range(6):
        day = today - timedelta(days=offset)
        date_str = day.isoformat()
        available = offset == 0 or (data_dir / f"{date_str}.json").exists()
        if offset == 0:
            href = prefix + "index.html"
        elif prefix:
            href = f"{date_str}.html"
        else:
            href = f"archive/{date_str}.html"
        items.append(
            {
                "date": date_str,
                "label": labels.get(offset, f"{offset}天前"),
                "href": href,
                "available": available,
            }
        )
    return items


def make_digest(
    date_str: str,
    generated_at: datetime,
    settings: dict,
    selected: dict[str, list[dict]],
    summaries: dict[str, dict],
    feed_names: list[str],
) -> dict:
    now_epoch = generated_at.timestamp()
    categories_out = []
    for category in settings["categories"]:
        events = []
        for article in selected.get(category["id"], []):
            summary = summaries.get(article["id"]) or fallback_summary(article, category)
            published_at = None
            published_label = None
            if article.get("published"):
                published_epoch = calendar.timegm(article["published"])
                published_at = datetime.fromtimestamp(published_epoch, tz=timezone.utc).isoformat()
                published_label = relative_label(published_epoch, now_epoch)
            events.append(
                {
                    "id": article.get("id"),
                    "title": summary["title"],
                    "summary": summary["summary"],
                    "detail": summary["detail"],
                    "tags": summary["tags"],
                    "importance": summary["importance"],
                    "source_name": article.get("source_name") or article.get("feed_name", ""),
                    "source_url": article.get("resolved_link") or article.get("link", ""),
                    "image_url": article.get("image"),
                    "published_at": published_at,
                    "published_label": published_label,
                    "verification_count": article.get("verification_count", 1),
                    "verified_by": article.get("verified_by", []),
                    "source_domain": article.get("source_domain", ""),
                    "category_id": category["id"],
                }
            )
        categories_out.append(
            {
                "id": category["id"],
                "name": category["name"],
                "color": category["color"],
                "description": category.get("description", ""),
                "events": events,
            }
        )
    all_events = [event for cat in categories_out for event in cat["events"]]
    hero = max(all_events, key=lambda event: event["importance"]) if all_events else None
    return {
        "date": date_str,
        "generated_at": generated_at.isoformat(),
        "site_title": settings["site_title"],
        "site_tagline": settings["site_tagline"],
        "feed_names": sorted(feed_names),
        "hero": hero,
        "categories": categories_out,
    }


def write_digest(digest: dict, data_dir: Path | None = None) -> Path:
    target = data_dir or DATA_DIR
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{digest['date']}.json"
    path.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_digests(data_dir: Path | None = None) -> list[dict]:
    target = data_dir or DATA_DIR
    digests = []
    for path in sorted(target.glob("*.json")):
        try:
            digests.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(digests, key=lambda item: item.get("date", ""), reverse=True)


def _archive_items(digests: list[dict]) -> list[dict]:
    items = []
    for item in digests:
        generated = datetime.fromisoformat(item["generated_at"])
        count = sum(len(category.get("events", [])) for category in item.get("categories", []))
        items.append(
            {
                "date": item["date"],
                "display_date": display_date(item["date"]),
                "generated_label": generated.strftime("%m月%d日 %H:%M"),
                "event_count": count,
            }
        )
    return items


def render_site(
    digest: dict,
    settings: dict,
    feeds: list[dict],
    output_dir: Path,
    data_dir: Path | None = None,
) -> None:
    target_data = data_dir or DATA_DIR
    output_dir = Path(output_dir)
    archive_dir = output_dir / "archive"
    assets_dir = output_dir / "assets"
    archive_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html", "htm", "xml", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    shutil.copyfile(TEMPLATE_DIR / "style.css", assets_dir / "style.css")
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    ensure_placeholders(settings, output_dir)

    generated_at = datetime.fromisoformat(digest["generated_at"])
    hero_context = {}
    if digest.get("hero"):
        hero_category = next(
            (category for category in settings["categories"] if category["id"] == digest["hero"]["category_id"]),
            settings["categories"][0],
        )
        hero_image = digest["hero"].get("image_url") or f"assets/images/placeholder-{hero_category['id']}.svg"
        hero_image = (
            hero_image.replace("'", "%27").replace("(", "%28").replace(")", "%29")
            if hero_image
            else ""
        )
        hero_context = {
            "hero_category_name": hero_category["name"],
            "hero_color": hero_category["color"],
            "hero_background_url": hero_image,
        }

    base_context = {
        "digest": digest,
        "settings": settings,
        "feeds": feeds,
        "display_date": display_date(digest["date"]),
        "short_date": short_date(digest["date"]),
        "generated_time": generated_at.strftime("%H:%M"),
        "img_prefix": "",
        "day_nav": day_nav_items(date.fromisoformat(digest["date"]), target_data, ""),
        **hero_context,
    }
    index_html = env.get_template("index.html.j2").render(**base_context)
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")

    digests = load_digests(target_data)
    archive_day_nav = day_nav_items(date.fromisoformat(digest["date"]), target_data, "../")
    archive_index = env.get_template("archive_index.html.j2").render(
        digests=_archive_items(digests),
        settings=settings,
        feeds=feeds,
        img_prefix="../",
        day_nav=archive_day_nav,
    )
    (archive_dir / "index.html").write_text(archive_index, encoding="utf-8")

    archive_template = env.get_template("archive_day.html.j2")
    for item in digests:
        pager = _archive_pager(item["date"], archive_day_nav)
        context = {
            "digest": item,
            "settings": settings,
            "feeds": feeds,
            "display_date": display_date(item["date"]),
            "short_date": short_date(item["date"]),
            "generated_time": datetime.fromisoformat(item["generated_at"]).strftime("%H:%M"),
            "img_prefix": "../",
            "day_nav": archive_day_nav,
            **pager,
        }
        page = archive_template.render(**context)
        (archive_dir / f"{item['date']}.html").write_text(page, encoding="utf-8")


def _archive_pager(date_str: str, nav: list[dict]) -> dict:
    available = [item for item in nav if item["available"]]
    indexes = [index for index, item in enumerate(available) if item["date"] == date_str]
    if not indexes:
        return {}
    index = indexes[0]
    previous = available[index + 1] if index + 1 < len(available) else None
    following = available[index - 1] if index > 0 else None
    return {
        "archive_prev": previous,
        "archive_next": following,
    }


def prune_old(settings: dict, data_dir: Path | None = None, output_dir: Path | None = None) -> None:
    target_data = data_dir or DATA_DIR
    cutoff = (date.today() - timedelta(days=int(settings.get("retention_days", 90)))).isoformat()
    for path in target_data.glob("*.json"):
        if path.stem < cutoff:
            path.unlink()
    if output_dir:
        archive_dir = Path(output_dir) / "archive"
        for path in archive_dir.glob("*.html"):
            if path.name != "index.html" and path.stem < cutoff:
                path.unlink()
        images_root = Path(output_dir) / "assets" / "images"
        for path in images_root.glob("20*"):
            if path.name < cutoff:
                shutil.rmtree(path, ignore_errors=True)


def build_all(
    settings: dict,
    feeds: list[dict],
    selected: dict[str, list[dict]],
    summaries: dict[str, dict],
    generated_at: datetime,
    feed_names: list[str],
    output_dir: Path,
    data_dir: Path | None = None,
) -> dict:
    date_str = generated_at.strftime("%Y-%m-%d")
    digest = make_digest(date_str, generated_at, settings, selected, summaries, feed_names)
    write_digest(digest, data_dir)
    render_site(digest, settings, feeds, output_dir, data_dir)
    prune_old(settings, data_dir, output_dir)
    return digest
