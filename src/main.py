"""AIニュース自動まとめ メイン処理。

順序:
1. 設定読み込み + 高コストモデルガード
2. 公式情報取得
3. Hacker News取得
4. arXiv取得
5. 取得結果統合
6. 重複排除
7. 過去掲載済みニュースの除外
8. AI要約・影響分析（candidate_max件まで）
9. 重要度=除外 を取り除き、上位 publish_max 件を最終掲載に
10. HTML / Markdown 生成
11. メール送信
12. JSONログ生成（published_items_meta も保存）
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from analyze import analyze_items, filter_excluded, is_too_old
from config import (
    InvalidAIModelError,
    PER_SOURCE_TYPE_LIMITS,
    expensive_allowed,
    is_expensive_model,
    load_settings,
)
from publish_select import diversify_by_source
from dedupe import dedupe
from fetch_arxiv import fetch_arxiv
from fetch_hn import fetch_hn
from fetch_official import fetch_official
from history import build_meta, filter_already_published
from models import RunStats
from render_html import write_html
from render_markdown import write_markdown
from sanitize import collect_secret_values, sanitize_list, sanitize_text
from send_mail import send_mail

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("main")

# プロジェクトルート（src/ の親）
ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
OUTPUT_DIR = ROOT / "output"
LOGS_DIR = ROOT / "logs"


def _jst_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=9)))


def _write_log(stats: RunStats, date_iso: str, settings=None) -> Path:
    """JSONログを書き出す。

    logs/*.json はGitHubにコミットされるため、書き出し前に必ずSecretsを除去する。
    Settings由来の既知シークレット値と、APIキー・Bearer等の汎用パターンを両方マスクする。
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    secrets = collect_secret_values(settings)
    stats.errors = sanitize_list(stats.errors, secrets)
    stats.abort_reason = sanitize_text(stats.abort_reason, secrets)
    stats.mail_result = sanitize_text(stats.mail_result, secrets)

    path = LOGS_DIR / f"{date_iso}.json"
    path.write_text(
        json.dumps(stats.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("log written: %s", path)
    return path


def main() -> int:
    try:
        settings = load_settings()
    except InvalidAIModelError as e:
        # Secrets値は含まれない（モデル名のみ）。stderrへ明確なメッセージを出す。
        log.error("AI_MODEL validation failed: %s", e)
        sys.stderr.write(f"ERROR: {e}\n")
        return 3

    stats = RunStats()
    errors: list = []

    jst = _jst_now()
    stats.started_at = jst.isoformat()
    stats.ai_model = settings.ai_model
    date_str_jp = jst.strftime("%Y/%m/%d")
    date_str_iso = jst.strftime("%Y-%m-%d")

    log.info("=== ai-news-digest start %s ===", date_str_jp)
    # モデル名は GitHub Secrets 経由ではない通常のenv（または DEFAULT_AI_MODEL）。
    # マスクされず素のログに出るので、Actions上で何のモデルを使ったか確認できる。
    log.info("ai_model=%s", settings.ai_model)

    # 1. 高コストモデル誤指定ガード
    if is_expensive_model(settings.ai_model) and not expensive_allowed():
        reason = (
            f"高コストモデルが指定されているため停止: model={settings.ai_model}. "
            f"使用するには ALLOW_EXPENSIVE_MODEL=true を設定する。"
        )
        log.error(reason)
        stats.abort_reason = reason
        stats.errors.append(reason)
        stats.finished_at = _jst_now().isoformat()
        _write_log(stats, date_str_iso, settings)
        return 2

    # 2. 公式
    official = fetch_official(settings, errors)
    stats.fetched_per_source["official"] = len(official)

    # 3. HN
    hn = fetch_hn(settings, errors)
    stats.fetched_per_source["hn"] = len(hn)

    # 4. arXiv
    arxiv = fetch_arxiv(settings, errors)
    stats.fetched_per_source["arxiv"] = len(arxiv)

    # X はスキップ（X APIは使わない）

    # 5. 統合
    all_items = official + hn + arxiv
    stats.fetched_total = len(all_items)
    log.info("total fetched: %d", stats.fetched_total)

    # 6. 重複排除
    deduped = dedupe(all_items)
    stats.after_dedupe = len(deduped)

    # 6.5. 30日超の古い記事を除外（特権ソースは温存）
    before_age = len(deduped)
    deduped = [it for it in deduped if not is_too_old(it)]
    log.info("age filter: %d -> %d (>30d excluded except privileged sources)",
             before_age, len(deduped))

    # 7. 過去掲載済みニュースを除外
    fresh, dup_count = filter_already_published(
        deduped,
        LOGS_DIR,
        settings.history_lookback_days,
        settings.history_title_threshold,
    )
    stats.recorded_duplicate_excluded_count = dup_count
    log.info("history filter: %d -> %d (excluded=%d)", len(deduped), len(fresh), dup_count)

    # 8. AI解析（candidate_max件まで絞ってAPIを叩く）
    analyzed, usage = analyze_items(fresh, settings, errors)
    stats.candidate_count = len(analyzed)
    stats.ai_model = usage.get("model", settings.ai_model)
    stats.ai_calls = int(usage.get("calls", 0))
    stats.input_tokens = int(usage.get("input_tokens", 0))
    stats.output_tokens = int(usage.get("output_tokens", 0))
    stats.estimated_cost_usd = float(usage.get("estimated_cost_usd", 0.0))

    # APIエラー状況。エラーメッセージはサニタイズして格納。
    stats.fallback_used = bool(usage.get("fallback_used", False))
    stats.api_error = bool(usage.get("api_error", False))
    stats.api_error_type = str(usage.get("api_error_type", "") or "")
    stats.suspected_credit_issue = bool(usage.get("suspected_credit_issue", False))
    stats.billing_check_required = stats.suspected_credit_issue
    raw_api_msg = str(usage.get("api_error_message", "") or "")
    stats.api_error_message_sanitized = sanitize_text(
        raw_api_msg, collect_secret_values(settings)
    )

    # 9. 重要度=除外を取り除く
    filtered = filter_excluded(analyzed)

    # 重要度ソート（A → B → C → priority_score）。欠損/不明はC相当。
    rank = {"A": 3, "B": 2, "C": 1}
    def _importance_rank(it):
        return rank.get(it.importance, rank["C"])

    filtered.sort(
        key=lambda x: (_importance_rank(x), x.priority_score),
        reverse=True,
    )

    # 最終掲載は publish_max 件まで。source_type ベースで配分（primary公式優先、HN<=2、arXiv<=1）。
    published_items = diversify_by_source(filtered, settings.publish_max)
    # diversify_by_source はソース種別でバケット化するため、結果順では公式Bが他バケットAより上に来うる。
    # 表示順は重要度を最優先にする。Python の sort は stable なので、同重要度内では選定順が保持される。
    published_items.sort(key=_importance_rank, reverse=True)
    log.info("publish: %d / %d (cap=%d, hn<=%d arxiv<=%d)",
             len(published_items), len(filtered), settings.publish_max,
             PER_SOURCE_TYPE_LIMITS.get("hn", 0),
             PER_SOURCE_TYPE_LIMITS.get("arxiv", 0))

    stats.published = len(published_items)
    stats.count_a = sum(1 for it in published_items if it.importance == "A")
    stats.count_b = sum(1 for it in published_items if it.importance == "B")
    stats.count_c = sum(1 for it in published_items if it.importance == "C")
    stats.count_excluded = len(analyzed) - len(filtered)
    stats.published_items_meta = [build_meta(it) for it in published_items]

    # 警告フラグ。credit を優先、それ以外で api_error があれば一般API警告。
    credit_warning = stats.suspected_credit_issue
    api_warning = stats.api_error and not credit_warning

    # 10. HTML
    try:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        html_path = write_html(
            published_items, jst, DOCS_DIR,
            credit_warning=credit_warning,
            api_warning=api_warning,
        )
        stats.html_path = str(html_path.relative_to(ROOT)).replace("\\", "/")
        log.info("html written: %s", stats.html_path)
    except Exception as e:
        msg = f"html generation failed: {e}"
        log.error(msg)
        errors.append(msg)

    # 10. Markdown
    try:
        md_path = write_markdown(
            published_items, jst, OUTPUT_DIR,
            credit_warning=credit_warning,
            api_warning=api_warning,
        )
        stats.markdown_path = str(md_path.relative_to(ROOT)).replace("\\", "/")
        log.info("markdown written: %s", stats.markdown_path)
    except Exception as e:
        msg = f"markdown generation failed: {e}"
        log.error(msg)
        errors.append(msg)

    # 11. メール送信
    page_url = ""
    if settings.site_base_url:
        rel = f"{jst.year:04d}/{jst.month:02d}/{jst.day:02d}.html"
        page_url = settings.site_base_url.rstrip("/") + "/" + rel
    mail_result = send_mail(
        published_items, page_url, date_str_jp, settings, errors,
        credit_warning=credit_warning,
        api_warning=api_warning,
    )
    stats.mail_result = mail_result
    log.info("mail: %s", mail_result)

    # 12. JSONログ
    stats.errors = errors
    stats.finished_at = _jst_now().isoformat()
    _write_log(stats, date_str_iso, settings)

    log.info("=== ai-news-digest finished ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
