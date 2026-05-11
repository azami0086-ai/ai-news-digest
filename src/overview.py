"""冒頭サマリー生成（ルールベース）。

タイトル途中切れを使わず、ソース/タグ/重要度を集計して 2〜3 文で全体傾向を述べる。
LLMは使わない（API追加コストを発生させないため）。
"""
from __future__ import annotations

from collections import Counter
from typing import List

from models import NewsItem


# ソース名からベンダー名相当に正規化（冒頭文で読みやすくするため）
SOURCE_TO_VENDOR = {
    "OpenAI Blog": "OpenAI",
    "Anthropic News": "Anthropic",
    "Google The Keyword - AI": "Google",
    "Google Workspace Updates": "Google Workspace",
    "Google DeepMind Blog": "Google DeepMind",
    "Microsoft AI Blog": "Microsoft",
    "HuggingFace Blog": "Hugging Face",
    "Meta AI Blog": "Meta",
    "Hacker News": "Hacker News",
    "arXiv": "arXiv",
}


def _vendor(source: str) -> str:
    return SOURCE_TO_VENDOR.get(source, source or "その他")


def build_overview(items: List[NewsItem]) -> str:
    """2〜3 文の冒頭サマリーを返す。タイトル途中切れは使わない。"""
    if not items:
        return "本日の掲載対象ニュースはない。"

    # ベンダー集計
    vendor_count = Counter(_vendor(it.source) for it in items)
    top_vendors = [v for v, _ in vendor_count.most_common(3)]

    # タグ集計
    tag_count: Counter = Counter()
    for it in items:
        for t in it.tags:
            if t:
                tag_count[t] += 1
    top_tags = [t for t, _ in tag_count.most_common(4)]

    a_count = sum(1 for it in items if it.importance == "A")
    b_count = sum(1 for it in items if it.importance == "B")
    total = len(items)

    # 1文目: ベンダー傾向
    if len(top_vendors) >= 2:
        s1 = f"本日は {top_vendors[0]} と {top_vendors[1]} を中心に {total} 件のAIニュースが集まった。"
    elif len(top_vendors) == 1:
        s1 = f"本日は {top_vendors[0]} 関連を中心に {total} 件のAIニュースが集まった。"
    else:
        s1 = f"本日は {total} 件のAIニュースが集まった。"

    # 2文目: トピック傾向
    if top_tags:
        tag_text = "、".join(top_tags[:3])
        s2 = f"主なトピックは {tag_text} など。"
    else:
        s2 = "幅広いAI動向が含まれていた。"

    # 3文目: 重要度傾向
    if a_count > 0:
        s3 = f"重要度Aは {a_count} 件で、AI利用への直接的な影響が想定される。"
    elif b_count > 0:
        s3 = f"重要度Bが {b_count} 件で、今後のAI活用方針に関係する内容が中心。"
    else:
        s3 = "知識として把握しておきたい内容が中心。"

    return f"{s1} {s2} {s3}"
