"""DeepSeek-based summarization with extractive fallback."""

from __future__ import annotations

import json
import logging
import os
import re

import requests

from .news import clean_text

logger = logging.getLogger(__name__)

MAX_TITLE = 40
MAX_SUMMARY = 220
MAX_DETAIL = 1400
MAX_TAGS = 5


def api_key_available() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())


def clean_paragraph_text(value: str) -> str:
    value = re.sub(r"[ \t\r\f\v]+", " ", value or "")
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def truncate_sentences(text: str, max_chars: int) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for separator in "。！？!?；;":
        index = cut.rfind(separator)
        if index > max_chars * 0.5:
            return cut[: index + 1]
    return cut.rstrip() + "…"


def build_prompt(article: dict, category: dict, settings: dict) -> str:
    cfg = settings.get("llm", {})
    max_chars = int(cfg.get("max_source_chars", 4000))
    source = article.get("text") or article.get("summary") or article.get("title") or ""
    source = clean_text(source)[:max_chars]
    return (
        "请根据以下新闻素材，生成适合中文晨报阅读的结构化摘要。\n"
        f"分类：{category['name']}\n"
        f"原标题：{article.get('title', '')}\n"
        f"来源：{article.get('source_name', '未知')}\n"
        f"发布时间：{article.get('published_label', '未知')}\n"
        "素材：\n"
        f"{source}\n\n"
        "只输出一个 JSON 对象，字段必须为：\n"
        '{"title":"中文标题，不超过 22 字","summary":"简短解释，1-2 句，50-90 字",'
        '"detail":"详细解释，250-320 字，说明背景、影响和后续看点，可用换行分 2-3 段",'
        '"tags":["标签1","标签2","标签3"],"importance":0到100的整数}'
    )


def call_llm(article: dict, category: dict, settings: dict) -> dict:
    cfg = settings.get("llm", {})
    api_key = os.environ["DEEPSEEK_API_KEY"].strip()
    payload = {
        "model": cfg.get("model", "deepseek-chat"),
        "messages": [
            {
                "role": "system",
                "content": "你是一位资深中文新闻编辑，擅长把新闻改写成客观、准确、易读的晨报摘要。只输出 JSON。",
            },
            {"role": "user", "content": build_prompt(article, category, settings)},
        ],
        "temperature": 0.3,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = float(cfg.get("timeout_seconds", 60))
    retries = int(cfg.get("max_retries", 2))
    for attempt in range(retries + 1):
        try:
            response = requests.post(cfg.get("api_url"), headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = parse_llm_json(content)
            if parsed:
                return normalize_result(parsed, article, category)
        except Exception as exc:
            logger.warning("LLM attempt %s failed: %s", attempt + 1, exc)
    return fallback_summary(article, category)


def parse_llm_json(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def normalize_result(data: dict, article: dict, category: dict) -> dict:
    title = clean_text(data.get("title") or article.get("title") or category["name"])[:MAX_TITLE]
    summary = clean_text(data.get("summary") or article.get("summary") or title)[:MAX_SUMMARY]
    detail = clean_paragraph_text(data.get("detail") or article.get("text") or summary)[:MAX_DETAIL]
    tags = [clean_text(tag)[:12] for tag in (data.get("tags") or []) if clean_text(tag)]
    tags = (tags or [category["name"]])[:MAX_TAGS]
    try:
        importance = max(0, min(100, int(data.get("importance", 50))))
    except (TypeError, ValueError):
        importance = 50
    return {
        "title": title,
        "summary": summary,
        "detail": detail,
        "tags": tags,
        "importance": importance,
    }


def fallback_summary(article: dict, category: dict) -> dict:
    rss_summary = clean_text(article.get("summary") or "")
    text = clean_text(article.get("text") or "")
    title = clean_text(article.get("title") or category["name"])[:MAX_TITLE]
    summary = truncate_sentences(rss_summary or text or title, 90) or title
    detail = truncate_sentences(text or rss_summary or title, 300) or f"本条暂无更多正文，原标题：{title}"
    if len(detail) <= len(summary):
        detail = summary + "（更多内容请点击阅读原文查看）"
    return {
        "title": title,
        "summary": summary,
        "detail": detail,
        "tags": [category["name"], clean_text(article.get("source_name") or "新闻")],
        "importance": max(0, min(100, int(round(article.get("score", 50))))),
    }


def summarize_articles(selected: dict[str, list[dict]], settings: dict, force_fallback: bool = False) -> dict[str, dict]:
    results: dict[str, dict] = {}
    use_llm = (
        not force_fallback
        and api_key_available()
        and settings.get("llm", {}).get("enabled", True)
    )
    for category in settings["categories"]:
        for article in selected.get(category["id"], []):
            if article.get("id") in results:
                continue
            results[article["id"]] = (
                call_llm(article, category, settings) if use_llm else fallback_summary(article, category)
            )
    return results
