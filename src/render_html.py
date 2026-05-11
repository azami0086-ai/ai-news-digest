"""スマホ向けレスポンシブHTMLを生成。外部CSSに依存しない。"""
from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path
from typing import List

from models import NewsItem
from overview import build_overview


CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic UI", "Segoe UI", sans-serif;
  font-size: 16px;
  line-height: 1.7;
  background: #f7f7f9;
  color: #1f1f1f;
}
@media (prefers-color-scheme: dark) {
  body { background: #14161a; color: #e6e6e6; }
  .card { background: #1d2026 !important; border-color: #2a2e36 !important; }
  .meta { color: #9aa0a6 !important; }
  a { color: #6cb4ff !important; }
  .tag { background: #2a2e36 !important; color: #cfd2d8 !important; }
  .summary-bar { background: #1d2026 !important; border-color: #2a2e36 !important; }
}
.wrap { max-width: 760px; margin: 0 auto; padding: 16px; }
header { padding: 20px 4px 8px; }
header h1 { font-size: 22px; margin: 0 0 4px; }
header .date { color: #6b7280; font-size: 14px; }
.summary-bar {
  margin: 12px 0 20px; padding: 14px 16px;
  background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
  font-size: 15px;
}
.credit-warning {
  margin: 12px 0; padding: 14px 16px;
  background: #fff1f0; border: 2px solid #d92d20; border-left: 8px solid #d92d20;
  border-radius: 10px; color: #842029;
  font-size: 15px; font-weight: 600; line-height: 1.6;
}
.credit-warning .label {
  display: inline-block; background: #d92d20; color: #fff;
  padding: 2px 10px; border-radius: 6px; font-size: 13px; margin-right: 8px;
}
@media (prefers-color-scheme: dark) {
  .credit-warning { background: #2a1212 !important; color: #ffb8b0 !important; border-color: #d92d20 !important; }
}
.card {
  background: #fff; border: 1px solid #e5e7eb; border-radius: 14px;
  padding: 14px 16px; margin: 10px 0;
}
.card.A { border-left: 6px solid #d92d20; }
.card.B { border-left: 6px solid #f79009; }
.card.C { border-left: 6px solid #667085; }
.title { font-size: 17px; font-weight: 700; margin: 0 0 6px; line-height: 1.4; }
.title a { color: inherit; text-decoration: none; }
.title a:hover { text-decoration: underline; }
.meta { color: #6b7280; font-size: 13px; margin-bottom: 8px; }
.imp { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; margin-right: 6px; }
.imp.A { background: #fee4e2; color: #d92d20; }
.imp.B { background: #fef0c7; color: #b54708; }
.imp.C { background: #e4e7ec; color: #344054; }
.section { margin: 6px 0; }
.section .label { font-size: 12px; color: #6b7280; }
.tags { margin-top: 8px; }
.tag {
  display: inline-block; background: #eef2f7; color: #344054;
  font-size: 12px; padding: 2px 8px; border-radius: 999px; margin: 2px 4px 2px 0;
}
.aux { font-size: 13px; margin-top: 6px; word-break: break-all; }
.aux a { color: #1d4ed8; }
.empty { padding: 24px; text-align: center; color: #6b7280; }
footer { color: #9aa3af; font-size: 12px; text-align: center; padding: 24px 0; }
"""


def _escape(s: str) -> str:
    return html.escape(s or "", quote=True)


def _render_card(item: NewsItem) -> str:
    imp = item.importance if item.importance in ("A", "B", "C") else "C"
    tags_html = "".join(f'<span class="tag">#{_escape(t)}</span>' for t in item.tags)
    aux_html = ""
    if item.aux_urls:
        aux_html = '<div class="aux"><span class="label">補助URL</span><br>' + "<br>".join(
            f'<a href="{_escape(u)}" target="_blank" rel="noopener">{_escape(u)}</a>' for u in item.aux_urls
        ) + "</div>"
    notes_html = ""
    if item.notes:
        notes_html = f'<div class="section"><span class="label">実務上の注意点</span><br>{_escape(item.notes)}</div>'
    dedupe_html = ""
    if item.dedupe_note:
        dedupe_html = f'<div class="section"><span class="label">重複確認</span><br>{_escape(item.dedupe_note)}</div>'

    return f"""
    <article class="card {imp}">
      <h2 class="title"><a href="{_escape(item.url)}" target="_blank" rel="noopener">{_escape(item.title)}</a></h2>
      <div class="meta">
        <span class="imp {imp}">{imp}</span>
        <span>{_escape(item.published or '日付不明')} / {_escape(item.source)}</span>
      </div>
      <div class="section"><span class="label">要約</span><br>{_escape(item.summary or item.snippet[:200])}</div>
      <div class="section"><span class="label">AI利用への影響</span><br>{_escape(item.impact or '未分析')}</div>
      {notes_html}
      {dedupe_html}
      <div class="section"><span class="label">根拠URL</span><br>
        <a href="{_escape(item.url)}" target="_blank" rel="noopener" style="word-break:break-all;">{_escape(item.url)}</a>
      </div>
      {aux_html}
      <div class="tags">{tags_html}</div>
    </article>
    """


def _build_overview(items: List[NewsItem]) -> str:
    return build_overview(items)


CREDIT_WARNING_HTML = """
<div class="credit-warning">
  <span class="label">注意</span>
  Claude APIクレジット不足または利用上限により、AI要約を実行できなかった可能性があります。<br>
  このページは簡易版です。<br>
  Anthropic ConsoleのBillingを確認してください。
</div>
"""

API_WARNING_HTML = """
<div class="credit-warning">
  <span class="label">注意</span>
  Claude API要約に失敗しました。<br>
  このページは簡易版です。<br>
  Anthropic ConsoleおよびGitHub Actionsのログを確認してください。
</div>
"""


def render_html(items: List[NewsItem], date_str: str,
                generated_at: datetime,
                credit_warning: bool = False, api_warning: bool = False) -> str:
    overview = _build_overview(items)
    if not items:
        body = '<div class="empty">本日の掲載対象ニュースはありません。</div>'
    else:
        body = "\n".join(_render_card(it) for it in items)

    if credit_warning:
        warning_html = CREDIT_WARNING_HTML
    elif api_warning:
        warning_html = API_WARNING_HTML
    else:
        warning_html = ""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIニュース {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  {warning_html}
  <header>
    <h1>AIニュース まとめ</h1>
    <div class="date">{_escape(date_str)}</div>
  </header>
  <div class="summary-bar">{_escape(overview)}</div>
  {body}
  <footer>generated at {_escape(generated_at.strftime('%Y/%m/%d %H:%M'))} JST</footer>
</div>
</body>
</html>
"""


def write_html(items: List[NewsItem], date: datetime, docs_dir: Path,
               credit_warning: bool = False, api_warning: bool = False) -> Path:
    """日別HTML、index.html、latest.html を生成。日別ファイルパスを返す。"""
    date_str = date.strftime("%Y/%m/%d")
    daily_dir = docs_dir / f"{date.year:04d}" / f"{date.month:02d}"
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_path = daily_dir / f"{date.day:02d}.html"
    html_text = render_html(items, date_str,
                            generated_at=date,
                            credit_warning=credit_warning,
                            api_warning=api_warning)
    daily_path.write_text(html_text, encoding="utf-8")

    # latest.html
    (docs_dir / "latest.html").write_text(html_text, encoding="utf-8")

    # index.html: 過去日付のリンク一覧
    _update_index(docs_dir, date)
    return daily_path


def _update_index(docs_dir: Path, today) -> None:
    entries = []
    for year_dir in sorted(docs_dir.glob("*"), reverse=True):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.glob("*"), reverse=True):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            for day_file in sorted(month_dir.glob("*.html"), reverse=True):
                rel = f"{year_dir.name}/{month_dir.name}/{day_file.name}"
                date_label = f"{year_dir.name}/{month_dir.name}/{day_file.stem}"
                entries.append((rel, date_label))

    entries = entries[:60]
    items_html = "\n".join(
        f'<li><a href="{_escape(rel)}">{_escape(label)}</a></li>'
        for rel, label in entries
    ) or "<li>まだニュースが生成されていない</li>"

    today_str = today.strftime("%Y/%m/%d")
    text = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIニュース 一覧</title>
<style>{CSS}
ul {{ list-style:none; padding:0; }}
li {{ padding:10px 14px; background:#fff; border:1px solid #e5e7eb; border-radius:10px; margin:6px 0; }}
li a {{ color:#1d4ed8; text-decoration:none; }}
@media (prefers-color-scheme: dark) {{ li {{ background:#1d2026; border-color:#2a2e36; }} li a {{ color:#6cb4ff; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>AIニュース 一覧</h1>
    <div class="date">最終更新 {_escape(today_str)}</div>
  </header>
  <p><a href="latest.html">最新ニュースを見る</a></p>
  <ul>{items_html}</ul>
</div>
</body>
</html>
"""
    (docs_dir / "index.html").write_text(text, encoding="utf-8")
