"""Hacker News取得。Algolia HN Search APIを使う（公開API、認証不要）。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List

import requests

from config import HN_KEYWORDS, Settings
from models import NewsItem

log = logging.getLogger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"


def fetch_hn(settings: Settings, errors: list) -> List[NewsItem]:
    items: List[NewsItem] = []
    seen_urls = set()
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=settings.recent_days + 1)).timestamp())

    for kw in HN_KEYWORDS:
        try:
            params = {
                "query": kw,
                "tags": "story",
                "numericFilters": f"created_at_i>{since_ts}",
                "hitsPerPage": settings.hn_max_per_keyword,
            }
            resp = requests.get(HN_SEARCH_URL, params=params, timeout=settings.http_timeout_sec)
            resp.raise_for_status()
            data = resp.json()
            for hit in data.get("hits", []):
                url = (hit.get("url") or "").strip()
                title = (hit.get("title") or "").strip()
                if not title or not url:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                created = hit.get("created_at", "")
                published = created[:10].replace("-", "/") if created else ""
                items.append(NewsItem(
                    title=title,
                    url=url,
                    source="Hacker News",
                    source_type="hn",
                    published=published,
                    snippet=f"HN points={hit.get('points', 0)} comments={hit.get('num_comments', 0)} keyword={kw}",
                    category="",
                    aux_urls=[f"https://news.ycombinator.com/item?id={hit.get('objectID')}"],
                ))
        except Exception as e:
            msg = f"hn fetch failed for keyword {kw!r}: {e}"
            log.warning(msg)
            errors.append(msg)

    log.info("hn fetched: %d", len(items))
    return items
