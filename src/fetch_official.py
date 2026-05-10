"""公式情報取得。RSSがあればRSS、なければ静的HTMLから抜粋。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from config import OFFICIAL_SOURCES, Settings
from models import NewsItem

log = logging.getLogger(__name__)


def _fmt_date(value) -> str:
    """yyyy/mm/dd を返す。失敗時は空文字。"""
    if value is None:
        return ""
    try:
        if hasattr(value, "tm_year"):
            return f"{value.tm_year:04d}/{value.tm_mon:02d}/{value.tm_mday:02d}"
        if isinstance(value, datetime):
            return value.strftime("%Y/%m/%d")
        if isinstance(value, str):
            return value[:10].replace("-", "/")
    except Exception:
        return ""
    return ""


def _is_recent(date_str: str, recent_days: int) -> bool:
    if not date_str:
        return True  # 日付不明は残す
    try:
        d = datetime.strptime(date_str, "%Y/%m/%d").replace(tzinfo=timezone.utc)
        threshold = datetime.now(timezone.utc) - timedelta(days=recent_days + 1)
        return d >= threshold
    except Exception:
        return True


def fetch_rss(src, settings: Settings) -> List[NewsItem]:
    items: List[NewsItem] = []
    feed = feedparser.parse(src.url)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS parse failed: {src.url}")
    for entry in feed.entries[: settings.official_max_per_source]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = _fmt_date(entry.get("published_parsed") or entry.get("updated_parsed"))
        snippet = ""
        for key in ("summary", "description"):
            v = entry.get(key)
            if v:
                snippet = BeautifulSoup(v, "html.parser").get_text(" ", strip=True)
                break
        items.append(NewsItem(
            title=title,
            url=link,
            source=src.name,
            source_type="official",
            published=published,
            snippet=snippet[:500],
            category=src.category,
        ))
    return items


def fetch_html(src, settings: Settings) -> List[NewsItem]:
    items: List[NewsItem] = []
    headers = {"User-Agent": "ai-news-digest/1.0 (+https://github.com/)"}
    resp = requests.get(src.url, headers=headers, timeout=settings.http_timeout_sec)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 8:
            continue
        full = urljoin(src.url, href)
        if full in seen:
            continue
        # 同一ドメイン内のニュース系リンクに絞る
        if not any(seg in full for seg in ("/news", "/blog", "/post", "/release", "/announce", "/research")):
            continue
        seen.add(full)
        items.append(NewsItem(
            title=text[:200],
            url=full,
            source=src.name,
            source_type="official",
            published="",
            snippet="",
            category=src.category,
        ))
        if len(items) >= settings.official_max_per_source:
            break
    return items


def fetch_official(settings: Settings, errors: list) -> List[NewsItem]:
    """全公式情報を取得。失敗してもerrorsに残して継続。"""
    all_items: List[NewsItem] = []
    for src in OFFICIAL_SOURCES:
        try:
            if src.kind == "rss":
                items = fetch_rss(src, settings)
            else:
                items = fetch_html(src, settings)
            # 古すぎるものを除外
            items = [it for it in items if _is_recent(it.published, settings.recent_days)]
            all_items.extend(items)
            log.info("official fetched: %s -> %d", src.name, len(items))
        except Exception as e:
            msg = f"official fetch failed: {src.name}: {e}"
            log.warning(msg)
            errors.append(msg)
    return all_items
