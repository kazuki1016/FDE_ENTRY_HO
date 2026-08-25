# 定期eval IAM・認証情報移行仕様（spec_scheduled-eval.md）

生成日: 2026-08-21
入力: req_scheduled-eval.md
生成エージェント: spec-writer
位置づけ: spec.md（機能仕様）および spec_infra.md（AWSサーバーレス構成仕様）を前提とした、
定期eval実行ワークフローの認証情報管理方式変更に関する差分仕様。

---

## 0. 本文書の目的と位置づけ

本文書は `.github/workflows/scheduled-eval.yml`（定期eval実行ワークフロー）において、
認証情報（`BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD`・Bedrock APIキー）の取得元を
「GitHub Secretsに直接保存」から「OIDC連携のIAMロール経由でSecrets Manager（`fde-rag/aws-secrets`）から取得」へ移行するための仕様を定義する。

**既存仕様との関係:**

- **spec.md**: 機能仕様（API仕様・データモデル・処理フロー）の正典。本文書はスコープ外。
- **spec_infra.md**: AWSサーバーレス構成仕様。OIDC認証・Secrets Manager管理・最小権限ポリシー等の方針は本文書との整合を保つ。本文書は spec_infra.md 9章（CI/CD）の方針を scheduled-eval.yml に対して適用する差分仕様として位置づける。
- **本文書（spec_scheduled-eval.md）**: scheduled-eval.yml における認証情報移行仕様。機能仕様・インフラ仕様の変更は行わない。

**現状と変更点の概要:**

| 項目 | 変更前（現行実装） | 変更後（本仕様） |
|---|---|---|
| 認証情報の取得元 | GitHub Secrets（`${{ secrets.XXX }}`） | Secrets Manager（`fde-rag/aws-secrets`）から実行時取得 |
| AWS認証手段 | 不在（GitHub Secretsに平文保管） | OIDC連携の専用IAMロールによる AssumeRole |
| AWS_BEARER_TOKEN_BEDROCK | GitHub Secrets | Secrets Manager 経由 |
| BASIC_AUTH_USERNAME | GitHub Secrets | Secrets Manager 経由 |
| BASIC_AUTH_PASSWORD | GitHub Secrets | Secrets Manager 経由 |
| GitHub Secretsの該当値 | 設定済み | IAMロール作成・動作確認後に削除 |
| Slack通知 | なし（eval失敗時のみGitHub UI・デフォルト通知） | eval実行後に合否に関わらず Slack Incoming Webhook へ結果を送信する |

---

## 1. システム概要

`evals/` 配下の正解率評価（`run_eval.py`）と応答時間評価（`run_latency_eval.py`）を
GitHub Actions で毎日 JST 9:00 頃（UTC 00:00）に定期実行する。

本ワークフローは deploy.yml（デプロイ用）・reingest.yml（PDF再ingest用）と並ぶ
3本目のワークフローであり、本番の健全性を日次で監視することを目的とする。

eval実行後は、正解率・レイテンシの評価結果を合否に関わらず Slack Incoming Webhook で通知する（2.5章）。

**再実行との関係:**
- `workflow_dispatch` により手動起動も可能とする（既存実装から継承）。
- deploy.yml への eval 組み込みは行わない（spec_infra.md 9.2章・CLAUDE.md 5.2章の方針を継承。
  毎デプロイでの無制限な課金を避けるため）。

---

## 2. ワークフロー仕様（.github/workflows/scheduled-eval.yml）

### 2.1 トリガー・スケジュール

| 項目 | 値 |
|---|---|
| ファイルパス | `.github/workflows/scheduled-eval.yml`（変更なし） |
| スケジュールトリガー | `cron: "0 0 * * *"`（UTC 00:00 = JST 9:00。GitHub Actions の cron は timezone 指定不可） |
| 手動トリガー | `workflow_dispatch: {}`（変更なし） |
| 実行環境 | `ubuntu-latest`（変更なし） |

### 2.2 実行ステップ

ステップの順序は以下のとおりとする。AWS認証ステップを先頭に追加し、
Secrets Manager 取得ステップを Install dependencies の前に挿入する。

