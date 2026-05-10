"""重複排除。URL正規化＋タイトル類似度で同一ニュースを統合する。"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import List
from urllib.parse import urlparse, urlunparse

from models import NewsItem

log = logging.getLogger(__name__)

# 公式情報を主根拠とするための優先度
SOURCE_TYPE_RANK = {"official": 3, "arxiv": 2, "hn": 1, "x": 0}


def normalize_url(url: str) -> str:
    """クエリパラメータの一部やfragmentを落として正規化。"""
    try:
        p = urlparse(url)
        # utm_系などのクエリは落とす
        query = "&".join([
            seg for seg in (p.query or "").split("&")
            if seg and not seg.lower().startswith(("utm_", "ref=", "from=", "fbclid", "gclid"))
        ])
        path = (p.path or "/").rstrip("/") or "/"
        return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", query, ""))
    except Exception:
        return url


def _norm_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^\w\s぀-ヿ一-鿿]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio()


def dedupe(items: List[NewsItem]) -> List[NewsItem]:
    """重複統合した結果のリストを返す。"""
    # 取得元ごとの優先度＋公開日が新しいものを主に残す
    items = sorted(
        items,
        key=lambda x: (SOURCE_TYPE_RANK.get(x.source_type, 0), x.published or ""),
        reverse=True,
    )

    merged: List[NewsItem] = []
    for it in items:
        norm = normalize_url(it.url)
        match = None
        for m in merged:
            if normalize_url(m.url) == norm:
                match = m
                break
            if _similar(m.title, it.title) >= 0.82:
                match = m
                break
        if match is None:
            merged.append(it)
            continue

        # 補助情報として統合
        note = f"重複統合: {it.source}"
        if match.dedupe_note:
            match.dedupe_note += f"; {note}"
        else:
            match.dedupe_note = note
        if it.url and it.url != match.url and it.url not in match.aux_urls:
            match.aux_urls.append(it.url)
        for au in it.aux_urls:
            if au and au not in match.aux_urls and au != match.url:
                match.aux_urls.append(au)
        # 公式情報のスニペットが空でhn/arxiv側にあれば補完
        if not match.snippet and it.snippet:
            match.snippet = it.snippet
        if not match.published and it.published:
            match.published = it.published

    log.info("dedupe: %d -> %d", len(items), len(merged))
    return merged
