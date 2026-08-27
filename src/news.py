"""Feed fetching, normalization, ranking and article enrichment."""

from __future__ import annotations

import calendar
import hashlib
import logging
import re
import time
import urllib.parse
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path

import feedparser
import requests
import trafilatura

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "spm",
    "ref",
}

logger = logging.getLogger(__name__)

MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

QR_URL_RE = re.compile(
    r"(qrcode|qr_code|erweima|2dcode|weixin|wechat|gongzhonghao|official_account|"
    r"qr/|二维码|扫码|公众号)",
    re.IGNORECASE,
)
QR_ALT_RE = re.compile(r"(二维码|扫码|扫码关注|公众号二维码|关注我们)", re.IGNORECASE)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def decode_html_bytes(content: bytes, declared: str | None = None, apparent: str | None = None) -> str:
    candidates = ["utf-8", "gb18030", "big5"]
    for encoding in (declared, apparent):
        if encoding and encoding.lower() not in {item.lower() for item in candidates}:
            candidates.append(encoding)
    for encoding in candidates:
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return clean_text(unescape(value))


def build_feed_url(feed: dict) -> str:
    if feed.get("type") == "google_news":
        params = {
            "q": feed["query"],
            "hl": feed.get("hl", "zh-CN"),
            "gl": feed.get("gl", "CN"),
            "ceid": feed.get("ceid", "CN:zh-Hans"),
        }
        return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    return feed["url"]


def fetch_feed(feed: dict, settings: dict) -> list[dict]:
    url = build_feed_url(feed)
    timeout = float(settings.get("request_timeout_seconds", 15))
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("feed fetch failed %s (%s): %s", feed.get("id"), url, exc)
        return []

    if feed.get("type") == "html_list":
        html = decode_html_bytes(response.content, response.encoding, response.apparent_encoding)
        return fetch_html_list(feed, html)

    parsed = feedparser.parse(response.content)
    items = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        source = entry.get("source")
        source_name = None
        if isinstance(source, dict):
            source_name = source.get("title")
        items.append(
            {
                "feed_id": feed.get("id"),
                "feed_name": feed.get("name", feed.get("id", "未命名源")),
                "title": title,
                "link": link,
                "source_name": clean_text(source_name or feed.get("name", feed.get("id", ""))),
                "summary": strip_tags(entry.get("summary") or entry.get("description") or ""),
                "published": entry.get("published_parsed") or entry.get("updated_parsed"),
                "weight": float(feed.get("weight", 1.0)),
                "categories": list(feed.get("categories", [])),
                "primary_category": feed.get("primary_category"),
            }
        )
    logger.info("feed %s returned %d items", feed.get("id"), len(items))
    return items


def parse_date_only(value: str) -> time.struct_time | None:
    try:
        if len(value) == 8:
            year, month, day = int(value[:4]), int(value[4:6]), int(value[6:8])
        elif len(value) == 10:
            year, month, day = int(value[:4]), int(value[5:7]), int(value[8:10])
        else:
            return None
        return time.struct_time((year, month, day, 12, 0, 0, 0, 0, -1))
    except ValueError:
        return None


def fetch_html_list(feed: dict, html: str) -> list[dict]:
    path_contains = feed.get("path_contains")
    pattern = feed.get("link_pattern")
    date_pattern = feed.get("date_pattern")
    anchors = []
    try:
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(html)
        for anchor in doc.xpath("//a"):
            href = anchor.get("href", "")
            title = anchor.text_content()
            if href and title:
                anchors.append((href, title))
    except Exception:
        anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]{8,100})</a>', html)
    items = []
    seen: set[str] = set()
    for href, title in anchors:
        title = clean_text(strip_tags(title))
        if not title:
            continue
        if path_contains and path_contains not in href:
            continue
        if pattern and not re.search(pattern, href):
            continue
        full_url = urllib.parse.urljoin(feed["url"], href)
        key = normalize_url(full_url)
        if key in seen:
            continue
        seen.add(key)
        published = None
        if date_pattern:
            match = re.search(date_pattern, href)
            if match:
                groups = [group for group in match.groups() if group]
                date_value = "".join(groups) if groups else None
                if date_value:
                    published = parse_date_only(date_value)
        items.append(
            {
                "feed_id": feed.get("id"),
                "feed_name": feed.get("name", feed.get("id", "未命名源")),
                "title": title,
                "link": full_url,
                "source_name": feed.get("name", feed.get("id", "")),
                "summary": "",
                "published": published,
                "weight": float(feed.get("weight", 1.0)),
                "categories": list(feed.get("categories", [])),
                "primary_category": feed.get("primary_category"),
            }
        )
        if len(items) >= int(feed.get("max_items", 30)):
            break
    logger.info("html feed %s returned %d items", feed.get("id"), len(items))
    return items


