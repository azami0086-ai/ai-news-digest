"""SMTPメール送信。シークレットはログ・例外メッセージに出さない。

メール本文は読者向けに簡潔化:
- arXiv API URL等の長いURLは本文に出さない（logs/*.jsonには残す）
- エラー詳細はメール本文に出さず、失敗ソース名だけの短文サマリーに置き換える
- HTML URLは SITE_BASE_URL（既定値あり）に基づき、当日HTMLまたはlatestへ
"""
from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from config import Settings
from models import NewsItem
from overview import build_overview_facts

log = logging.getLogger(__name__)


CREDIT_WARNING_LINES = [
    "注意：",
    "Claude APIクレジット不足または利用上限により、AI要約が実行できなかった可能性があります。",
    "Anthropic ConsoleのBillingを確認してください。",
    "このメールのニュース本文は簡易版です。",
]


def _summarize_errors_for_email(errors: List[str]) -> str:
    """エラーをメール本文向けに短文サマリーに整形。

    - 長いURLは含めない
    - 失敗ソース名だけを抽出
    - 抽出できない場合は汎用文面
    """
    if not errors:
        return ""

    sources: List[str] = []
    seen = set()
    for e in errors:
        lower = e.lower()
        name = None
        # 「official fetch failed: <name>:」を最優先で拾う
        if "official fetch failed:" in lower:
            m = re.search(r"official fetch failed:\s*([^:]+):", e, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
        elif "arxiv" in lower:
            name = "arXiv"
        elif "hn fetch" in lower or "hacker news" in lower:
            name = "Hacker News"
        elif "send_mail" in lower or "smtp" in lower:
            name = "メール送信"
        elif "html generation" in lower:
            name = "HTML生成"
        elif "markdown generation" in lower:
            name = "Markdown生成"
        elif "anthropic" in lower or "analyze" in lower:
            name = "AI解析"
        if name and name not in seen:
            seen.add(name)
            sources.append(name)

    if not sources:
        return "一部処理でエラーが発生しました。詳細はログを確認してください。"
    if len(sources) == 1:
        return f"{sources[0]} の取得に一時失敗しました。詳細はログを確認してください。"
    return f"{'、'.join(sources[:3])} の取得に一時失敗しました。詳細はログを確認してください。"

API_WARNING_LINES = [
    "注意：",
    "Claude API要約に失敗しました。",
    "Anthropic ConsoleおよびGitHub Actionsのログを確認してください。",
    "このメールのニュース本文は簡易版です。",
]


def _build_subject(date_str: str, credit_warning: bool = False, api_warning: bool = False) -> str:
    if credit_warning:
        return f"【AIニュース・要確認】{date_str} Claude APIクレジット不足の可能性"
    if api_warning:
        return f"【AIニュース・要確認】{date_str} Claude API要約失敗"
    return f"【AIニュース】{date_str} まとめ"


# メール本文の「主なトピック」用 表示名マップ（キーは lowercase）。
# 既存タグ表記がばらついても読みやすい表記に揃える。未登録のタグは元の文字列をそのまま使う。
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


def _display_topic(tag: str) -> str:
    if not tag:
        return tag
    return TOPIC_DISPLAY_NAMES.get(tag.strip().lower(), tag)


def _display_topics(tags: List[str]) -> List[str]:
    """表示名へ変換した上で、順序を保ったまま重複除去。"""
    return list(dict.fromkeys(_display_topic(t) for t in tags if t))


def _format_overview_publish_line(facts: dict) -> str:
    """掲載件数行の文字列を生成。バケットの個別件数 + 合計を併記。"""
    bucket_part = " / ".join(f"{label} {n} 件" for label, n in facts["buckets"])
    if bucket_part:
        return f"掲載件数: {bucket_part} / 合計 {facts['total']} 件"
    return f"掲載件数: 合計 {facts['total']} 件"


def _build_overview_bullets(facts: dict) -> List[str]:
    """plain text 用の箇条書き行群（'- xxx' 形式、先頭に「概要:」ヘッダ）。"""
    topics = _display_topics(facts["topics"])
    topics_str = "、".join(topics) if topics else "なし"
    impacts_str = "、".join(facts["impacts"]) if facts["impacts"] else "なし"
    return [
        "概要:",
        f"- {_format_overview_publish_line(facts)}",
        f"- 主なトピック: {topics_str}",
        f"- 実務影響: {impacts_str}",
        f"- 重要度A: {facts['a_count']} 件",
    ]


def _build_overview_html(facts: dict) -> str:
    """HTML 用の概要セクション（<p>概要:</p><ul><li>...</li></ul>）。"""
    topics = _display_topics(facts["topics"])
    topics_str = "、".join(topics) if topics else "なし"
    impacts_str = "、".join(facts["impacts"]) if facts["impacts"] else "なし"
    items_html = "".join([
        f"<li>{_escape(_format_overview_publish_line(facts))}</li>",
        f"<li>主なトピック: {_escape(topics_str)}</li>",
        f"<li>実務影響: {_escape(impacts_str)}</li>",
        f"<li>重要度A: {facts['a_count']} 件</li>",
    ])
    return f"<p>概要:</p><ul>{items_html}</ul>"


def _build_body(items: List[NewsItem], page_url: str, date_str: str,
                errors: List[str],
                credit_warning: bool = False, api_warning: bool = False) -> tuple[str, str]:
    """plain text と HTML のメール本文を構築して返す。"""
    facts = build_overview_facts(items)
    bullets = _build_overview_bullets(facts)
    overview_html = _build_overview_html(facts)
    err_summary = _summarize_errors_for_email(errors)

    # --- plain text ---
    lines: List[str] = []
    if credit_warning:
        lines.extend(CREDIT_WARNING_LINES)
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
    elif api_warning:
        lines.extend(API_WARNING_LINES)
        lines.append("")
        lines.append("-" * 40)
        lines.append("")

    lines.append(f"AIニュース {date_str} まとめ")
    lines.append("")
    # page_url は常に有効（SITE_BASE_URL に既定値があるため）
    if page_url:
        lines.append("HTML:")
        lines.append(page_url)
        lines.append("")
    lines.extend(bullets)

    # エラー詳細はメール本文に出さない。失敗ソース名だけの短文サマリーに。
    if err_summary:
        lines.append("")
        lines.append(f"※{err_summary}")

    plain_body = "\n".join(lines)

    # --- HTML body ---
    parts: List[str] = ["<html><body>"]
    if credit_warning:
        parts.append(
            '<p style="color:#d92d20;font-weight:600;">'
            + "<br>".join(_escape(l) for l in CREDIT_WARNING_LINES)
            + "</p><hr>"
        )
    elif api_warning:
        parts.append(
            '<p style="color:#d92d20;font-weight:600;">'
            + "<br>".join(_escape(l) for l in API_WARNING_LINES)
            + "</p><hr>"
        )

    parts.append(f"<p>{_escape(f'AIニュース {date_str} まとめ')}</p>")
    if page_url:
        esc_url = _escape(page_url)
        parts.append(f'<p>HTML:<br><a href="{esc_url}">{esc_url}</a></p>')
    parts.append(overview_html)
    if err_summary:
        parts.append(f"<p>※{_escape(err_summary)}</p>")
    parts.append("</body></html>")
    html_body = "".join(parts)

    return plain_body, html_body


def _mask_secrets(text: str) -> str:
    """念のためAPIキーらしき長い英数字列をマスク。"""
    import re
    text = re.sub(r"sk-[A-Za-z0-9_-]{10,}", "sk-***", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9_.-]+", "Bearer ***", text)
    return text


def send_mail(items: List[NewsItem], page_url: str, date_str: str,
              settings: Settings, errors: List[str],
              credit_warning: bool = False, api_warning: bool = False) -> str:
    if not settings.smtp_host or not settings.mail_to or not settings.mail_from:
        msg = "SMTP設定が不足。送信スキップ"
        log.warning(msg)
        return msg

    subject = _build_subject(date_str, credit_warning=credit_warning, api_warning=api_warning)
    plain_body, html_body = _build_body(
        items, page_url, date_str, errors,
        credit_warning=credit_warning, api_warning=api_warning,
    )

    mime = MIMEMultipart("alternative")
    mime["Subject"] = subject
    mime["From"] = settings.mail_from
    mime["To"] = settings.mail_to
    mime.attach(MIMEText(plain_body, "plain", "utf-8"))
    mime.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if settings.smtp_port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                  timeout=settings.http_timeout_sec, context=context) as s:
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(mime)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                              timeout=settings.http_timeout_sec) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                except Exception:
                    pass
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(mime)
        return "ok"
    except Exception as e:
        # 例外メッセージにシークレットが入る可能性があるためマスク
        safe = _mask_secrets(str(e))
        log.warning("send_mail failed: %s", safe)
        return f"failed: {safe[:200]}"


def _escape(s: str) -> str:
    import html
    return html.escape(s or "", quote=True)