| # | ステップ名 | 変更 | 概要 |
|---|---|---|---|
| 1 | `actions/checkout@v6` | 変更なし | リポジトリをチェックアウト |
| 2 | Configure AWS credentials（OIDC） | **新規追加** | `aws-actions/configure-aws-credentials@v4` で OIDC AssumeRole を実行 |
| 3 | Retrieve secrets from Secrets Manager | **新規追加** | `aws secretsmanager get-secret-value` で認証情報を取得し、マスク処理後に `$GITHUB_ENV` へ書き込む |
| 4 | `actions/setup-python@v6` | 変更なし | Python 3.12 セットアップ |
| 5 | Install dependencies | 変更なし | `pip install -r requirements.txt` |
| 6 | Build ChromaDB | 変更なし（env参照元のみ変更） | `PYTHONPATH=src python -m ingest`。env の `AWS_BEARER_TOKEN_BEDROCK` を `${{ secrets.* }}` から `${{ env.AWS_BEARER_TOKEN_BEDROCK }}`（`$GITHUB_ENV` 経由）に変更する |
| 7 | Run correctness eval | stdout キャプチャ追加 | `run_eval.py`。env の `AWS_BEARER_TOKEN_BEDROCK` 参照元を変更する。Slack通知用に stdout を `tee` で `/tmp/correctness_result.txt` に書き出す（`set -o pipefail` で終了コードを保持する） |
| 8 | Run latency eval | stdout キャプチャ追加 | `run_latency_eval.py`。env の `BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD` 参照元を変更する。Slack通知用に stdout を `tee` で `/tmp/latency_result.txt` に書き出す（`set -o pipefail` で終了コードを保持する） |
| 9 | Notify Slack | **新規追加** | `if: always()` かつ `continue-on-error: true` で実行する。両evalのキャプチャ済み stdout から正解率スコア・レイテンシ統計・合否を読み取り、Slack Incoming Webhook へ通知する（2.5章参照） |
| 10 | Fail if either eval failed | ステップ番号のみ変更（内容変更なし） | いずれかのeval失敗時にワークフロー全体を失敗にする |

### 2.3 AWS OIDC認証（configure-aws-credentials）

```yaml
- name: Configure AWS credentials (OIDC)
  uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: ${{ vars.AWS_SCHEDULED_EVAL_ROLE_ARN }}
    aws-region: ${{ vars.AWS_REGION }}
```

- `permissions` ブロックに `id-token: write`（OIDC トークン発行用）および `contents: read` を付与すること。
- `aws-actions/configure-aws-credentials@v4` は既存の deploy.yml・reingest.yml と同じバージョンを使用する（バージョン統一）。
- `AWS_SCHEDULED_EVAL_ROLE_ARN` は GitHub Variables（Secret ではなく Variable）に登録する（ARN は非機密値。spec_infra.md 9.2章の `AWS_DEPLOY_ROLE_ARN`・`AWS_REINGEST_ROLE_ARN` と同パターン）。

### 2.4 Secrets Manager からの認証情報取得

```yaml
- name: Retrieve secrets from Secrets Manager
  run: |
    SECRET_JSON=$(aws secretsmanager get-secret-value \
      --secret-id fde-rag/aws-secrets \
      --query SecretString \
      --output text)
    BEDROCK_KEY=$(echo "$SECRET_JSON" | python3 -c \
      "import sys,json; print(json.load(sys.stdin)['AWS_BEARER_TOKEN_BEDROCK'])")
    USERNAME=$(echo "$SECRET_JSON" | python3 -c \
      "import sys,json; print(json.load(sys.stdin)['BASIC_AUTH_USERNAME'])")
    PASSWORD=$(echo "$SECRET_JSON" | python3 -c \
      "import sys,json; print(json.load(sys.stdin)['BASIC_AUTH_PASSWORD'])")
    echo "::add-mask::$BEDROCK_KEY"
    echo "::add-mask::$USERNAME"
    echo "::add-mask::$PASSWORD"
    echo "AWS_BEARER_TOKEN_BEDROCK=$BEDROCK_KEY" >> "$GITHUB_ENV"
    echo "BASIC_AUTH_USERNAME=$USERNAME" >> "$GITHUB_ENV"
    echo "BASIC_AUTH_PASSWORD=$PASSWORD" >> "$GITHUB_ENV"
```

**仕様要点:**