def fetch_all(feeds: list[dict], settings: dict) -> list[dict]:
    articles = []
    for feed in feeds:
        articles.extend(fetch_feed(feed, settings))
    return articles


def normalize_url(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def normalize_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", (title or "").lower())


def source_domain(url: str) -> str:
    try:
        netloc = urllib.parse.urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def titles_similar(first: str, second: str) -> bool:
    if not first or not second:
        return False
    if first == second:
        return True
    if min(len(first), len(second)) < 6:
        return False
    if SequenceMatcher(None, first, second).ratio() >= 0.72:
        return True
    first_grams = {first[index : index + 4] for index in range(len(first) - 3)}
    second_grams = {second[index : index + 4] for index in range(len(second) - 3)}
    return bool(first_grams & second_grams)


def verify_articles(
    articles: list[dict],
    min_sources: int = 2,
    foreign_domains: tuple[str, ...] = (),
    category_priority: tuple[str, ...] = (),
) -> list[dict]:
    groups: list[dict] = []
    for article in articles:
        key = normalize_title(article.get("title", ""))
        if not key:
            continue
        for group in groups:
            if titles_similar(group["_key"], key):
                group["_items"].append(article)
                break
        else:
            groups.append({"_key": key, "_items": [article]})

    verified: list[dict] = []
    for group in groups:
        items = group["_items"]
        domains = {source_domain(item.get("link", "")) for item in items}
        domains.discard("")
        if len(domains) < min_sources:
            continue
        categories = set()
        for item in items:
            categories.update(item.get("categories", []))
        foreign_members = [
            item
            for item in items
            if source_domain(item.get("link", "")) in foreign_domains
        ]
        if foreign_members:
            representative = max(
                foreign_members,
                key=lambda item: (
                    float(item.get("weight", 1.0)),
                    1 if (item.get("image") or item.get("text")) else 0,
                ),
            )
            if "world" in categories:
                categories = {"world"}
        else:
            representative = max(
                items,
                key=lambda item: (
                    float(item.get("weight", 1.0)),
                    1 if (item.get("image") or item.get("text")) else 0,
                ),
            )
        primary = representative.get("primary_category")
        if len(categories) > 1 and primary in categories:
            categories = {primary}
        elif len(categories) > 1:
            for category in category_priority:
                if category in categories:
                    categories = {category}
                    break
        merged = dict(representative)
        merged["categories"] = sorted(categories)
        merged["verification_count"] = len(domains)
        merged["verified_by"] = sorted({item.get("source_name", "") for item in items})
        merged["verified_domains"] = sorted(domains)
        merged["source_domain"] = source_domain(representative.get("link", ""))
        merged["members"] = items
        verified.append(merged)
    return verified


def dedupe_articles(articles: list[dict]) -> list[dict]:
    ordered = sorted(articles, key=lambda item: item.get("weight", 0.0), reverse=True)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict] = []
    for article in ordered:
        url_key = normalize_url(article.get("link", ""))
        title_key = normalize_title(article.get("title", ""))
        if url_key in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(article)
    return unique


def age_hours(article: dict, now_epoch: float) -> float | None:
    published = article.get("published")
    if not published:
        return None
    return max(0.0, (now_epoch - calendar.timegm(published)) / 3600.0)


def rank_articles(articles: list[dict], now_epoch: float, max_age_hours: float = 24.0) -> list[dict]:
    for article in articles:
        age = age_hours(article, now_epoch)
        article["age_hours"] = age
        if age is not None and age <= max_age_hours:
            article["fresh"] = True
            recency = 1.0 - (age / max_age_hours) * 0.7
            article["score"] = round(float(article.get("weight", 1.0)) * (0.5 + recency), 4)
        else:
            article["fresh"] = False
            article["score"] = 0.0
    return articles


