# ai-news-digest

AI利用者向けの最新ニュースを毎日自動で収集・要約・公開・通知するシステム。

## 1. システム概要

- 毎日 18:10 JST（GitHub Actions cron `10 9 * * *`）に実行
- 公式情報・Hacker News・arXiv からニュースを取得
- 重複排除し、過去掲載済みニュースを除外
- Claude API で要約と「AI利用への影響」を分析
- スマホ向けレスポンシブ HTML を `docs/` に出力
- **GitHub Actions が `docs/` をアーティファクトとして GitHub Pages にデプロイ**
- Obsidian 用 Markdown を `output/` に出力
- 実行ログを `logs/YYYY-MM-DD.json` に保存
- 設定したメールアドレスに HTML URL と概要を送信

開発・修正は Claude Code が担当。本番実行は GitHub Actions のみ。

## 2. 何を収集するか

「AIを使用する人・会社・業務に影響があるニュース」に限定。

- 最新AIモデル / AIサービスのリリース・機能変更・サービス終了
- 料金・プラン変更、セキュリティ・利用制限
- AI関連の重要論文
- Claude Code、ChatGPT、Gemini、Google Workspace、NotebookLM の利用に影響する情報

優先順位: Claude > ChatGPT > Gemini > Google Workspace > NotebookLM > その他AIモデル > AI論文 > その他。

## 3. 何を収集しないか

- AI企業の株価・決算・人事のみのニュース
- 利用者影響の薄い買収・提携
- 一次情報のない噂
- 広告色の強い記事
- 根拠URL不明確な記事
- **X（旧Twitter）の API は使用しない**（`X_BEARER_TOKEN` 等は不要）
- **会社データ・Google Drive・Gmail・Slack・社内ファイル等への連携は一切持たない**

## 4. GitHub Actions

`.github/workflows/daily.yml` 参照。

- スケジュール: `10 9 * * *`（UTC、= 18:10 JST）
- 手動実行: `workflow_dispatch` で可能（Actions 画面の "Run workflow"）
- 権限:
  ```
  permissions:
    contents: write   # output / logs のコミット
    pages: write      # GitHub Pagesデプロイ
    id-token: write   # OIDC認証
  ```
- concurrency: `pages` グループでデプロイ衝突を防止
- 実行内容:
  1. Python 3.11 セットアップ
  2. `pip install -r requirements.txt`
  3. `python src/main.py` 実行（HTML / Markdown / JSONログ生成）
  4. `actions/configure-pages` → `actions/upload-pages-artifact`（`docs/`）→ `actions/deploy-pages` で公開
  5. `output/` と `logs/` の差分を自動コミット（失敗してもPagesデプロイは継続）

注意: GitHub Actions の `schedule` は厳密に時刻通りには起動しない。多少の遅延は許容する。

## 5. GitHub Pages の設定方法

リポジトリの Settings → Pages で以下を設定する。

- **Source: GitHub Actions**

ブランチ公開（`Deploy from a branch`）は使わない。GitHub Actions が直接アーティファクトを Pages にデプロイする方式に統一している。

これで以下が公開される。

- `https://<user>.github.io/<repo>/` → `docs/index.html`（過去ログ一覧）
- `https://<user>.github.io/<repo>/latest.html` → 最新ニュース
- `https://<user>.github.io/<repo>/YYYY/MM/DD.html` → 日別ニュース

## 6. GitHub Secrets の設定項目

リポジトリの Settings → Secrets and variables → Actions で設定する。

