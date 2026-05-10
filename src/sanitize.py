"""Secretsマスク。logs/メール本文に値が混入しないよう共通化する。

logs/*.json は GitHub にコミットされるため、SMTP例外メッセージ等にメールアドレスや
パスワードが含まれた場合に備え、書き出し前に必ずこのモジュールを通す。
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from config import Settings


# 汎用パターン
_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_.\-]+", re.IGNORECASE),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API key風
)


def _redact_patterns(text: str) -> str:
    out = text
    for pat in _PATTERNS:
        out = pat.sub("***", out)
    return out


def collect_secret_values(settings: Optional[Settings]) -> List[str]:
    """Settingsから既知のSecret値を収集。空文字は除外。"""
    if settings is None:
        return []
    candidates = [
        settings.anthropic_api_key,
        settings.smtp_password,
        settings.smtp_user,
        settings.mail_from,
        settings.mail_to,
        settings.smtp_host,
    ]
    # 4文字未満の値は誤検知が多いので除外
    return [c for c in candidates if c and len(c) >= 4]


def sanitize_text(text: str, secrets: Iterable[str]) -> str:
    """既知のSecret値と汎用パターンの両方を ‘***’ に置換。"""
    if not text:
        return text or ""
    out = text
    for s in secrets:
        if not s:
            continue
        out = out.replace(s, "***")
    out = _redact_patterns(out)
    return out


def sanitize_list(items: Iterable[str], secrets: Iterable[str]) -> List[str]:
    return [sanitize_text(s, secrets) for s in items]
