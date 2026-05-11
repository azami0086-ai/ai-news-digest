"""publish 候補の最終選定（ソース配分）。

source_type ベースで配分を調整する:
  - official_primary（OFFICIAL_PRIMARY_SOURCES）を最優先
  - その他 official（primary 外）を次に採用
  - hn / arxiv / その他 は PER_SOURCE_TYPE_LIMITS で上限を設ける
  - 通常時は leftovers を含む補充段階でも上限を破らない
  - 例外: 公式記事（primary + other_official）の合計が
    EMERGENCY_FILL_THRESHOLD 未満のときに限り、上限超過分を補充して
    掲載件数を確保する（log.info で理由を出す）

呼び出し側で重要度 + priority_score 順にソート済みである前提。
"""
from __future__ import annotations

import logging
from typing import List

from config import (
    DEFAULT_OTHER_TYPE_LIMIT,
    EMERGENCY_FILL_THRESHOLD,
    OFFICIAL_PRIMARY_SOURCES,
    PER_SOURCE_TYPE_LIMITS,
)
from models import NewsItem

log = logging.getLogger(__name__)


def diversify_by_source(items: List[NewsItem], publish_max: int) -> List[NewsItem]:
    primary: List[NewsItem] = []
    other_official: List[NewsItem] = []
    typed_within_limit: List[NewsItem] = []
    typed_overflow: List[NewsItem] = []
    typed_counts: dict = {}

    for it in items:
        if it.source in OFFICIAL_PRIMARY_SOURCES:
            primary.append(it)
            continue
        if it.source_type == "official":
            other_official.append(it)
            continue
        stype = it.source_type or "other"
        limit = PER_SOURCE_TYPE_LIMITS.get(stype, DEFAULT_OTHER_TYPE_LIMIT)
        cnt = typed_counts.get(stype, 0)
        if cnt < limit:
            typed_within_limit.append(it)
            typed_counts[stype] = cnt + 1
        else:
            typed_overflow.append(it)

    selected: List[NewsItem] = []
    # 段階1〜3: primary公式 → その他公式 → 上限内 typed
    for bucket in (primary, other_official, typed_within_limit):
        for it in bucket:
            if len(selected) >= publish_max:
                return selected
            selected.append(it)

    # 段階4: 公式が極端に少ない場合のみ例外補充（HN/arXiv の上限を超えて採用）
    official_count = len(primary) + len(other_official)
    if len(selected) < publish_max and official_count < EMERGENCY_FILL_THRESHOLD:
        if typed_overflow:
            log.info(
                "emergency fill: official_count=%d < threshold=%d. "
                "Adding up to %d items from typed_overflow.",
                official_count, EMERGENCY_FILL_THRESHOLD,
                publish_max - len(selected),
            )
            for it in typed_overflow:
                if len(selected) >= publish_max:
                    break
                selected.append(it)

    return selected