| 名前 | 必須 | 説明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 必須 | Claude API キー |
| `MAIL_SMTP_HOST` | 必須 | SMTP サーバー（例: `smtp.gmail.com`） |
| `MAIL_SMTP_PORT` | 必須 | SMTP ポート（587 / 465） |
| `MAIL_SMTP_USER` | 必須 | SMTP ユーザー名 |
| `MAIL_SMTP_PASSWORD` | 必須 | SMTP パスワード（Gmail はアプリパスワード） |
| `MAIL_FROM` | 必須 | 送信元メールアドレス |
| `MAIL_TO` | 必須 | 通知先メールアドレス |
| `SITE_BASE_URL` | 任意 | GitHub Pages のベースURL。メール本文のリンクに使う |
| `ALLOW_EXPENSIVE_MODEL` | 任意 | `true` のときのみ Sonnet/Opus を使用可能。それ以外は実行停止 |

`X_BEARER_TOKEN` は **使わない**。設定しないこと。

### `AI_MODEL` の取り扱い

- **原則設定不要**。既定値は `src/config.py` の `DEFAULT_AI_MODEL = "claude-haiku-4-5-20251001"`
- **GitHub Secrets には登録しない**。Secrets に登録すると Actions ログで `***` に自動マスクされ、何のモデルを使ったか判別できなくなる
- 変更したい場合のみ `.github/workflows/daily.yml` の `env` に **通常の環境変数** として記述する
- 値はモデルID **そのもの** だけを書く。ダブルクォート / シングルクォート / 全角スペース / 改行 / タブ / バッククォートを含む場合は起動時に `InvalidAIModelError` で停止する
- `claude-3-5-haiku-latest` のような **latest 系 alias は使わない**（将来挙動が変わる可能性のため）
- 当面の許可モデルID:
  - `claude-haiku-4-5-20251001`（既定）
  - `claude-3-5-haiku-20241022`
- 許可リストに無い値を指定した場合は次のような明確なエラーを出して停止する:

  ```
  ERROR: Invalid AI_MODEL. Use claude-haiku-4-5-20251001 or unset AI_MODEL.
  ```

- `anthropic.NotFoundError: 404 not_found_error` がランタイムで出た場合は **モデルID不正（モデル廃止・タイポ・存在しないID）の可能性が高い**。許可リストのIDに戻すか `AI_MODEL` を未設定にする

## 7. 手動実行方法

- GitHub Actions タブ → `daily-ai-news` → "Run workflow" を押す
- ローカル実行する場合（Windows PowerShell の例）：

```powershell
$env:ANTHROPIC_API_KEY = "..."
$env:MAIL_SMTP_HOST = "..."
# ... 他のSecrets相当を環境変数に設定
$env:PYTHONPATH = "src"
python src/main.py
```

依存インストールは事前に必要：

```
pip install -r requirements.txt
```

## 8. 出力ファイルの説明

- `docs/index.html` … 過去ニュース一覧（Pagesアーティファクト）
- `docs/latest.html` … 最新ニュース
- `docs/YYYY/MM/DD.html` … 日別ニュースHTML
- `output/YYYY-MM-DD_AIニュース.md` … Obsidian保存用Markdown
- `logs/YYYY-MM-DD.json` … 実行ログ（取得件数、A/B/C件数、エラー、メール結果、コスト集計、`published_items_meta`）

ログ JSON は git 管理に残す方針（`.gitignore` で除外しない）。

`published_items_meta` は当日掲載した各ニュースの `url` / `normalized_url` / `title` / `published` / `source` を保存する。次回以降の実行で再掲載防止に使う。

## 9. メール送信設定

- SMTP STARTTLS（587）/ SMTPS（465）の両対応
- 件名: `【AIニュース】yyyy/mm/dd まとめ`
- 本文: HTML URL、冒頭1文まとめ、掲載件数、重要度A件数、エラー概要
- パスワード等の Secrets はログ・本文に出さない（`send_mail._mask_secrets` で念のためマスク）

## 10. X API を使わない方針

- `fetch_x.py` はファイルとして存在するが、`enable_x=False` がデフォルトで何も取得しない
- `main.py` からは呼ばない
- X API ベアラートークン (`X_BEARER_TOKEN`) は使わない
- X 単独の情報を確定ニュースとして掲載しない

## 11. 会社データを扱わない安全ルール