| 項目 | 値・説明 |
|---|---|
| シークレットID | `fde-rag/aws-secrets`（既存 Secrets Manager シークレット。Lambda ランタイムでも同一シークレットを使用） |
| 取得する JSON キー | `AWS_BEARER_TOKEN_BEDROCK`・`BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD`（`config.py` の `_SECRET_KEYS` と同一。Secrets Manager 側のキー構造は既存 Lambda 設定から継承） |
| マスク処理 | `echo "::add-mask::$VALUE"` でログへの平文出力を防ぐ。マスク設定は値を `$GITHUB_ENV` に書き込む前に行う |
| 環境変数への書き込み | `$GITHUB_ENV` 経由。以降のステップで `${{ env.XXX }}` または `run` 内のシェル変数として参照可能 |
| `python3` の利用 | JSON パース用。`ubuntu-latest` には Python 3 が標準搭載されているため追加セットアップ不要 |

### 2.5 Slack通知ステップ

#### 設計方針

| 項目 | 採用方針 | 理由 |
|---|---|---|
| 連携方式 | Slack Incoming Webhook（`curl` で POST） | Simplicity First。Slack App 新規作成・Bot Token 方式は不要な複雑さを伴う。Incoming Webhook URL 1本で完結する |
| 通知タイミング | ステップ9（両eval完了後、Fail判定前） | 両evalの結果を集約してから通知する。`if: always()` で eval 失敗時も確実に実行する |
| 失敗時の扱い | `continue-on-error: true` | Slack 通知の失敗（Webhook URL 誤り・ネットワーク障害）でeval合否判定を歪めない。通知失敗はログで確認する |
| Webhook URL の管理 | [推奨デフォルト値（PENDING）] GitHub Secrets に `SLACK_WEBHOOK_URL` として保存 | Incoming Webhook URL は AWS 認証情報ではなく Slack 固有の機密値。CLAUDE.md 6章の「長期的なAWSアクセスキーを保存しない」制約は AWS 認証情報に限定されており、本値には適用されない。GitHub Secrets は非AWS機密値の標準的な保存場所であり、Secrets Manager での管理（AWS認証情報との同居）より Simplicity First に適う（付記 P2 参照） |
| stdout キャプチャ | ステップ7・8 の `run` に `set -o pipefail` と `tee` を追加 | `run_eval.py` の `スコア: X/10 (XX%)` 行・`run_latency_eval.py` の `最小: X.XX秒 / ...` 行・`1問目（コールドスタート想定）: X.XX秒` 行を `grep` で取得し、Slack メッセージに埋め込む |

#### stdout キャプチャの追加（ステップ7・8 の変更箇所）

```yaml
- name: Run correctness eval (run_eval.py)
  id: correctness
  continue-on-error: true
  run: |
    set -o pipefail
    PYTHONPATH=src python evals/run_eval.py 2>&1 | tee /tmp/correctness_result.txt
  env:
    AWS_BEARER_TOKEN_BEDROCK: ${{ env.AWS_BEARER_TOKEN_BEDROCK }}
    AWS_REGION: ${{ vars.AWS_REGION }}

- name: Run latency eval (run_latency_eval.py)
  id: latency
  continue-on-error: true
  run: |
    set -o pipefail
    PYTHONPATH=src python evals/run_latency_eval.py 2>&1 | tee /tmp/latency_result.txt
  env:
    RAG_ENDPOINT_URL: ${{ vars.RAG_ENDPOINT_URL }}
    BASIC_AUTH_USERNAME: ${{ env.BASIC_AUTH_USERNAME }}
    BASIC_AUTH_PASSWORD: ${{ env.BASIC_AUTH_PASSWORD }}
```

**`set -o pipefail` の必要性:** `tee` は常に exit code 0 を返すため、`pipefail` なしでは `run_eval.py` が exit 1 しても `continue-on-error` が正しく機能しない（eval失敗を誤って成功と判定する）。

#### Notify Slack ステップ（新規追加）