def select_for_category(
    articles: list[dict],
    category_id: str,
    limit: int,
    max_per_source: int = 2,
    min_verified: int = 1,
    foreign_domains: tuple[str, ...] = (),
    foreign_only: bool = False,
) -> list[dict]:
    matching = [
        article
        for article in articles
        if article.get("fresh", True)
        and article.get("verification_count", min_verified) >= min_verified
        and category_id in article.get("categories", [])
    ]
    matching.sort(
        key=lambda article: (
            article.get("verification_count", min_verified),
            article.get("score", 0.0),
        ),
        reverse=True,
    )
    selected = []
    domain_counts: dict[str, int] = {}
    for article in matching:
        candidate = article
        if foreign_only:
            members = article.get("members") or [article]
            allowed = [
                member
                for member in members
                if source_domain(member.get("link", "")) in foreign_domains
            ]
            if not allowed:
                continue
            chosen_member = max(allowed, key=lambda member: float(member.get("weight", 1.0)))
            candidate = {**article, **chosen_member}
            candidate["verification_count"] = article.get("verification_count", min_verified)
            candidate["verified_by"] = article.get("verified_by", [])
            candidate["verified_domains"] = article.get("verified_domains", [])
            candidate["source_domain"] = source_domain(chosen_member.get("link", ""))
            candidate["members"] = members
        domain = candidate.get("source_domain") or source_domain(candidate.get("link", ""))
        if domain_counts.get(domain, 0) >= max_per_source:
            continue
        selected.append(candidate)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def select_top(articles: list[dict], settings: dict) -> dict[str, list[dict]]:
    default_limit = int(settings.get("items_per_category", 4))
    max_per_source = int(settings.get("max_per_source", 2))
    min_verified = int(settings.get("min_verified_sources", 1))
    foreign_domains = tuple(settings.get("foreign_domains", []))
    global_max_per_source = int(settings.get("global_max_per_source", 4))
    selected = {
        category["id"]: select_for_category(
            articles,
            category["id"],
            int(category.get("limit", default_limit)),
            max_per_source,
            min_verified,
            foreign_domains,
            bool(category.get("foreign_only", False)),
        )
        for category in settings["categories"]
    }
    global_counts: dict[str, int] = {}
    seen_ids: set[str] = set()
    for category in settings["categories"]:
        kept = []
        for article in selected[category["id"]]:
            article_id = article.get("id")
            if article_id and article_id in seen_ids:
                continue
            domain = article.get("source_domain") or source_domain(article.get("link", ""))
            if global_counts.get(domain, 0) >= global_max_per_source:
                continue
            kept.append(article)
            seen_ids.add(article_id)
            global_counts[domain] = global_counts.get(domain, 0) + 1
        selected[category["id"]] = kept
    return selected


def assign_ids(articles: list[dict]) -> None:
    for article in articles:
        key = normalize_url(article.get("link", "")) or article.get("title", "")
        article["id"] = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def resolve_link(url: str, timeout: float = 12.0) -> str:
    if "news.google.com/rss/articles" not in url:
        return url
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.head(url, allow_redirects=True, headers=headers, timeout=timeout)
        if response.url and response.url != url:
            return response.url
    except requests.RequestException:
        pass
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            headers=headers,
            timeout=timeout,
            stream=True,
        )
        response.close()
        return response.url or url
    except requests.RequestException:
        return url


def extract_og_image(html: str) -> str | None:
    pattern = re.compile(
        r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)[^>]*>',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html or ""):
        content = re.search(r'content=["\']([^"\']+)["\']', match.group(0), re.IGNORECASE)
        if not content:
            continue
        value = unescape(content.group(1)).strip()
        if value.startswith("//"):
            return "https:" + value
        if value.startswith(("http://", "https://")):
            return value
    return None


def images_from_markdown(markdown: str) -> list[dict]:
    images = []
    for match in MARKDOWN_IMAGE_RE.finditer(markdown or ""):
        alt = clean_text(unescape(match.group(1)))
        url = unescape(match.group(2)).strip()
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith(("http://", "https://")):
            images.append({"url": url, "alt": alt})
    return images


def is_qr_image(url: str, alt: str = "") -> bool:
    return bool(QR_URL_RE.search(url or "")) or bool(QR_ALT_RE.search(alt or ""))


def fetch_article_details(article: dict, settings: dict) -> dict:
    url = resolve_link(article.get("link", ""))
    timeout = float(settings.get("article_timeout_seconds", 20))
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        html = decode_html_bytes(response.content, response.encoding, response.apparent_encoding)
        markdown = trafilatura.extract(
            html,
            output_format="markdown",
            include_images=True,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
        text = trafilatura.extract(
            html,
            output_format="txt",
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
        candidates = []
        if markdown:
            candidates = images_from_markdown(markdown)
        og_image = extract_og_image(html)
        if og_image and not any(item["url"] == og_image for item in candidates):
            candidates.append({"url": og_image, "alt": ""})
        return {
            "resolved_link": url,
            "text": clean_text(text or ""),
            "image": candidates[0]["url"] if candidates else None,
            "images": [item["url"] for item in candidates[:8]],
        }
    except Exception as exc:
        logger.warning("article fetch failed %s: %s", url, exc)
        return {"resolved_link": url, "text": "", "image": None}


def image_extension(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.lower()
    for extension in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if path.endswith(extension):
            return extension
    return ".jpg"


def download_image(url: str, dest_dir: Path, filename: str) -> bool:
    dest = Path(dest_dir) / filename
    if dest.exists() and dest.stat().st_size > 0:
        return True
    try:
        host = urllib.parse.urlsplit(url).netloc
        response = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": f"https://{host}/",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
            timeout=15,
            stream=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "image" not in content_type and not url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif")
        ):
            return False
        data = response.content
        if len(data) < 500 or len(data) > 8 * 1024 * 1024:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception as exc:
        logger.warning("image download failed %s: %s", url, exc)
        return False
