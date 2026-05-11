"""publish 候補の最終選定（ソース配分）。

source_type ベースで配分を調整する:
  - official_primary（OFFICIAL_PRIMARY_SOURCES）を最優先
  - その他 official を次に採用
  - hn / arxiv は PER_SOURCE_TYPE_LIMITS の上限まで採用
  - publish_max に満たない場合は leftovers から元順序で補充

呼び出し側で重要度+priority_score 順にソートされている前提。
"""
from __future__ import annotations

from typing import List

from config import OFFICIAL_PRIMARY_SOURCES, PER_SOURCE_TYPE_LIMITS
from models import NewsItem


def diversify_by_source(items: List[NewsItem], publish_max: int) -> List[NewsItem]:
    primary: List[NewsItem] = []
    other_official: List[NewsItem] = []
    typed_limited: List[NewsItem] = []
    typed_counts: dict = {}
    leftovers: List[NewsItem] = []

    for it in items:
        if it.source in OFFICIAL_PRIMARY_SOURCES:
            primary.append(it)
        elif it.source_type == "official":
            other_official.append(it)
        else:
            limit = PER_SOURCE_TYPE_LIMITS.get(it.source_type)
            if limit is None:
                # 未登録の source_type は "その他" として 2 件まで
                limit = 2
                key = it.source_type or "other"
            else:
                key = it.source_type
            cnt = typed_counts.get(key, 0)
            if cnt < limit:
                typed_limited.append(it)
                typed_counts[key] = cnt + 1
            else:
                leftovers.append(it)

    selected: List[NewsItem] = []
    for bucket in (primary, other_official, typed_limited):
        for it in bucket:
            if len(selected) >= publish_max:
                break
            selected.append(it)
        if len(selected) >= publish_max:
            break

    if len(selected) < publish_max:
        for it in leftovers:
            if len(selected) >= publish_max:
                break
            selected.append(it)

    return selected