```yaml
- name: Notify Slack
  if: always()
  continue-on-error: true
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
    CORRECTNESS_OUTCOME: ${{ steps.correctness.outcome }}
    LATENCY_OUTCOME: ${{ steps.latency.outcome }}
    RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
  run: |
    SCORE_LINE=$(grep -m1 'スコア:' /tmp/correctness_result.txt 2>/dev/null || echo '（取得失敗）')
    LATENCY_SUMMARY=$(grep -m1 '最小:' /tmp/latency_result.txt 2>/dev/null || echo '（取得失敗）')
    COLD_LINE=$(grep -m1 '1問目' /tmp/latency_result.txt 2>/dev/null || echo '（取得失敗）')
    export SCORE_LINE LATENCY_SUMMARY COLD_LINE
    python3 << 'EOF'
import json, os, subprocess, sys
c = os.environ['CORRECTNESS_OUTCOME']
l = os.environ['LATENCY_OUTCOME']
c_icon = ':white_check_mark:' if c == 'success' else ':x:'
l_icon = ':white_check_mark:' if l == 'success' else ':x:'
overall = ':white_check_mark: 全eval合格' if c == 'success' and l == 'success' else ':x: eval失敗あり'
score = os.environ.get('SCORE_LINE', '（取得失敗）')
lat = os.environ.get('LATENCY_SUMMARY', '（取得失敗）')
cold = os.environ.get('COLD_LINE', '（取得失敗）')
run_url = os.environ['RUN_URL']
text = (
    f'*日次eval結果 — {overall}*\n'
    f'{c_icon} 正解率eval: {c}  |  {score}\n'
    f'{l_icon} レイテンシeval: {l}  |  {lat}  |  {cold}\n'
    f'<{run_url}|ワークフロー実行ログ>'
)
payload = json.dumps({'text': text})
r = subprocess.run(
    ['curl', '-sf', '-X', 'POST', os.environ['SLACK_WEBHOOK_URL'],
     '-H', 'Content-Type: application/json', '-d', payload]
)
sys.exit(r.returncode)
EOF
```

**通知内容の仕様:**

| 項目 | 取得元 | 例 |
|---|---|---|
| 全体合否アイコン | `steps.correctness.outcome` / `steps.latency.outcome` の AND | `:white_check_mark: 全eval合格` / `:x: eval失敗あり` |
| 正解率eval合否 | `steps.correctness.outcome`（`success` / `failure`） | `:white_check_mark: 正解率eval: success` |
| 正解率スコア | `/tmp/correctness_result.txt` の `スコア:` 行（`run_eval.py` 最終出力） | `スコア: 8/10 (80%)` |
| レイテンシeval合否 | `steps.latency.outcome`（`success` / `failure`） | `:x: レイテンシeval: failure` |
| レイテンシ統計 | `/tmp/latency_result.txt` の `最小:` 行（`run_latency_eval.py` 最終出力） | `最小: 3.21秒 / 平均: 8.45秒 / 最大: 52.10秒` |
| コールドスタート | `/tmp/latency_result.txt` の `1問目` 行（`run_latency_eval.py` 最終出力） | `1問目（コールドスタート想定）: 52.10秒` |
| 実行ログURL | `$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID` | Slack mrkdwn のリンク形式 `<url|ワークフロー実行ログ>` |

**`SLACK_WEBHOOK_URL` 未設定時の挙動:** `${{ secrets.SLACK_WEBHOOK_URL }}` が未設定の場合、環境変数は空文字列になる。`curl` が空 URL に対してエラーを返し、Notify Slack ステップは失敗する。`continue-on-error: true` により後続のステップ10（Fail if either eval failed）は eval の結果のみで判定される。

---

## 3. IAMロール仕様

### 3.1 基本情報

| 項目 | 値 |
|---|---|
| [推奨デフォルト値（PENDING）] ロール名 | `GitHubActionsScheduledEvalRole`（`GitHubActionsDeployRole`・`GitHubActionsReingestRole` の命名規則を踏襲） |
| AWSアカウントID | `215552491011`（既存ロールと同一。spec_infra.md 9.4章より） |
| リージョン | `ap-northeast-1`（既存リソースと同一） |
| 作成方法 | AWS コンソールまたは AWS CLI による手動作成（IAM はグローバルサービスのためリージョン指定不要） |

### 3.2 信頼関係（Trust Policy）

