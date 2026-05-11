"""冒頭サマリー生成（ルールベース）。

タイトル途中切れを使わず、公式/コミュニティ/研究の比率・タグ・実務影響方向を
集計して 2〜3 文で全体傾向を述べる。LLMは使わない（API追加コストなし）。
"""
from __future__ import annotations

from collections import Counter
from typing import List

from config import OFFICIAL_PRIMARY_SOURCES, PRACTICAL_IMPACT_KEYWORDS
from models import NewsItem


# 実務影響方向の表示用ラベル（PRACTICAL_IMPACT_KEYWORDS と整合）
IMPACT_LABELS = {
    "automation": "業務自動化",
    "enterprise": "企業導入",
    "security": "セキュリティ",
    "privacy": "プライバシー",
    "compliance": "コンプライアンス",
    "coding": "コード生成",
    "claude code": "Claude Code",
    "codex": "Codex",
    "chatgpt": "ChatGPT利用",
    "gemini": "Gemini利用",
    "ai agent": "AIエージェント",
    "agents": "AIエージェント",
}


def _bucket(item: NewsItem) -> str:
    """記事を「公式 / コミュニティ / 研究 / その他」に分類。"""
    if item.source in OFFICIAL_PRIMARY_SOURCES:
        return "公式"
    if item.source_type == "official":
        return "公式"
    if item.source_type == "hn":
        return "コミュニティ"
    if item.source_type == "arxiv":
        return "研究"
    return "その他"


def _impact_directions(items: List[NewsItem]) -> List[str]:
    """記事タイトル+スニペットから実務影響方向の代表ラベルを最大3つ抽出。"""
    found: List[str] = []
    seen = set()
    for it in items:
        text = f"{it.title} {it.snippet}".lower()
        for kw in PRACTICAL_IMPACT_KEYWORDS:
            if kw in text:
                label = IMPACT_LABELS.get(kw, kw)
                if label not in seen:
                    seen.add(label)
                    found.append(label)
                    if len(found) >= 3:
                        return found
    return found


def build_overview_facts(items: List[NewsItem]) -> dict:
    """箇条書き表示用の構造化サマリー。

    キー:
      - total: int
      - buckets: List[Tuple[str, int]]（公式/コミュニティ/研究/その他のうち件数>0）
      - topics: List[str]（タグ上位 最大4）
      - impacts: List[str]（実務影響方向 最大3）
      - a_count: int（重要度A件数）
    """
    bucket_count = Counter(_bucket(it) for it in items)
    buckets = [
        (label, bucket_count[label])
        for label in ("公式", "コミュニティ", "研究", "その他")
        if bucket_count.get(label, 0) > 0
    ]
    tag_count: Counter = Counter()
    for it in items:
        for t in it.tags:
            if t:
                tag_count[t] += 1
    topics = [t for t, _ in tag_count.most_common(4)]
    impacts = _impact_directions(items)
    a_count = sum(1 for it in items if it.importance == "A")
    return {
        "total": len(items),
        "buckets": buckets,
        "topics": topics,
        "impacts": impacts,
        "a_count": a_count,
    }


def build_overview(items: List[NewsItem]) -> str:
    """2〜3 文の冒頭サマリーを返す。タイトル途中切れは使わない。"""
    if not items:
        return "本日の掲載対象ニュースはない。"

    total = len(items)

    # 公式 / コミュニティ / 研究 / その他 の比率
    bucket_count = Counter(_bucket(it) for it in items)
    parts = []
    for label in ("公式", "コミュニティ", "研究", "その他"):
        n = bucket_count.get(label, 0)
        if n > 0:
            parts.append(f"{label} {n} 件")
    if len(parts) >= 2:
        s1 = f"本日は {' / '.join(parts)} のあわせて {total} 件を掲載した。"
    elif len(parts) == 1:
        s1 = f"本日は {parts[0]}を掲載した。"
    else:
        s1 = f"本日は {total} 件のAIニュースを掲載した。"

    # タグ集計
    tag_count: Counter = Counter()
    for it in items:
        for t in it.tags:
            if t:
                tag_count[t] += 1
    top_tags = [t for t, _ in tag_count.most_common(4)]
    if top_tags:
        s2 = f"主なトピックは {'、'.join(top_tags[:4])} など。"
    else:
        s2 = "AI関連の幅広いトピックが含まれていた。"

    # 実務影響方向
    impacts = _impact_directions(items)
    a_count = sum(1 for it in items if it.importance == "A")
    if impacts:
        if a_count > 0:
            s3 = f"実務面では {'、'.join(impacts)} への影響が中心で、重要度Aは {a_count} 件。"
        else:
            s3 = f"実務面では {'、'.join(impacts)} への影響が中心。"
    elif a_count > 0:
        s3 = f"重要度Aは {a_count} 件で、AI利用への直接的な影響が想定される。"
    else:
        s3 = "知識として把握しておきたい内容が中心。"

    return f"{s1} {s2} {s3}"
