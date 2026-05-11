"""AI要約・影響分析。Claude APIを呼ぶ。失敗時はフォールバック。

コスト制御方針:
- 初期実装は Haiku のみ。Sonnetは使わない。
- 解析対象は priority_score 上位 settings.candidate_max 件まで。
- 各APIコールの usage を集計し、概算コスト(USD)を算出。
- 将来、重要度A候補だけSonnetに回す余地は残してよい（その際はrun_with_modelを差し替え）。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Tuple

from config import (
    GOOGLE_FAVORED_KEYWORDS,
    MODEL_PRICING,
    OFFICIAL_PRIMARY_SOURCES,
    PRACTICAL_IMPACT_KEYWORDS,
    PRIORITY_KEYWORDS,
    Settings,
)
from models import NewsItem


# 30日超でも例外的に残す優先ソース（OpenAI / Anthropic / Google公式）
PRIVILEGED_SOURCES = frozenset([
    "OpenAI Blog",
    "Anthropic News",
    "Google Workspace Updates",
    "Google DeepMind Blog",
    "Google The Keyword - AI",
])

log = logging.getLogger(__name__)


PROMPT_SYSTEM = """あなたはAIニュースの編集アシスタント。
読み手は社内の労務・経理・総務担当。短時間で実務判断できる文面が必要。
AI技術者向けの詳細レポートではない。

重要：
- 事実と推測を分ける
- 根拠URLにないことを断定しない
- 未確認情報は「未確認」と書く
- 長文引用しない
- 日本語で書く

出力は必ず以下のJSONのみ（前後に文章を書かない）：
{
  "title_ja": "日本語の見出し（自然なニュース見出し、内容を盛らない、固有名詞はそのまま）",
  "summary": "何の話？を1文（40〜60字を目安、常体、難しい技術用語を避ける）",
  "impact": "何が変わる？を1文（40〜60字を目安、常体、会社で何を見るべきかを書く）",
  "notes": "注意することを1文（必要時のみ2文、各40〜60字、常体、機密・許可・確認・制限など実務軸）",
  "importance": "A" または "B" または "C" または "除外",
  "tags": ["関連タグ", ...]
}

文章ルール:
- 常体で統一する。「です」「ます」「ください」「お勧めします」は使わない
- 各項目は1文が原則
  - 何の話？: 1文
  - 何が変わる？: 1文
  - 注意すること: 1文。必要なときだけ2文
- 1文は40〜60字を目安にする。80字超えは避ける
- 難しい技術用語を避ける
- 固有名詞は残す（OpenAI、Codex、Claude、ChatGPT、Gemini、Google Workspace など）
- 抽象語を減らし「会社で何を見るべきか」を書く
- 大げさにしない
- 不明なことを断定しない
- 実務判断に不要な詳細は削る

避ける表現:
- 実現 / 準拠 / テレメトリ / ネットワークポリシー / セキュリティ対策を公開
- エージェント運用 / 企業導入を加速 / 業務効率化に寄与 / 活用が期待される
- 方法論 / 統治体制 / 業務設計 / 品質管理 / 導入フェーズ / 照合
- 信頼度は高い / 可能性があります / 確認してください / お勧めします

言い換え:
- 方法論 → 考え方
- 統治体制 → ルールや責任者
- 業務設計 → 業務での使い方
- 品質管理 → 出力チェック
- 導入フェーズと照合 → 自社の状況と比べる
- 信頼度は高い → 公式資料として扱える
- 確認してください → 確認する
- 可能性があります → 可能性がある
- お勧めします → 〜するとよい / 〜する

推奨する表現:
- 説明した / 使えるようにした / 注意が必要 / 制限する / 確認する
- 読ませない / 許可制にする / 会社で使う前に確認する
- ルールや責任者を決める / 自社の状況と比べる / 公式資料として読める

