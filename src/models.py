"""ニュースアイテムのデータモデル。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class NewsItem:
    """1件のニュース。"""
    title: str             # 原題（英語等）。表示時の Original 表記にも使う
    url: str
    source: str            # 取得元名（例: "OpenAI Blog", "Hacker News", "arXiv"）
    source_type: str       # "official" / "hn" / "arxiv" / "x"
    published: str         # yyyy/mm/dd（取得不能なら "" ）
    snippet: str = ""      # 記事の抜粋・概要
    category: str = ""     # 主要分類タグ（Claude, ChatGPT, ...）

    # 解析後に埋まるフィールド
    title_ja: str = ""             # 表示用の日本語見出し（公式訳ではない）
    summary: str = ""              # 何の話？
    impact: str = ""               # 何が変わる？
    importance: str = ""           # "A" / "B" / "C" / "除外"
    tags: List[str] = field(default_factory=list)
    notes: str = ""                # 注意すること
    dedupe_note: str = ""          # 重複確認結果
    aux_urls: List[str] = field(default_factory=list)  # 補助URL

    # 内部用
    priority_score: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunStats:
    """実行ログ用の集計値。"""
    started_at: str = ""
    finished_at: str = ""
    fetched_per_source: Dict[str, int] = field(default_factory=dict)
    fetched_total: int = 0
    after_dedupe: int = 0
    recorded_duplicate_excluded_count: int = 0  # 過去掲載済みとして除外した件数
    candidate_count: int = 0       # AI解析にかけた件数（candidate_max以下）
    published: int = 0             # 最終掲載件数（publish_max以下）
    count_a: int = 0
    count_b: int = 0
    count_c: int = 0
    count_excluded: int = 0
    errors: List[str] = field(default_factory=list)
    html_path: str = ""
    markdown_path: str = ""
    mail_result: str = ""

    # AI APIコスト集計
    ai_model: str = ""
    ai_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # AI APIエラー状況
    fallback_used: bool = False               # 1件でもフォールバック解析になったか
    api_error: bool = False                   # API呼び出し失敗があったか
    api_error_type: str = ""                  # credit_exhausted / payment_required / usage_limit / rate_limit / auth_error / unknown_api_error / ""
    api_error_message_sanitized: str = ""     # サニタイズ済みエラーメッセージ
    suspected_credit_issue: bool = False      # クレジット不足・課金系エラーの疑い
    billing_check_required: bool = False      # Anthropic Console 確認が必要か

    # 中断理由（高コストモデルガード等）。空なら正常実行。
    abort_reason: str = ""

    # 最終掲載アイテムのメタ（次回以降の再掲載防止に使う）
    # 各要素: 再掲載判定用フィールド (url, normalized_url, title, published, source) +
    # 表示再現用フィールド (title_ja, importance, tags, summary, impact, notes)
    published_items_meta: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
