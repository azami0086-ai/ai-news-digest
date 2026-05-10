"""X取得モジュール。

X APIは使わない方針のため、初期実装ではここは無効化されている。
main.pyからは呼ばない。将来的に補助情報枠として使う場合に備えてファイルだけ残す。
X_BEARER_TOKEN等の認証情報は使用しない。
"""
from __future__ import annotations

from typing import List

from config import Settings
from models import NewsItem


def fetch_x(settings: Settings, errors: list) -> List[NewsItem]:
    """初期実装では何も取得しない。X APIは使わない。"""
    if not settings.enable_x:
        return []
    # 安全側の実装方針として、このブランチには到達しない設計にしている。
    # X APIは使わないため、enable_xがTrueでも何もしない。
    errors.append("fetch_x: X取得は無効化されている（X APIは使わない方針）")
    return []