このシステムは公開Web上の AI ニュースだけを扱う。以下は絶対に行わない。

- 会社データ・社内ファイル・給与・労務・経理・社員情報・マイナンバーへのアクセス
- Google Drive / Gmail / Slack 連携
- ローカルPC内の会社関連フォルダの参照
- MCP接続の追加
- 外部ストレージ連携の追加

## 12. コスト制御方針

Claude API残高を浪費しないため、以下の制限をかけている。

- **既定モデル: `claude-haiku-4-5-20251001`（`src/config.py` の `DEFAULT_AI_MODEL`、固定ID）**
  - latest 系は将来中身が変わる可能性があるため、本番・定時実行では固定IDを推奨する
  - `AI_MODEL` 環境変数で上書き可能（通常運用では原則設定不要）
  - `AI_MODEL` は GitHub **Secrets には登録しない**。Secrets 経由の値は Actions ログで `***` にマスクされ、どのモデルを使ったか追跡できなくなるため。変更したい場合は `daily.yml` の `env` に通常の値として記述する
- **Sonnet / Opus 誤指定防止**: `AI_MODEL` に `sonnet` または `opus` が含まれる場合、`ALLOW_EXPENSIVE_MODEL=true` がない限り実行を停止する
  - 停止時はSecrets値を一切表示せず、停止理由を `logs/YYYY-MM-DD.json` の `abort_reason` に記録
  - 初期運用では Haiku 固定を推奨。残高が少ない間は Sonnet/Opus を使わない
- Claude API の **Web search は使用しない**（料金回避）
- ニュース取得は Python 側で行い、Claude API は要約・影響分析にのみ使う
- AI解析対象は priority_score 上位 **20 件まで**（`Settings.candidate_max`）
- 最終掲載は **10 件まで**（`Settings.publish_max`）

JSONログのコスト関連フィールド:

| フィールド | 内容 |
|---|---|
| `ai_model` | 使ったモデル名 |
| `ai_calls` | API呼び出し回数 |
| `input_tokens` | 合計入力トークン |
| `output_tokens` | 合計出力トークン |
| `estimated_cost_usd` | 概算コスト（`config.MODEL_PRICING` から計算） |

注意:
- `estimated_cost_usd` は **概算値**。正確な請求額は Anthropic Console の Billing ページで確認する。
- `MODEL_PRICING` は **手動更新前提**。価格改定があった場合は `src/config.py` のテーブルを更新する。

## 12.1 Claude APIクレジット不足・利用上限時の挙動

Claude APIクレジット不足・利用上限・課金系エラーが発生しても、処理全体は可能な限り継続する。

### 動作

- **継続される処理**: ニュース取得 / 重複排除 / 簡易解析（フォールバック） / HTML生成 / Markdown生成 / JSONログ生成 / メール送信 / Pagesデプロイ
- **GitHub Actions の成否**: AI要約だけが失敗して上記が完走できれば、Actionsは成功扱い
- **失敗扱いになる条件**: HTML/Markdown/JSONログ/メール/Pagesデプロイのいずれかに失敗した場合

### 検知方法

`src/analyze.py` の `classify_api_error()` が例外メッセージから次のいずれかに分類する。

| `api_error_type` | 判定キーワード | `suspected_credit_issue` |
|---|---|---|
| `credit_exhausted` | credit / credits / insufficient / balance / billing | true |
| `payment_required` | payment required / 402 | true |
| `usage_limit` | spend limit / usage limit / quota / その他 limit | true |
| `rate_limit` | rate limit / 429 / too many requests | false |
| `auth_error` | unauthorized / 401 / invalid api key / authentication | false |
| `unknown_api_error` | 上記いずれにも該当しない | false |

### 警告の表示先

警告は2段階で出る。

- **クレジット警告**: `suspected_credit_issue == true`（`credit_exhausted` / `payment_required` / `usage_limit`）
- **一般API警告**: `api_error == true` かつ `suspected_credit_issue == false`（`rate_limit` / `auth_error` / `unknown_api_error`）