文体イメージ:
悪い例: 「OpenAIが企業向けにAI導入を大規模化する際の方法論を公開。信頼・統治体制・業務設計・品質管理が軸。」
良い例: 「OpenAIが、企業でAI利用を広げる時の考え方を説明した。」

悪い例: 「会社でAI導入を進める際、信頼構築とルール作りが重要とあらためて確認。自社の導入フェーズと照合して見直す材料になる。」
良い例: 「AI導入を広げる前に、利用ルールと責任者を決める必要がある。」

悪い例: 「実際の取り組み内容はガイド資料を確認が必要。OpenAI公式提供なので信頼度は高い。」
良い例: 「公式資料として読めるが、自社で使う場合は権限・保存先・責任範囲を確認する。」

title_ja のルール:
- 直訳しすぎず、日本語ニュース見出しとして自然に
- 内容を盛らない
- 固有名詞は原則そのまま残す（Codex、OpenAI、Gemini、Claude、ChatGPT、Google Workspace など）
- 公式訳ではなく「表示用の和訳見出し」

重要度判定:
- A: 今日または近日中にAIの使い方・導入判断・業務利用ルールに影響
- B: 今後のAI活用方針に影響
- C: 知識として把握しておけばよい
- 除外: AI利用への影響が薄い、株価・人事・噂のみ、根拠URL不明確