既存ロール（`GitHubActionsDeployRole`・`GitHubActionsReingestRole`）と同一のパターンを使用する（spec_infra.md 9.4章「確定」事項を継承）。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::215552491011:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:kazuki1016@71158437/FDE_ENTRY_HO@1340135191:*"
        }
      }
    }
  ]
}
```

**重要**: `sub` 条件は GitHub immutable ID 形式（`repo:{owner}@{owner_id}/{repo}@{repo_id}:*`）を使用する。
従来形式（`repo:{owner}/{repo}:*`）では `AssumeRoleWithWebIdentity` が
`Not authorized` で拒否されることが実機で確認されている（spec_infra.md 9.4章）。

### 3.3 権限ポリシー（最小権限）

`secretsmanager:GetSecretValue` を対象シークレットの **個別 ARN** に限定して付与する。
ワイルドカードは使用しない（spec_infra.md 8.2章 最小権限ポリシー方針を継承）。

**インラインポリシー例（`ScheduledEvalSecretsAccess`）:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "[要確認: fde-rag/aws-secrets の完全 ARN]"
    }
  ]
}
```

| 権限 | 対象リソース | 備考 |
|---|---|---|
| `secretsmanager:GetSecretValue` | `fde-rag/aws-secrets` の完全 ARN（`arn:aws:secretsmanager:ap-northeast-1:215552491011:secret:fde-rag/aws-secrets-XXXXXX` 形式。末尾のランダムサフィックスを含む正確な ARN を指定すること） | 個別 ARN 指定。ワイルドカード不使用 |

**このロールに付与しない権限（過剰権限の排除）:**

- `bedrock:InvokeModel`（`run_eval.py` は `AWS_BEARER_TOKEN_BEDROCK` キーを環境変数として渡し、Bedrock SDK がそれをベアラートークンとして使用するため、IAM の Bedrock 権限は不要）
- S3 バケットへのアクセス権限（CIランナー上での `python -m ingest` は環境変数経由の Bedrock API キーのみを使用する。S3 上の ChromaDB アーカイブは使用しない）
- CloudWatch Logs 書き込み権限（GitHub Actions ランナーのログは Actions UI に表示される。CloudWatch Logs への書き込みは Lambda ランタイムに限った要件であり、本ロールには不要）

---

## 4. GitHub Secrets / Variables の構成

### 4.1 移行後に削除する GitHub Secrets

IAMロール作成・動作確認が完了した後（5章の移行手順参照）に削除する。

| Secret 名 | 削除可否 | 備考 |
|---|---|---|
| `BASIC_AUTH_USERNAME` | **削除する** | scheduled-eval.yml のみで使用。移行後は Secrets Manager 経由に切り替わる |
| `BASIC_AUTH_PASSWORD` | **削除する** | 同上 |
| `AWS_BEARER_TOKEN_BEDROCK` | **削除しない（確定・ユーザー確認済み）** | `.github/workflows/deploy.yml` の `Build ChromaDB for tests`・`Run tests` ステップが現在も `${{ secrets.AWS_BEARER_TOKEN_BEDROCK }}` を直接参照しており、deploy.ymlはOIDC/Secrets Manager経由への移行スコープ外（7.3章）。本値をGitHub Secretsから削除するとdeploy.ymlのpytestが壊れるため、削除しない。scheduled-eval.yml内では2.4章の通りSecrets Manager経由の値（`${{ env.AWS_BEARER_TOKEN_BEDROCK }}`）を使用し、GitHub Secretsの同名値とは独立に共存させる |

### 4.2 新規追加する GitHub Variables

| Variable 名 | 値 | 備考 |
|---|---|---|
| [推奨デフォルト値（PENDING）] `AWS_SCHEDULED_EVAL_ROLE_ARN` | `arn:aws:iam::215552491011:role/GitHubActionsScheduledEvalRole`（ロール名確定後に確定） | IAM ロール作成後に登録する。既存 `AWS_DEPLOY_ROLE_ARN`・`AWS_REINGEST_ROLE_ARN` と同パターン |

### 4.3 維持する既存 Secrets / Variables

本移行のスコープ外。変更しない。

| 種別 | 名前 | 用途 |
|---|---|---|
| Variable | `AWS_REGION` | 全ワークフロー共通（deploy.yml・reingest.yml と共有） |
| Variable | `RAG_ENDPOINT_URL` | `run_latency_eval.py` のエンドポイント URL |
| Variable | `AWS_DEPLOY_ROLE_ARN` | deploy.yml 用（変更なし） |
| Variable | `AWS_REINGEST_ROLE_ARN` | reingest.yml 用（変更なし） |
| Variable | `CHROMA_S3_BUCKET` | reingest.yml 用（変更なし） |
| Secret | `APP_API_KEY` | deploy.yml の pytest 用（変更なし） |