| 場所 | クレジット警告 | 一般API警告 |
|---|---|---|
| メール件名 | `【AIニュース・要確認】yyyy/mm/dd Claude APIクレジット不足の可能性` | `【AIニュース・要確認】yyyy/mm/dd Claude API要約失敗` |
| メール本文 | クレジット不足の可能性 / Billing確認 / 簡易版 | API要約失敗 / Anthropic Console と GitHub Actions ログ確認 / 簡易版 |
| HTML 最上部 | 赤枠の警告ボックス（Billing文言） | 赤枠の警告ボックス（Console + Actionsログ文言） |
| Markdown 冒頭 | blockquote 4行（Billing文言） | blockquote 4行（Console + Actionsログ文言） |
| JSONログ | `suspected_credit_issue: true` / `billing_check_required: true` / `api_error_type` / `api_error_message_sanitized` | `api_error: true` / `api_error_type` / `api_error_message_sanitized` |

クレジット警告が優先。両方の条件を満たす場合はクレジット警告のみ出る（重複表示を避ける）。

クレジット警告が出た場合は **Anthropic Console の Billing ページ** を確認する。
一般API警告が出た場合は **Anthropic Console（API設定・利用状況）と GitHub Actions の実行ログ** を確認する。

### コスト概算の注意

- `estimated_cost_usd` は **概算値**。正確な請求額は Anthropic Console で確認する。
- `MODEL_PRICING` の単価は手動更新前提。価格改定があったら `src/config.py` を更新する。

## 13. 過去掲載済みニュースの再掲載防止

毎日実行で同じニュースが翌日以降に再掲載されないよう、以下のフローで除外する。

- 取得期間は直近 3 日
- ただし `logs/*.json`（直近 30 日）の `published_items_meta` を読み、当日候補と照合
- 正規化URL一致 または タイトル類似度 0.92 以上のものは「過去掲載済み」として除外
- 続報や重要な更新は別ニュース（タイトル差分が大きい）として通る
- 除外件数は JSONログの `recorded_duplicate_excluded_count` に記録

`history_lookback_days` と `history_title_threshold` は `src/config.py` で調整可能。

### 状態の永続化

GitHub Actions の実行環境は毎回新しい仮想マシンで起動するため、`logs/*.json` を **リポジトリにコミットして永続化する**。

- 実行終了時に `git add output logs docs` → `git commit` → `git push` を実行（[daily.yml](.github/workflows/daily.yml) の `Commit logs and output` ステップ）
- 次回実行は `actions/checkout@v4` で push 済みの `logs/*.json` を取得し、`history.load_history` が読み込む
- 再掲載防止の状態管理は **`logs/*.json` のみに依存**（GitHub Pages のアーティファクトデプロイには依存しない）
- そのため `permissions` は `contents: write`（コミット用）/ `pages: write`（Pagesデプロイ用）/ `id-token: write`（OIDC用）の3つを設定する
- `Commit logs and output` ステップは `continue-on-error: true`。コミットが失敗しても Pages デプロイは止めない
- `docs/` も合わせてコミットしているが、これは差分追跡用。Pages 公開自体は `actions/upload-pages-artifact` 経由なのでコミット結果に依存しない

### logs/*.json の永続化失敗時の注意

`logs/*.json` は過去掲載済みニュースの再掲載防止に使われる。GitHub Actions の `Commit logs and output` ステップでリポジトリにコミットされる前提だが、以下の理由でコミットが失敗する可能性がある。

- 同時刻の別実行とのプッシュ競合
- ブランチ保護ルールの設定ミス
- リポジトリ容量制限
- ネットワーク一時障害

コミットが失敗すると、次回実行時の再掲載防止が弱くなり、同じニュースが翌日以降に再掲載される可能性がある。

