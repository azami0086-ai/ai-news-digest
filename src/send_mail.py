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
from overview import build_overview

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


def _build_body(items: List[NewsItem], page_url: str, date_str: str,
                errors: List[str],
                credit_warning: bool = False, api_warning: bool = False) -> str:
    a_count = sum(1 for it in items if it.importance == "A")
    overview = build_overview(items)

    lines = []
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
    lines.append(overview)
    lines.append("")
    lines.append(f"掲載件数: {len(items)}")
    lines.append(f"重要度A: {a_count}")

    # エラー詳細はメール本文に出さない。失敗ソース名だけの短文サマリーに。
    err_summary = _summarize_errors_for_email(errors)
    if err_summary:
        lines.append("")
        lines.append(f"※{err_summary}")

    return "\n".join(lines)


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
    body = _build_body(items, page_url, date_str, errors,
                       credit_warning=credit_warning, api_warning=api_warning)

    mime = MIMEMultipart("alternative")
    mime["Subject"] = subject
    mime["From"] = settings.mail_from
    mime["To"] = settings.mail_to
    mime.attach(MIMEText(body, "plain", "utf-8"))

    # HTML版本文（URLは本文中の「HTML:」直下に一度だけクリック可能に表示する）
    escaped_body = _escape(body).replace(chr(10), "<br>")
    if page_url:
        escaped_url = _escape(page_url)
        escaped_body = escaped_body.replace(
            escaped_url,
            f'<a href="{escaped_url}">{escaped_url}</a>',
            1,
        )
    html_body = f"<html><body><p>{escaped_body}</p></body></html>"
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