### 4.4 新規追加する GitHub Secrets（Slack通知用）

| Secret 名 | 値 | 備考 |
|---|---|---|
| [推奨デフォルト値（PENDING）] `SLACK_WEBHOOK_URL` | Slack の Incoming Webhook アプリで生成した Webhook URL（`https://hooks.slack.com/services/...` 形式） | AWS 認証情報ではないため Secrets Manager での管理は不要と判断（付記 P2・2.5章参照）。未設定の場合、Notify Slack ステップは `continue-on-error: true` により失敗するが eval 合否判定には影響しない |

---

## 5. 移行手順（運用）

**順序性の厳守**: IAMロール作成・動作確認を行ってから GitHub Secrets を削除する。
逆順（先に削除）を行うと、移行途中に既存の scheduled-eval.yml が認証失敗する。

| # | ステップ | 実施者 | 確認事項 |
|---|---|---|---|
| 1 | `fde-rag/aws-secrets` の完全 ARN を取得する | 開発者 | AWS コンソール（Secrets Manager）または `aws secretsmanager describe-secret --secret-id fde-rag/aws-secrets --query ARN --output text` で確認する |
| 2 | IAMロール（`GitHubActionsScheduledEvalRole`）を作成する | 開発者 | 3章の Trust Policy・権限ポリシーを設定する。ロール ARN を控える |
| 3 | GitHub Variables に `AWS_SCHEDULED_EVAL_ROLE_ARN` を登録する | 開発者 | 手順2で取得したロール ARN を設定する |
| 4 | GitHub Secrets に `SLACK_WEBHOOK_URL` を登録する | 開発者 | Slack の Incoming Webhook アプリで Webhook URL を生成し、登録する（4.4章参照） |
| 5 | scheduled-eval.yml を本仕様に従い更新し、リポジトリに push する | 開発者 | 6章の受け入れ基準に沿った動作確認を行う |
| 6 | `workflow_dispatch` で手動起動し、動作確認を行う | 開発者 | AC-SEVAL-1〜AC-SEVAL-5 を満たすことを確認する |
| 7 | 動作確認完了後に GitHub Secrets から `BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD` を削除する | 開発者 | 削除後にも `workflow_dispatch` で動作確認する（AC-SEVAL-2） |
| ~~8~~ | ~~`AWS_BEARER_TOKEN_BEDROCK` の削除要否を確認する~~ | — | **解消（ユーザー確認済み）**: deploy.ymlが直接参照しているため削除しない（4.1章参照）。対応不要 |

---

## 6. 受け入れ基準（検証可能形式）

spec_infra.md 7章と同じ「入力 | 操作 | 期待出力」の3列形式で定義する。

### AC-SEVAL-1: OIDC 認証と Secrets Manager 取得の成功

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-SEVAL-1-1 | `AWS_SCHEDULED_EVAL_ROLE_ARN` Variable が設定済み、新 IAMロールが作成済み | `workflow_dispatch` で scheduled-eval.yml を手動起動する | `Configure AWS credentials (OIDC)` ステップが成功し、AWS_ACCESS_KEY_ID 等の一時クレデンシャルが発行されること（ステップログに `Assumed role` が出力される） |
| AC-SEVAL-1-2 | OIDC 認証済みの状態 | `Retrieve secrets from Secrets Manager` ステップが実行される | ステップが正常終了し（exit code 0）、後続の Build ChromaDB・Run correctness eval・Run latency eval の各ステップが認証情報エラーなく実行されること |
| AC-SEVAL-1-3 | 上記移行後の通常スケジュール実行 | UTC 00:00（JST 9:00）にスケジュールトリガーで自動起動する | ワークフロー全体が成功（`success`）または eval 評価基準を満たさない場合は明示的に `exit 1` で失敗すること（認証エラー・Secrets Manager アクセスエラーによる失敗ではないこと） |

