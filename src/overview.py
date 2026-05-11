"""冒頭サマリー生成（ルールベース）。

タイトル途中切れを使わず、公式/コミュニティ/研究の比率・タグ・実務影響方向を
集計し、概要を箇条書きで返す。LLMは使わない（API追加コストなし）。
"""
from __future__ import annotations

import html as _html
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


# 概要箇条書きの「主なトピック」表示名マップ（キーは lowercase）。
# 既存タグ表記がばらついても読みやすい表記に揃える。未登録タグは元の文字列を使う。
TOPIC_DISPLAY_NAMES = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "claude code": "Claude Code",
    "claudecode": "Claude Code",
    "gemini": "Gemini",
    "google": "Google",
    "google workspace": "Google Workspace",
    "googleworkspace": "Google Workspace",
    "notebooklm": "NotebookLM",
    "deepmind": "DeepMind",
    "microsoft": "Microsoft",
    "copilot": "Copilot",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "codex": "Codex",
    "huggingface": "Hugging Face",
    "meta": "Meta",
    "enterprise": "エンタープライズ",
    "security": "セキュリティ",
    "privacy": "プライバシー",
    "compliance": "コンプライアンス",
    "automation": "業務自動化",
    "ai agent": "AIエージェント",
    "agents": "AIエージェント",
    "agent": "AIエージェント",
    "llm": "LLM",
    "rag": "RAG",
    "arxiv": "arXiv",
    "hacker news": "Hacker News",
    "hackernews": "Hacker News",
}


def display_topic(tag: str) -> str:
    if not tag:
        return tag
    return TOPIC_DISPLAY_NAMES.get(tag.strip().lower(), tag)


def display_topics(tags: List[str]) -> List[str]:
    """表示名へ変換した上で、順序を保ったまま重複除去。"""
    return list(dict.fromkeys(display_topic(t) for t in tags if t))


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


def format_overview_publish_line(facts: dict) -> str:
    """「掲載件数:」行の文字列。バケット件数 + 合計を併記。"""
    bucket_part = " / ".join(f"{label} {n} 件" for label, n in facts["buckets"])
    if bucket_part:
        return f"掲載件数: {bucket_part} / 合計 {facts['total']} 件"
    return f"掲載件数: 合計 {facts['total']} 件"


def build_overview_bullets(items: List[NewsItem]) -> List[str]:
    """plain text 用の概要箇条書き行群（先頭に「概要:」ヘッダ付き）。"""
    if not items:
        return ["概要:", "- 本日の掲載対象ニュースはない"]
    facts = build_overview_facts(items)
    topics = display_topics(facts["topics"])
    topics_str = "、".join(topics) if topics else "なし"
    impacts_str = "、".join(facts["impacts"]) if facts["impacts"] else "なし"
    return [
        "概要:",
        f"- {format_overview_publish_line(facts)}",
        f"- 主なトピック: {topics_str}",
        f"- 実務影響: {impacts_str}",
        f"- 重要度A: {facts['a_count']} 件",
    ]


def build_overview_html_block(items: List[NewsItem]) -> str:
    """HTML 用の概要セクション（<p>概要:</p><ul><li>...</li></ul>）。"""
    if not items:
        return "<p>概要:</p><ul><li>本日の掲載対象ニュースはない</li></ul>"
    facts = build_overview_facts(items)
    topics = display_topics(facts["topics"])
    topics_str = "、".join(topics) if topics else "なし"
    impacts_str = "、".join(facts["impacts"]) if facts["impacts"] else "なし"
    items_html = "".join([
        f"<li>{_html.escape(format_overview_publish_line(facts), quote=True)}</li>",
        f"<li>主なトピック: {_html.escape(topics_str, quote=True)}</li>",
        f"<li>実務影響: {_html.escape(impacts_str, quote=True)}</li>",
        f"<li>重要度A: {facts['a_count']} 件</li>",
    ])
    return f"<p class=\"overview-head\">概要:</p><ul class=\"overview-list\">{items_html}</ul>"


def build_overview_markdown(items: List[NewsItem]) -> str:
    """Markdown 用の概要文字列（複数行、先頭に「概要:」、各行 '- ' 形式）。"""
    return "\n".join(build_overview_bullets(items))
