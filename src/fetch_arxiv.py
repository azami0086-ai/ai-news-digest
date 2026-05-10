"""arXiv取得。arXiv API Atomフィードを利用。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List

import feedparser
import requests

from config import ARXIV_KEYWORDS, Settings
from models import NewsItem

log = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query"


def _build_query(keywords: List[str]) -> str:
    # cs.AI / cs.CL / cs.LG カテゴリに限定し、キーワードORで絞る
    kw_part = " OR ".join([f'all:"{k}"' for k in keywords])
    cat_part = "(cat:cs.AI OR cat:cs.CL OR cat:cs.LG)"
    return f"({kw_part}) AND {cat_part}"


def fetch_arxiv(settings: Settings, errors: list) -> List[NewsItem]:
    items: List[NewsItem] = []
    try:
        params = {
            "search_query": _build_query(ARXIV_KEYWORDS),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": settings.arxiv_max_results,
        }
        resp = requests.get(ARXIV_API, params=params, timeout=settings.http_timeout_sec)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        threshold = datetime.now(timezone.utc) - timedelta(days=settings.recent_days + 1)

        for entry in feed.entries:
            title = (entry.get("title") or "").strip().replace("\n", " ")
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
            if published_struct:
                pub_dt = datetime(*published_struct[:6], tzinfo=timezone.utc)
                if pub_dt < threshold:
                    continue
                published = pub_dt.strftime("%Y/%m/%d")
            else:
                published = ""

            summary = (entry.get("summary") or "").strip().replace("\n", " ")
            items.append(NewsItem(
                title=title,
                url=link,
                source="arXiv",
                source_type="arxiv",
                published=published,
                snippet=summary[:600],
                category="AI論文",
            ))
    except Exception as e:
        msg = f"arxiv fetch failed: {e}"
        log.warning(msg)
        errors.append(msg)

    log.info("arxiv fetched: %d", len(items))
    return items