### AC-SEVAL-2: GitHub Secrets 削除後も動作すること（Secrets Manager 経由への完全移行確認）

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-SEVAL-2-1 | GitHub Secrets から `BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD` を削除済みの状態 | `workflow_dispatch` で scheduled-eval.yml を手動起動する | ワークフローが認証エラーなく実行され、`run_latency_eval.py` が Basic 認証ヘッダー付きでエンドポイントにリクエストを送信できること |
| AC-SEVAL-2-2 | GitHub Secrets から当該値を削除済みの状態 | ワークフローの `Retrieve secrets from Secrets Manager` ステップログを確認する | Secrets Manager から取得した値が後続ステップに正しく渡されており、`run_latency_eval.py` が HTTP 403（認証失敗）ではなく正常応答を受け取っていること |

### AC-SEVAL-3: IAMロールの権限が対象 Secrets に限定されていること

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-SEVAL-3-1 | 新 IAMロールの権限ポリシー | AWS コンソール（IAM ロール詳細）またはインラインポリシー JSON を確認する | `secretsmanager:GetSecretValue` のリソースが `fde-rag/aws-secrets` の完全 ARN（1リソース）のみであり、ワイルドカード（`*`）が使用されていないこと |
| AC-SEVAL-3-2 | 新 IAMロールの権限ポリシー | 同上 | `secretsmanager:*` や `*:*` のような過剰な権限が含まれていないこと |
| AC-SEVAL-3-3 | 新 IAMロールで assume した一時クレデンシャル | `aws secretsmanager get-secret-value --secret-id <別のシークレット名>` を実行する | `AccessDeniedException` が返ること（`fde-rag/aws-secrets` 以外のシークレットへのアクセスが拒否されること） |

### AC-SEVAL-4: 認証情報がワークフローログに平文で出力されないこと

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-SEVAL-4-1 | `workflow_dispatch` 実行後のワークフローログ | GitHub Actions UI で各ステップのログを確認する | `AWS_BEARER_TOKEN_BEDROCK`・`BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD` の具体的な値（文字列）がログに平文で表示されていないこと。`echo "::add-mask::"` によりマスク（`***`）されていること |
| AC-SEVAL-4-2 | `Retrieve secrets from Secrets Manager` ステップのログ | 同上 | `SECRET_JSON` の生の内容（Secrets Manager から取得した JSON 文字列）がログに出力されていないこと |

### AC-SEVAL-5: eval結果が合否に関わらず Slack に通知されること

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-SEVAL-5-1 | `SLACK_WEBHOOK_URL` Secret 設定済み、eval成功時（正解率80%以上・全問SLA内） | `workflow_dispatch` で起動し、Notify Slack ステップのログを確認する | 設定済み Slack チャンネルに「全eval合格」を示すメッセージが投稿されること。メッセージに正解率スコア行（`スコア: X/10`）・レイテンシ統計行（`最小: X.XX秒 / ...`）・ワークフロー実行 URL が含まれること |
| AC-SEVAL-5-2 | `SLACK_WEBHOOK_URL` Secret 設定済み、eval失敗時（正解率80%未満またはSLA超過） | 同上 | 「eval失敗あり」を示すメッセージが Slack に投稿されること。失敗したeval種別（正解率・レイテンシ）に対して `:x:` アイコンが表示され、ワークフロー実行 URL が含まれること |
| AC-SEVAL-5-3 | `SLACK_WEBHOOK_URL` Secret が未設定の状態 | `workflow_dispatch` で起動する | Notify Slack ステップが失敗するが（`continue-on-error: true` により後続ステップへ進む）、ステップ10（Fail if either eval failed）は eval の実行結果のみで合否判定を行い、Slack 通知の失敗はワークフロー全体の結果に影響しないこと |
| AC-SEVAL-5-4 | `SLACK_WEBHOOK_URL` Secret 設定済み、ステップ7（correctness eval）が失敗した状態 | ワークフローのステップ9（Notify Slack）が `if: always()` で実行される | eval ステップが失敗していても Notify Slack ステップが実行されること（`if: always()` の動作確認） |

---

## 7. 制約と前提

### 7.1 CLAUDE.md との整合性

