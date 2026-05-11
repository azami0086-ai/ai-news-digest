"""公式情報取得。RSSがあればRSS、なければ静的HTMLから抜粋。"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List, Tuple
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from config import OFFICIAL_SOURCES, Settings
from models import NewsItem

log = logging.getLogger(__name__)


# 単独で出現したら記事タイトルとしては不採用にするナビゲーション・カテゴリ語
NAV_TITLES = frozenset([
    "skip to main content", "skip to content",
    "research", "product", "announcements", "engineering", "policy",
    "company", "news", "blog", "home", "careers", "sign in", "log in",
    "menu", "about", "contact", "press", "events",
    "support", "documentation", "docs", "api", "pricing",
    "stories", "perspectives", "newsroom", "all posts",
])

# タイトル末尾に貼りつく「カテゴリ名 + 日付 + 本文冒頭」を切るためのパターン
_TRAILING_CATEGORY_DATE = re.compile(
    r"\s+(Product|Research|Announcements|Engineering|Policy|Company|News|Blog)\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}.*$",
    re.IGNORECASE,
)
# タイトル末尾に貼りつく「日付 + 本文冒頭」だけのパターン
_TRAILING_DATE = re.compile(
    r"\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}.*$",
    re.IGNORECASE,
)
_LEADING_SKIP = re.compile(r"^\s*skip to (main )?content\s*", re.IGNORECASE)

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DATE_NUMERIC = re.compile(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})")
_DATE_ENGLISH = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)
_DATE_FROM_URL = re.compile(r"/(\d{4})/(\d{1,2})/(\d{1,2})(?:/|-)")


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


def _extract_date_from_text(text: str) -> str:
    """テキストから yyyy/mm/dd を抽出。失敗時 ''。"""
    if not text:
        return ""
    m = _DATE_NUMERIC.search(text)
    if m:
        y, mo, d = m.groups()
        try:
            return f"{int(y):04d}/{int(mo):02d}/{int(d):02d}"
        except ValueError:
            pass
    m = _DATE_ENGLISH.search(text)
    if m:
        month = _MONTH_MAP.get(m.group(1).lower()[:3])
        if month:
            try:
                return f"{int(m.group(3)):04d}/{month:02d}/{int(m.group(2)):02d}"
            except ValueError:
                pass
    return ""


def _extract_date_from_url(url: str) -> str:
    if not url:
        return ""
    m = _DATE_FROM_URL.search(url)
    if m:
        y, mo, d = m.groups()
        try:
            return f"{int(y):04d}/{int(mo):02d}/{int(d):02d}"
        except ValueError:
            pass
    return ""


def _clean_title(raw: str) -> str:
    """タイトルからナビ語・カテゴリ+日付混入・本文冒頭混入を除く。"""
    if not raw:
        return ""
    text = re.sub(r"\s+", " ", raw).strip()
    text = _LEADING_SKIP.sub("", text)
    # 「Product Apr 16, 2026 ...本文冒頭」を除去
    text = _TRAILING_CATEGORY_DATE.sub("", text)
    # 「Apr 16, 2026 ...本文冒頭」を除去
    text = _TRAILING_DATE.sub("", text)
    # 末尾の数値日付以降を除去（"... 2026/04/16 lorem..."）
    text = re.sub(r"\s+\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}.*$", "", text)
    text = text.strip(" -|·–—　")
    return text


def _truncate_title(title: str, max_len: int = 120) -> str:
    """120文字以内に整形。単語境界で切って末尾に … を付ける。"""
    if len(title) <= max_len:
        return title
    cut = title[:max_len]
    space = cut.rfind(" ")
    if space > int(max_len * 0.6):
        cut = cut[:space]
    return cut.rstrip(" -|·–—　") + "…"


def _is_valid_article_title(title: str) -> bool:
    """ナビゲーション単独タイトル等を弾く。"""
    if not title:
        return False
    if len(title) < 8:
        return False
    if title.strip().lower() in NAV_TITLES:
        return False
    # 大半が記号・空白
    letters = re.sub(r"[\s\-_/·–—|]+", "", title)
    if len(letters) < 6:
        return False
    return True


def _process_title(raw: str) -> str:
    """整形 + 検証してOKなら返す。NG なら空文字。"""
    cleaned = _clean_title(raw)
    if not _is_valid_article_title(cleaned):
        return ""
    return _truncate_title(cleaned)


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
        raw_title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        title = _process_title(raw_title)
        if not title or not link:
            continue
        # RSSは published / updated / pubDate を最優先
        published = _fmt_date(entry.get("published_parsed") or entry.get("updated_parsed"))
        if not published:
            # 文字列フィールドからフォールバック
            for k in ("published", "updated", "pubDate"):
                v = entry.get(k)
                if v:
                    published = _extract_date_from_text(v)
                    if published:
                        break
        if not published:
            published = _extract_date_from_url(link)

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


def _extract_html_link_context(a) -> Tuple[str, str]:
    """<a> 要素からタイトル候補と日付候補テキストを抽出。

    リンク自身のテキスト・周辺の小要素から日付らしき文字列を集める。
    """
    title_text = a.get_text(" ", strip=True)
    # 親要素・兄弟要素からテキストを少し拾う（直近1階層まで）
    context = title_text
    parent = a.find_parent(["article", "li", "div"])
    if parent is not None:
        ctx = parent.get_text(" ", strip=True)
        if ctx and len(ctx) < 2000:
            context = ctx
    return title_text, context


def fetch_html(src, settings: Settings) -> List[NewsItem]:
    items: List[NewsItem] = []
    headers = {"User-Agent": "ai-news-digest/1.0 (+https://github.com/)"}
    resp = requests.get(src.url, headers=headers, timeout=settings.http_timeout_sec)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        full = urljoin(src.url, href)
        if full in seen:
            continue
        # 同一ドメイン内のニュース系リンクに絞る
        if not any(seg in full for seg in ("/news", "/blog", "/post", "/release", "/announce", "/research")):
            continue
        raw_title, context_text = _extract_html_link_context(a)
        title = _process_title(raw_title)
        if not title:
            continue

        published = _extract_date_from_text(context_text) or _extract_date_from_url(full)

        seen.add(full)
        items.append(NewsItem(
            title=title,
            url=full,
            source=src.name,
            source_type="official",
            published=published,
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