優先順位の高いトピック: Claude > ChatGPT > Gemini > Google Workspace > NotebookLM > その他AIモデル > AI論文
"""


def _age_days(item: NewsItem) -> int:
    """記事の経過日数。published が無い場合は 9999（古い扱いだが除外しない判断に使う）。"""
    if not item.published:
        return 9999
    try:
        d = datetime.strptime(item.published, "%Y/%m/%d")
        return max(0, (datetime.now() - d).days)
    except Exception:
        return 9999


def _freshness_boost(item: NewsItem) -> int:
    """新しいほどボーナス。30日超は減点（特権ソースは緩和）。

    - 7日以内: +30 〜 +50
    - 8〜30日: +5 〜 +25
    - 30日超: 特権ソースは -10、それ以外は -200（実質除外）
    - published 不明: 0
    """
    if not item.published:
        return 0
    age = _age_days(item)
    if age <= 7:
        return 50 - age * 3        # 0日=+50, 7日=+29
    if age <= 30:
        return 25 - (age - 7)      # 8日=+24, 30日=+2
    if item.source in PRIVILEGED_SOURCES:
        return -10
    return -200


def is_too_old(item: NewsItem) -> bool:
    """30日超で特権ソースでもないものは除外対象。"""
    return _age_days(item) > 30 and item.source not in PRIVILEGED_SOURCES


def _priority_score(item: NewsItem) -> int:
    text = f"{item.title} {item.snippet} {item.category}".lower()
    score = 0
    for kw, val in PRIORITY_KEYWORDS:
        if kw.lower() in text:
            score = max(score, val)
    if item.source_type == "official":
        score += 5
    # 公式 primary はさらに加点（公式の中でも最重要ベンダー）
    if item.source in OFFICIAL_PRIMARY_SOURCES:
        score += 20
    if item.source_type == "arxiv":
        score = max(score, 10)

    # Google / Gemini / Workspace 系の語を含む記事に +15 ずつ加点
    favored_hits = sum(1 for kw in GOOGLE_FAVORED_KEYWORDS if kw in text)
    score += favored_hits * 15

    # 実務影響ワードに +10 ずつ加点
    impact_hits = sum(1 for kw in PRACTICAL_IMPACT_KEYWORDS if kw in text)
    score += impact_hits * 10

    score += _freshness_boost(item)
    return score


def _fallback_analyze(item: NewsItem) -> NewsItem:
    """AI APIが使えない場合のフォールバック。"""
    item.title_ja = item.title_ja or item.title
    item.summary = (item.snippet[:150] or item.title)[:150]
    item.impact = "未分析。会社での使い方は手動で確認する。"
    # 単純なヒューリスティック
    text = f"{item.title} {item.snippet}".lower()
    if any(k in text for k in ["claude", "chatgpt", "gemini", "notebooklm", "workspace"]):
        item.importance = "B"
    elif item.source_type == "arxiv":
        item.importance = "C"
    else:
        item.importance = "C"
    item.tags = [item.category] if item.category else []
    item.notes = "AI解析未実施"
    return item


def _extract_json(text: str) -> dict:
    """応答からJSON部分を抽出。"""
    text = text.strip()
    # 前後にコードブロックが付く場合がある
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("no JSON found in response")
    return json.loads(m.group(0))


def _build_user_prompt(item: NewsItem) -> str:
    return (
        f"タイトル: {item.title}\n"
        f"出所: {item.source} ({item.source_type})\n"
        f"公開日: {item.published or '不明'}\n"
        f"URL: {item.url}\n"
        f"カテゴリ: {item.category or '不明'}\n"
        f"抜粋: {item.snippet[:800]}\n"
    )


def analyze_one(client, model: str, item: NewsItem) -> Tuple[NewsItem, int, int]:
    """1件解析。戻り値: (item, input_tokens, output_tokens)。"""
    user_prompt = _build_user_prompt(item)
    resp = client.messages.create(
        model=model,
        max_tokens=600,
        system=PROMPT_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = ""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            text += block.text
    data = _extract_json(text)
    item.title_ja = (data.get("title_ja") or "").strip()
    item.summary = (data.get("summary") or "").strip()
    item.impact = (data.get("impact") or "").strip()
    importance = (data.get("importance") or "").strip()
    if importance not in ("A", "B", "C", "除外"):
        importance = "C"
    item.importance = importance
    raw_tags = data.get("tags") or []
    if isinstance(raw_tags, list):
        item.tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    item.notes = (data.get("notes") or "").strip()

    usage = getattr(resp, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    return item, in_tok, out_tok


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """単価表からUSD概算。未登録モデルは0を返す（実コストはAPIダッシュボードで確認）。"""
    p = MODEL_PRICING.get(model)
    if not p:
        return 0.0
    return (input_tokens / 1_000_000.0) * p["input"] + (output_tokens / 1_000_000.0) * p["output"]


def classify_api_error(exc: Exception) -> Tuple[str, bool]:
    """例外メッセージから api_error_type と suspected_credit_issue を推定。

    戻り値: (api_error_type, suspected_credit_issue)
      api_error_type は以下のいずれか:
        credit_exhausted / payment_required / usage_limit /
        rate_limit / auth_error / unknown_api_error
    """
    msg = (str(exc) or "").lower()

    # 課金・残高系（クレジット不足の疑い）
    if any(k in msg for k in ("credit", "credits", "insufficient", "balance")):
        return "credit_exhausted", True
    if any(k in msg for k in ("payment required", "payment_required", "402")):
        return "payment_required", True
    if "billing" in msg:
        return "credit_exhausted", True
    if any(k in msg for k in ("spend limit", "spend_limit", "usage limit", "usage_limit", "quota")):
        return "usage_limit", True

    # レート制限（課金疑いではない）
    if any(k in msg for k in ("rate limit", "rate_limit", "rate-limit", "429", "too many requests")):
        return "rate_limit", False

    # 認証
    if any(k in msg for k in ("unauthorized", "401", "invalid api key", "invalid_api_key", "authentication")):
        return "auth_error", False

    # 汎用 limit 文字列は課金疑いに倒す（誤検知よりも見落とし回避を優先）
    if "limit" in msg:
        return "usage_limit", True

    return "unknown_api_error", False


def _new_usage() -> Dict[str, object]:
    return {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "model": "",
        "fallback_used": False,
        "api_error": False,
        "api_error_type": "",
        "api_error_message": "",  # 生メッセージ。main.py側でsanitizeする
        "suspected_credit_issue": False,
    }


def _record_api_error(usage: Dict[str, object], exc: Exception) -> None:
    """例外をusageに記録。課金系を優先して上書きする。"""
    err_type, suspected = classify_api_error(exc)
    usage["api_error"] = True
    # まだ課金系を記録していなければ更新
    if suspected and not usage["suspected_credit_issue"]:
        usage["suspected_credit_issue"] = True
        usage["api_error_type"] = err_type
        usage["api_error_message"] = str(exc)
    elif not usage["api_error_type"]:
        usage["api_error_type"] = err_type
        usage["api_error_message"] = str(exc)


def analyze_items(
    items: List[NewsItem], settings: Settings, errors: list
) -> Tuple[List[NewsItem], Dict[str, object]]:
    """各ニュースをAIで要約・分析。失敗時はフォールバック。

    戻り値: (解析結果リスト, usage_dict)
    """
    # 優先度スコアを付与してソート、上位 candidate_max 件のみAPIに投げる
    for it in items:
        it.priority_score = _priority_score(it)
    items.sort(key=lambda x: x.priority_score, reverse=True)
    candidates = items[: settings.candidate_max]
    log.info("analyze candidates: %d / %d (cap=%d)",
             len(candidates), len(items), settings.candidate_max)

    usage_total = _new_usage()
    usage_total["model"] = settings.ai_model

    if not settings.anthropic_api_key:
        msg = "ANTHROPIC_API_KEY が未設定のためフォールバック解析"
        log.warning(msg)
        errors.append(msg)
        usage_total["api_error"] = True
        usage_total["api_error_type"] = "auth_error"
        usage_total["api_error_message"] = msg
        usage_total["fallback_used"] = True
        return [_fallback_analyze(it) for it in candidates], usage_total

    try:
        from anthropic import Anthropic
    except Exception as e:
        msg = f"anthropic SDK 読み込み失敗: {e}"
        log.warning(msg)
        errors.append(msg)
        _record_api_error(usage_total, e)
        usage_total["fallback_used"] = True
        return [_fallback_analyze(it) for it in candidates], usage_total

    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
    except Exception as e:
        msg = f"anthropic Client 初期化失敗: {e}"
        log.warning(msg)
        errors.append(msg)
        _record_api_error(usage_total, e)
        usage_total["fallback_used"] = True
        return [_fallback_analyze(it) for it in candidates], usage_total

    out: List[NewsItem] = []
    fallback_count = 0
    for it in candidates:
        try:
            analyzed, in_tok, out_tok = analyze_one(client, settings.ai_model, it)
            out.append(analyzed)
            usage_total["calls"] += 1
            usage_total["input_tokens"] += in_tok
            usage_total["output_tokens"] += out_tok
        except Exception as e:
            msg = f"analyze failed for {it.title!r}: {e}"
            log.warning(msg)
            errors.append(msg)
            _record_api_error(usage_total, e)
            out.append(_fallback_analyze(it))
            fallback_count += 1

    usage_total["fallback_used"] = fallback_count > 0
    usage_total["estimated_cost_usd"] = round(
        estimate_cost_usd(
            settings.ai_model,
            int(usage_total["input_tokens"]),
            int(usage_total["output_tokens"]),
        ),
        6,
    )
    log.info("ai usage: model=%s calls=%d in=%d out=%d cost~$%.4f fallback=%d api_error=%s suspected_credit=%s",
             usage_total["model"], usage_total["calls"],
             usage_total["input_tokens"], usage_total["output_tokens"],
             usage_total["estimated_cost_usd"], fallback_count,
             usage_total["api_error"], usage_total["suspected_credit_issue"])
    return out, usage_total


def filter_excluded(items: List[NewsItem]) -> List[NewsItem]:
    """重要度=除外を取り除く。"""
    return [it for it in items if it.importance != "除外"]