| CLAUDE.md 規定 | 本仕様での扱い |
|---|---|
| 6章「GitHubリポジトリに長期的なAWSアクセスキーを保存しない（OIDC連携のみ使用）」 | **遵守**: 新 IAMロールは OIDC 連携（`AssumeRoleWithWebIdentity`）のみで使用する。`AWS_ACCESS_KEY_ID`・`AWS_SECRET_ACCESS_KEY` は GitHub Secrets に登録しない |
| 6章「APIキー・トークンをソースコードにハードコードしない」 | **遵守**: 認証情報は Secrets Manager から実行時に取得し、`$GITHUB_ENV` 経由でマスク処理後に使用する |
| 5.2章「LambdaランタイムのシークレットをLambda環境変数またはソースコードに平文で保存しない（AWS Secrets Managerのみ使用）」 | **継承**: GitHub Actions 上でも同一の Secrets Manager シークレット（`fde-rag/aws-secrets`）を参照することで、認証情報の一元管理を維持する |
| 5.2章「AWS構成: GitHubリポジトリに長期的なAWSアクセスキーを保存しない」 | **遵守**: 本仕様はこの方針を scheduled-eval.yml に適用する変更である |
| 2章「Simplicity First」 | **遵守**: Slack 連携は Incoming Webhook + `curl` のみ。Slack App 新規作成・Bot Token 方式・Secrets Manager への同居は過剰設計のため採用しない |

### 7.2 既存仕様との整合性

| 参照先 | 整合事項 |
|---|---|
| spec_infra.md 9.4章 | Trust Policy の `sub` 条件（immutable ID 形式）を新ロールにも同一パターンで適用する |
| spec_infra.md 8.2章 | 最小権限ポリシー（個別 ARN 指定・ワイルドカード不使用）を本ロールにも適用する |
| CLAUDE.md 5.2章 PENDING「`GET /health`・`GET /stats` の認証要否」 | 本ワークフローは `/health`・`/stats` エンドポイントを直接呼ばないため影響なし |

### 7.3 スコープ外（本仕様では定義しない）

- deploy.yml の認証情報取得方式の変更（`AWS_BEARER_TOKEN_BEDROCK` を deploy.yml でも Secrets Manager 経由に移行するかは、本スコープ外）
- reingest.yml の変更（既に OIDC 連携済み。本仕様の影響なし）
- `fde-rag/aws-secrets` シークレット自体の値変更・ローテーション設計
- eval の成否判定基準（正解率・レイテンシの閾値）の変更（spec.md・CLAUDE.md 5.3章から継承）
- Slack 通知チャンネルの選定・Incoming Webhook アプリの作成手順（運用側の作業として本仕様のスコープ外）

---

## 付記: [要確認] 項目一覧

### ブロック値・確定が必要な項目

| # | 箇所 | 内容 | 対応方針 |
|---|---|---|---|
| 1 | 3.3 権限ポリシー | `fde-rag/aws-secrets` の完全 ARN（`arn:aws:secretsmanager:ap-northeast-1:215552491011:secret:fde-rag/aws-secrets-XXXXXX`。末尾のランダムサフィックスが未確認）。ユーザーの判断を要する項目ではなく、`aws secretsmanager describe-secret` で取得すれば解消する実装前タスク | `aws secretsmanager describe-secret --secret-id fde-rag/aws-secrets --query ARN --output text` で取得し、ポリシーに記載する |
| ~~2~~ | ~~4.1 削除対象 Secrets~~ | **解消（ユーザー確認済み）**: `AWS_BEARER_TOKEN_BEDROCK` はdeploy.ymlが直接参照しているため GitHub Secrets から削除しない。BASIC_AUTH_USERNAME・BASIC_AUTH_PASSWORDの2値のみ削除する（req_scheduled-eval.md 要件3は本値に関して一部未達となるが、意図的な判断） | 対応不要 |

### 推奨デフォルト値（PENDING）として記載した項目

| # | 箇所 | 内容 | 推奨値 |
|---|---|---|---|
| P1 | 3.1 / 4.2 | IAMロール名・対応する GitHub Variable 名 | `GitHubActionsScheduledEvalRole`・`AWS_SCHEDULED_EVAL_ROLE_ARN`（既存ロールの命名規則を踏襲） |
| P2 | 4.4 / 2.5 | `SLACK_WEBHOOK_URL` の保存場所 | GitHub Secrets に `SLACK_WEBHOOK_URL` として保存する（推奨）。CLAUDE.md 6章の「長期的なAWSアクセスキーを保存しない」制約は AWS 認証情報に限定されており、Slack Incoming Webhook URL には適用されない。Secrets Manager への同居（AWS認証情報と混在）は Simplicity First に反するため不採用。ユーザー確認後、4.4章の `[推奨デフォルト値（PENDING）]` タグを除去すること |
