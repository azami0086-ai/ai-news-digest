"""設定読み込み。環境変数とコード内デフォルトをまとめる。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class OfficialSource:
    name: str
    kind: str  # "rss" or "html"
    url: str
    category: str  # 主要分類タグ


# RSSがある場合はRSSを使う。ないものはhtmlで取得。
OFFICIAL_SOURCES: List[OfficialSource] = [
    # OpenAI / ChatGPT
    OfficialSource("OpenAI Blog", "rss", "https://openai.com/blog/rss.xml", "ChatGPT"),
    # Anthropic / Claude / Claude Code
    OfficialSource("Anthropic News", "html", "https://www.anthropic.com/news", "Claude"),
    # Google / Gemini / Workspace / NotebookLM
    OfficialSource("Google The Keyword - AI", "rss", "https://blog.google/technology/ai/rss/", "Gemini"),
    OfficialSource("Google Workspace Updates", "rss", "https://workspaceupdates.googleblog.com/feeds/posts/default", "GoogleWorkspace"),
    OfficialSource("Google DeepMind Blog", "rss", "https://deepmind.google/blog/rss.xml", "Gemini"),
    # Microsoft / Copilot
    OfficialSource("Microsoft AI Blog", "rss", "https://blogs.microsoft.com/ai/feed/", "Copilot"),
    # その他
    OfficialSource("HuggingFace Blog", "rss", "https://huggingface.co/blog/feed.xml", "AIモデル"),
    OfficialSource("Meta AI Blog", "rss", "https://ai.meta.com/blog/rss/", "AIモデル"),
]


HN_KEYWORDS = [
    "Claude", "Claude Code", "ChatGPT", "OpenAI", "GPT", "Gemini",
    "Google Workspace", "NotebookLM", "Copilot", "LLM",
    "AI agent", "Anthropic",
]


ARXIV_KEYWORDS = [
    "LLM", "large language model", "agent", "AI agent", "reasoning",
    "RAG", "multimodal", "code generation", "tool use", "AI safety",
    "evaluation", "benchmark", "enterprise AI",
]


# 優先順位（高いほど上）
PRIORITY_KEYWORDS = [
    ("Claude", 100),
    ("ChatGPT", 90),
    ("Gemini", 80),
    ("Google Workspace", 70),
    ("NotebookLM", 60),
    ("Copilot", 50),
    ("LLM", 40),
    ("AI agent", 30),
]


# Claude API 単価表（USD per 1M tokens）。コスト概算用。
# 必要に応じて更新する。新モデルを使う場合はここに追記。
# 価格改定時はこのテーブルを手動更新する。
MODEL_PRICING = {
    # Haiku 3.5（通常運用の固定ID推奨）
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "claude-3-5-haiku-latest":   {"input": 0.80, "output": 4.00},
    # Haiku 4.5（参考、初期実装では使わない）
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    # Sonnet 4.6（参考、初期実装では使わない。将来A候補のみ回す余地）
    "claude-sonnet-4-6":         {"input": 3.00, "output": 15.00},
}


# 高コストモデル誤指定防止用キーワード
EXPENSIVE_MODEL_KEYWORDS = ("sonnet", "opus")

# 既定モデル。AI_MODEL 環境変数があれば上書きするが、原則は設定不要。
# GitHub Secrets の AI_MODEL は使わない方針（Secretsに登録された値は
# Actions ログで *** に自動マスクされ、何のモデルを使ったか分からなくなるため）。
DEFAULT_AI_MODEL = "claude-haiku-4-5-20251001"


def is_expensive_model(model: str) -> bool:
    """SonnetやOpusなどコストの高いモデルかを判定。"""
    m = (model or "").lower()
    return any(k in m for k in EXPENSIVE_MODEL_KEYWORDS)


def expensive_allowed() -> bool:
    """ALLOW_EXPENSIVE_MODEL=true なら許可。それ以外は不許可。"""
    return (os.environ.get("ALLOW_EXPENSIVE_MODEL", "") or "").strip().lower() == "true"


def _resolve_ai_model() -> str:
    """AI_MODEL 環境変数があれば strip して採用。空または未設定なら DEFAULT_AI_MODEL。"""
    raw = os.environ.get("AI_MODEL")
    if raw is None:
        return DEFAULT_AI_MODEL
    val = raw.strip()
    if not val:
        return DEFAULT_AI_MODEL
    return val


@dataclass
class Settings:
    # 動作モード
    enable_x: bool = False  # X APIは使わない方針。常にFalse。

    # AI
    # モデルは config.DEFAULT_AI_MODEL を既定とし、AI_MODEL 環境変数があれば上書き。
    # AI_MODEL は通常のenv変数として扱う（GitHub Secretsには登録しない）。
    # Sonnet/Opus を使う場合は ALLOW_EXPENSIVE_MODEL=true が必要。
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    ai_model: str = field(default_factory=_resolve_ai_model)

    # サイト
    site_base_url: str = field(default_factory=lambda: os.environ.get("SITE_BASE_URL", ""))

    # メール
    smtp_host: str = field(default_factory=lambda: os.environ.get("MAIL_SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("MAIL_SMTP_PORT", "587") or "587"))
    smtp_user: str = field(default_factory=lambda: os.environ.get("MAIL_SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.environ.get("MAIL_SMTP_PASSWORD", ""))
    mail_from: str = field(default_factory=lambda: os.environ.get("MAIL_FROM", ""))
    mail_to: str = field(default_factory=lambda: os.environ.get("MAIL_TO", ""))

    # フェッチ件数上限
    hn_max_per_keyword: int = 10
    arxiv_max_results: int = 30
    official_max_per_source: int = 15

    # コスト制御: AI解析対象件数と最終掲載件数の上限
    candidate_max: int = 20   # priority_score上位 N件のみAPIに投げる
    publish_max: int = 10     # HTML/Markdown/メールに載せる最大件数

    # 取得対象期間（直近何日以内のニュースを残すか）
    recent_days: int = 3

    # 過去掲載済み判定の参照範囲（logs/*.json の何日分を見るか）
    history_lookback_days: int = 30
    # 再掲載判定のタイトル類似度しきい値（重複統合の0.82より高く、続報は通す）
    history_title_threshold: float = 0.92

    # HTTPタイムアウト
    http_timeout_sec: int = 20


def load_settings() -> Settings:
    return Settings()
