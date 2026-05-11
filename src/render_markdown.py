"""Obsidian保存用Markdownを生成。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from models import NewsItem
from overview import build_overview_bullets


def _normalize_tag(tag: str) -> str:
    return "#" + "".join(ch for ch in tag if ch.isalnum() or ch in "_-一-鿿ぁ-んァ-ヶ")


def _overview_lines(items: List[NewsItem]) -> List[str]:
    return build_overview_bullets(items)


CREDIT_WARNING_MD_LINES = [
    "> **注意：**",
    "> Claude APIクレジット不足または利用上限により、AI要約を実行できなかった可能性があります。",
    "> このMarkdownは簡易版です。",
    "> Anthropic ConsoleのBillingを確認してください。",
    "",
]

API_WARNING_MD_LINES = [
    "> **注意：**",
    "> Claude API要約に失敗しました。",
    "> このMarkdownは簡易版です。",
    "> Anthropic ConsoleおよびGitHub Actionsのログを確認してください。",
    "",
]


def render_markdown(items: List[NewsItem], date_str: str,
                    credit_warning: bool = False, api_warning: bool = False) -> str:
    a_list = [it for it in items if it.importance == "A"]
    overview_lines = _overview_lines(items)

    lines = []
    lines.append(f"# AIニュース {date_str}")
    lines.append("")
    if credit_warning:
        lines.extend(CREDIT_WARNING_MD_LINES)
    elif api_warning:
        lines.extend(API_WARNING_MD_LINES)
    # 概要は箇条書きそのままを引用ブロック化
    for ov in overview_lines:
        lines.append(f"> {ov}")
    lines.append("")

    if a_list:
        lines.append("## 重要度A 一覧")
        for it in a_list:
            display_title = it.title_ja or it.title
            lines.append(f"- [{display_title}]({it.url}) ({it.published or '日付不明'} / {it.source})")
            if it.title_ja and it.title and it.title_ja.strip() != it.title.strip():
                lines.append(f"  - Original: {it.title}")
        lines.append("")

    lines.append("## 各ニュース詳細")
    lines.append("")

    if not items:
        lines.append("該当ニュースはなかった。")
        return "\n".join(lines)

    for it in items:
        display_title = it.title_ja or it.title
        lines.append(f"### [{it.importance or 'C'}] {display_title}")
        lines.append("")
        if it.title_ja and it.title and it.title_ja.strip() != it.title.strip():
            lines.append(f"_Original: {it.title}_")
            lines.append("")
        lines.append(f"- 公開日: {it.published or '日付不明'}")
        lines.append(f"- 出所: {it.source}")
        lines.append(f"- 根拠URL: {it.url}")
        if it.aux_urls:
            lines.append("- 補助URL:")
            for u in it.aux_urls:
                lines.append(f"  - {u}")
        lines.append("")
        lines.append(f"**何の話？**: {it.summary or it.snippet[:200] or '(なし)'}")
        lines.append("")
        lines.append(f"**何が変わる？**: {it.impact or '未分析'}")
        if it.notes:
            lines.append("")
            lines.append(f"**注意すること**: {it.notes}")
        if it.dedupe_note:
            lines.append("")
            lines.append(f"**重複確認結果**: {it.dedupe_note}")
        if it.tags:
            lines.append("")
            lines.append("タグ: " + " ".join(_normalize_tag(t) for t in it.tags))
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def write_markdown(items: List[NewsItem], date: datetime, output_dir: Path,
                   credit_warning: bool = False, api_warning: bool = False) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{date.strftime('%Y-%m-%d')}_AIニュース.md"
    text = render_markdown(items, date.strftime("%Y/%m/%d"),
                           credit_warning=credit_warning,
                           api_warning=api_warning)
    path.write_text(text, encoding="utf-8")
    return path
