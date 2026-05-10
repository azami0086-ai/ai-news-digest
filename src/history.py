"""過去掲載済みニュースの照合。

logs/*.json から過去N日分の published_items_meta を読み、
当日候補のうち掲載済みと判断できるものを除外する。

判定:
- 正規化URL一致 → 同一ニュース
- タイトル類似度がしきい値以上 → 同一ニュース
- それ未満なら別ニュース（続報・別発表として通す）
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple

from dedupe import normalize_url
from models import NewsItem

log = logging.getLogger(__name__)


def _norm_title_for_history(t: str) -> str:
    import re
    t = (t or "").lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def load_history(logs_dir: Path, lookback_days: int) -> Tuple[set, List[Dict[str, str]]]:
    """過去 lookback_days 日分の logs/*.json から掲載済みメタを集める。

    戻り値: (掲載済み正規化URL集合, [掲載済みメタdict, ...])
    """
    if not logs_dir.exists():
        return set(), []

    cutoff = datetime.now().date() - timedelta(days=lookback_days)
    urls: set = set()
    metas: List[Dict[str, str]] = []

    for path in sorted(logs_dir.glob("*.json")):
        # ファイル名 YYYY-MM-DD.json 想定。範囲外はスキップ。
        try:
            file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("history load skipped %s: %s", path.name, e)
            continue

        for meta in data.get("published_items_meta", []) or []:
            url = (meta.get("url") or "").strip()
            norm = (meta.get("normalized_url") or "").strip()
            if not norm and url:
                norm = normalize_url(url)
            if norm:
                urls.add(norm)
            metas.append({
                "url": url,
                "normalized_url": norm,
                "title": (meta.get("title") or "").strip(),
                "published": (meta.get("published") or "").strip(),
                "source": (meta.get("source") or "").strip(),
            })

    log.info("history loaded: %d urls / %d metas (lookback=%dd)",
             len(urls), len(metas), lookback_days)
    return urls, metas


def is_already_published(
    item: NewsItem,
    history_urls: set,
    history_metas: List[Dict[str, str]],
    title_threshold: float,
) -> bool:
    """過去に掲載済みかどうかを判定。"""
    norm = normalize_url(item.url)
    if norm and norm in history_urls:
        return True
    item_title = _norm_title_for_history(item.title)
    if not item_title:
        return False
    for meta in history_metas:
        prev_title = _norm_title_for_history(meta.get("title", ""))
        if not prev_title:
            continue
        ratio = SequenceMatcher(None, item_title, prev_title).ratio()
        if ratio >= title_threshold:
            return True
    return False


def filter_already_published(
    items: List[NewsItem],
    logs_dir: Path,
    lookback_days: int,
    title_threshold: float,
) -> Tuple[List[NewsItem], int]:
    """過去掲載済みを除外したリストを返す。戻り値: (残ったitems, 除外件数)"""
    urls, metas = load_history(logs_dir, lookback_days)
    if not urls and not metas:
        return items, 0

    kept: List[NewsItem] = []
    excluded = 0
    for it in items:
        if is_already_published(it, urls, metas, title_threshold):
            excluded += 1
            log.info("history-excluded: %s", it.title[:80])
        else:
            kept.append(it)
    return kept, excluded


def build_meta(item: NewsItem) -> Dict[str, str]:
    """掲載アイテムから次回照合用メタを生成。"""
    return {
        "url": item.url or "",
        "normalized_url": normalize_url(item.url or ""),
        "title": item.title or "",
        "published": item.published or "",
        "source": item.source or "",
    }
