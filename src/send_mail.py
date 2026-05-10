"""SMTPメール送信。シークレットはログ・例外メッセージに出さない。"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from config import Settings
from models import NewsItem

log = logging.getLogger(__name__)


CREDIT_WARNING_LINES = [
    "注意：",
    "Claude APIクレジット不足または利用上限により、AI要約が実行できなかった可能性があります。",
    "Anthropic ConsoleのBillingを確認してください。",
    "このメールのニュース本文は簡易版です。",
]

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
    a_items = [it for it in items if it.importance == "A"]
    overview_pool = a_items if a_items else items[:6]
    overview = "本日の主要ニュースは、" + "、".join(
        it.title.split("|")[0].split(":")[0].strip()[:30] for it in overview_pool[:6]
    ) + "。" if items else "本日の掲載対象ニュースはない。"

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
    lines.append(f"HTML: {page_url or '(SITE_BASE_URL未設定)'}")
    lines.append("")
    lines.append(overview)
    lines.append("")
    lines.append(f"掲載件数: {len(items)}")
    lines.append(f"重要度A: {a_count}")
    if errors:
        lines.append("")
        lines.append("エラー概要:")
        for e in errors[:10]:
            # APIキー・パスワードが入る可能性のある文字列はマスク
            safe = _mask_secrets(e)
            lines.append(f"- {safe}")
        if len(errors) > 10:
            lines.append(f"...他 {len(errors) - 10} 件")
    lines.append("")
    lines.append("生成日時: 自動送信")
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

    # HTML版本文（リンクをクリック可能に）
    html_body = (
        "<html><body>"
        f"<p>{_escape(body).replace(chr(10), '<br>')}</p>"
        + (f'<p><a href="{_escape(page_url)}">{_escape(page_url)}</a></p>' if page_url else "")
        + "</body></html>"
    )
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