検知方法:
- daily.yml の `Warn on commit failure` ステップが `$GITHUB_STEP_SUMMARY` に「【警告】 logs/*.json の永続化に失敗した可能性があります」を出力する
- Actions の実行結果ページの上部に表示される
- 表示された場合は `Commit logs and output` ステップのログを確認し、競合解消後に `workflow_dispatch` で再実行する

### Secrets が logs に漏れないことの保証

`logs/*.json` は公開リポジトリにコミットされる前提のため、書き出し前に必ず Secrets をマスクする。

- `src/sanitize.py` が以下を行う:
  1. `Settings` から既知の Secret 値（`ANTHROPIC_API_KEY` / `MAIL_SMTP_PASSWORD` / `MAIL_SMTP_USER` / `MAIL_FROM` / `MAIL_TO` / `MAIL_SMTP_HOST`）を集め、ログ文字列内の一致箇所を `***` に置換
  2. `sk-…` / `sk-ant-…` / `Bearer …` / `AIza…` などの汎用パターンも `***` に置換
- `main.py._write_log` が JSONを書き出す直前に `stats.errors` / `stats.abort_reason` / `stats.mail_result` を sanitize
- `published_items_meta` には公開Webニュースの URL / タイトル / 公開日 / 出所 のみ記録され、Secrets は元から含まれない
- メール本文側は従来どおり `send_mail._mask_secrets` でマスク

## 14. トラブルシュート

| 症状 | 対処 |
|---|---|
| メールが来ない | `logs/*.json` の `mail_result` を確認。SMTP Secrets が正しいか確認 |
| HTML が更新されない | Actions のログを確認。0件でも HTML は出力されるはず。Pagesデプロイのログも確認 |
| Pagesが公開されない | Settings → Pages の Source が **GitHub Actions** になっているか確認 |
| Claude API 失敗が多い | `ANTHROPIC_API_KEY` の有効性、`AI_MODEL` の指定を確認。失敗時はフォールバック解析になる |
| 「高コストモデルが指定されているため停止」 | `AI_MODEL` を Haiku 系に戻すか、意図的なら `ALLOW_EXPENSIVE_MODEL=true` を Secrets に追加 |
| 公式RSSが取れない | サイト側のRSS停止やURL変更の可能性。`src/config.py` の `OFFICIAL_SOURCES` を更新 |
| arXivが取れない | API側の遅延。次回実行で復活することが多い |

## 15. 初期設定手順

1. GitHubリポジトリを作成する
2. `ai-news-digest/` を push する
3. Settings → Secrets and variables → Actions で必須Secretsを登録する
4. Settings → Pages で **Source = GitHub Actions** を選ぶ
5. Actionsタブで `daily-ai-news` を手動実行する（`Run workflow`）
6. GitHub Pages の公開URLを確認する（Actions の `deploy` ジョブの出力に表示される）
7. 確認した公開URLを `SITE_BASE_URL` として Secrets に追加する
8. 再度手動実行し、メール本文のURLが正しいか確認する

## 16. 仮定事項（実装上の前提）

実装で置いた合理的仮定。必要に応じてあとで変更してよい。

- AI モデルのデフォルトは `claude-haiku-4-5-20251001`（`src/config.py` の `DEFAULT_AI_MODEL`、固定ID）
- 取得対象期間は直近 3 日
- 重複排除（同一実行内）はタイトル類似度 0.82 以上または正規化URL一致
- 再掲載防止（過去実行との照合）はタイトル類似度 0.92 以上または正規化URL一致、参照範囲 30 日
- HN は Algolia HN Search API を使用（公開API、認証不要）
- 公式情報は基本RSS、無いものは静的HTMLからニュース系リンクを抽出（過度なスクレイピングはしない）
- HTML はインライン CSS のみ、システムのダーク/ライトモードに追従
- メール本文はテキスト＋HTMLの multipart、HTML URL をクリック可能にする
- `logs/*.json` を git にコミットする（履歴と再掲載防止のため）
