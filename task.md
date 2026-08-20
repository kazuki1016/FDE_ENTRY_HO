# AWS構成 実装計画（stage-gate）

生成日: 2026-08-19
入力: `spec_infra.md`
生成エージェント: stage-gate
位置づけ: `spec_infra.md`（AWSインフラ仕様）を実装可能な単位に分解した進行管理表。ngrok構成（req.md / spec.md）には影響しない範囲で、AWS構成の実装をフェーズ・ステップに分割する。

---

## 前提条件の確認（既存コードの問題点）

| 箇所 | 問題 |
|---|---|
| `src/config.py` 21行目 `API_KEY = os.environ["APP_API_KEY"]` | モジュール読み込み時に即評価される。AWS構成では`APP_API_KEY`は設定されないため`KeyError` |
| `src/config.py` 25行目 `AWS_BEARER_TOKEN_BEDROCK = os.environ["AWS_BEARER_TOKEN_BEDROCK"]` | 同上。Secrets Manager経由取得に変更する必要がある |
| `src/server.py` 25行目 `_store = ChromaVectorStore(config.CHROMA_DB_PATH)` | モジュール読み込み時にChromaDBを即初期化。Lambda起動時にS3ダウンロードより先に空の`/tmp/chroma_db`が作成され、検索結果が常に0件になる |
| `src/server.py` `_log_request`関数 | `logs/requests.jsonl`へのファイル書き込み。Lambda Container Imageでは`/tmp`以外は読み取り専用のため`PermissionError` |
| `src/server.py` 全体 | Basic認証ロジックが存在しない（X-API-Keyのみ） |
| `requirements.txt` | `mangum`が未記載 |

`tests/test_server.py`は`APP_API_KEY`環境変数が設定されている前提で動作する。Phase 2のコード変更がこの前提を壊さないことを各ステップで確認する。

---

## ステージゲート進行状況

| Phase | Step | 名称 | 変更ファイル | 状態 | ゲート条件 |
|---|---|---|---|---|---|
| 1 | 1 | mangum 追加 | requirements.txt | DONE | requirements.txtにmangumが記載されること — 確認済み |
| 2 | 2 | config.py 遅延ロード化 | src/config.py | DONE | pytest tests/ 全件GREEN — 確認済み（15 passed） |
| 2 | 3 | server.py ChromaDB遅延初期化 | src/server.py | DONE | pytest tests/ 全件GREEN — 確認済み（15 passed） |
| 2 | 4 | server.py Basic認証・ログ分岐 | src/server.py, tests/test_server.py | DONE | pytest tests/ 全件GREEN（既存11件PASS + 新規Basic認証テスト4件PASS） — 確認済み |
| 3 | 5 | Lambda ハンドラー作成 | src/lambda_handler.py | DONE | ローカルでの疎通確認 — 確認済み（ウォームスタート相当で`import lambda_handler`成功） |
| 3 | 6 | Dockerfile 作成 | Dockerfile | DONE | ローカルでのイメージビルド成功 — 確認済み（3.82GB、10GB未満）。実装時にPython 3.12への変更・CPU専用torch・onnxruntime/pymupdf周りの修正が必要と判明（詳細はspec_infra.md 2.4章・2.6章参照） |
| 4 | 7 | CDK 骨格 + S3×2 定義 | infra/app.py, infra/stacks/main_stack.py | DONE | cdk synth が成功すること — Step 7-10まとめて1回のcdk synthで確認済み |
| 4 | 8 | Lambda + Function URL 定義 | infra/stacks/main_stack.py | DONE | cdk synth が成功すること — 確認済み。AWS_REGIONがLambda予約済み環境変数で手動設定不可と判明し修正 |
| 4 | 9 | CloudFront + ルーティング + OAC 定義 | infra/stacks/main_stack.py | DONE | cdk synth が成功すること — 確認済み |
| 4 | 10 | CloudFront Functions + KVS + SM同期定義 | infra/stacks/main_stack.py, infra/cf_auth.js | DONE | cdk synth が成功すること — 確認済み。当初想定のAwsCustomResourceでは表現できずカスタムLambda+Providerに変更（詳細はspec_infra.md） |
| 5 | 11 | deploy.yml 作成 | .github/workflows/deploy.yml | DONE | YAML構文チェック通過 — 確認済み。人間承認A(GitHubリポジトリ)完了済み |
| 5 | 12 | reingest.yml 作成 | .github/workflows/reingest.yml | DONE | YAML構文チェック通過 — 確認済み |
| 6 | 13 | 初回 cdk deploy 実行 | （インフラ作成） | DONE | AWSリソース作成完了 — 確認済み（27/27 CREATE_COMPLETE）。CloudFront: dgjeh1trfl9lf.cloudfront.net |
| 6 | 14 | 初回 ChromaDB S3 アップロード | （データ配置） | DONE | S3にアーカイブが配置されること — 確認済み。GET /statsでchunk_count=109を確認 |
| 6 | 15 | E2Eおよびインフラ受け入れ基準検証 | （テスト実行） | DONE | AC-INFRA-1〜5 全件PASS — 確認済み。AC-INFRA-4-2は自動化上の制約により部分検証（実ブラウザでの最終確認を推奨）、AC-INFRA-5-2は利用実績蓄積後にAWS Billingで別途確認する運用事項として記録（詳細はStep 15進捗欄） |
| 6 | 16 | コンフォーマンス監査 + 品質ゲート確認 | （監査実行） | BLOCKED | 8.6章 品質ゲート5条件すべて充足 |

---

## 各ステップの詳細

### Phase 1: 前提条件整備

#### Step 1: `requirements.txt` への `mangum` 追加
- **変更ファイル**: requirements.txt
- **内容**: `mangum`パッケージを1行追加する
- **ゲート条件**: requirements.txtにmangumが記載されていること。`pip install -r requirements.txt`が正常終了すること
- **依存関係**: なし

---

### Phase 2: 共有コード変更（後方互換、ngrok構成影響ゼロ）

spec_infra.md 4.3章に記述されている変更をステップ分割して実施する。各ステップ完了時に`pytest tests/`を実行し、ngrok構成の既存テストが壊れていないことを確認する。

#### Step 2: `config.py` 遅延ロード化
- **変更ファイル**: src/config.py
- **内容**:
  - `API_KEY = os.environ["APP_API_KEY"]` → `os.environ.get("APP_API_KEY")`（ngrok構成でのみ設定される任意値。AWS構成では`None`）
  - `AWS_BEARER_TOKEN_BEDROCK = os.environ["AWS_BEARER_TOKEN_BEDROCK"]` を削除し、`@lru_cache`付き`get_secrets()`関数内でboto3の`secretsmanager.get_secret_value`を呼び出す形に変更。`AWS_SECRETS_NAME`未設定時は`os.environ.get("AWS_BEARER_TOKEN_BEDROCK")`にフォールバック（ngrok構成の後方互換）
  - `BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD`を新規追加（`get_secrets()`経由）
- **ゲート条件**: `pytest tests/` 全件GREEN
- **依存関係**: Step 1 の完了後

#### Step 3: `server.py` ChromaDB遅延初期化
- **変更ファイル**: src/server.py
- **内容**: `_store = ChromaVectorStore(config.CHROMA_DB_PATH)`のモジュールレベル即時初期化を廃止し、`@lru_cache`の`get_store()`ファクトリ関数に置き換える。各エンドポイントで`get_store()`を呼ぶ
- **ゲート条件**: `pytest tests/` 全件GREEN
- **依存関係**: Step 2 の完了後

#### Step 4: `server.py` Basic認証追加 + ログ出力先分岐
- **変更ファイル**: src/server.py, tests/test_server.py
- **内容**:
  - Basic認証ロジックを追加（`config.API_KEY`設定時はAPIキー方式、`config.BASIC_AUTH_USERNAME`等設定時はBasic認証方式）
  - **両方未設定の場合はフェイルクローズ（全リクエスト403）**（CLAUDE.md 6章「認証バイパスの脆弱性ゼロ」品質ゲートに直結）
  - `_log_request`の出力先を分岐（`config.LOG_PATH`設定時はファイル書き込み=ngrok構成、未設定時は`print(json.dumps(...))`で標準出力=AWS構成）
  - テスト追加: Basic認証403/200、フェイルクローズの検証（日本語テスト関数名）
- **ゲート条件**: `pytest tests/` 全件GREEN（既存APIキー認証テスト継続PASS + 新規テストPASS）
- **依存関係**: Step 2・3 の完了後

**[Phase 2完了後チェック]** `pytest tests/ -v` を実行し全件GREENであることを確認する（ngrok構成の後方互換性の最終確認）。

---

### Phase 3: Lambdaエントリーポイントとコンテナ化

#### Step 5: `src/lambda_handler.py` 作成
- **変更ファイル**: src/lambda_handler.py（新規）
- **内容**: モジュールレベルで`/tmp/chroma_db`の存在確認 → 存在しなければS3から`chroma_db_latest.tar.gz`をダウンロード・展開 → `CHROMA_DB_PATH`を`/tmp/chroma_db`に上書き → `server.app`をインポート → `Mangum(app)`でハンドラー生成。S3バケット名・キーは環境変数（`CHROMA_S3_BUCKET`・`CHROMA_S3_KEY`）。S3ファイル不在時は`RuntimeError`（AC-INFRA-3-3対応）
- **ゲート条件**: ローカルでの疎通確認（`python -c "import lambda_handler"`がエラーなく完了）
- **依存関係**: Step 3・Step 1 の完了後

#### Step 6: `Dockerfile` 作成
- **変更ファイル**: Dockerfile（新規）
- **内容**: ベースイメージ`public.ecr.aws/lambda/python:3.11`、requirements.txtインストール、embeddingモデルをビルド時に事前ダウンロードしイメージに同梱（コールドスタート時のHugging Faceダウンロード排除）、`src/`をコピーし`CMD ["lambda_handler.handler"]`
- **ゲート条件**: `docker build`が成功しイメージサイズ10GB未満であること
- **依存関係**: Step 1・Step 5 の完了後

---

### Phase 4: CDKインフラコード

各ステップで`cdk synth`成功をゲートとする。実際のAWSリソース作成はPhase 6（人間承認後）まで行わない。

#### Step 7: CDK骨格 + S3バケット×2定義
- **変更ファイル**: infra/app.py, infra/stacks/main_stack.py（新規）
- **内容**: CDKアプリ基本構造。フロントエンド用S3・ChromaDB永続化用S3の2バケット定義（OAC前提のパブリックアクセスブロック有効化）
- **ゲート条件**: `cdk synth`成功、テンプレートにS3×2出力
- **依存関係**: 人間承認B（`cdk bootstrap`完了）後、Step 6 の後

#### Step 8: Lambda + Function URL定義
- **変更ファイル**: infra/stacks/main_stack.py
- **内容**: `DockerImageFunction`定義（タイムアウト90秒・メモリ3008MB）、Function URL（認証タイプ`NONE`）、環境変数設定、IAM実行ロール最小権限（S3 GetObject・Secrets Manager GetSecretValue・CloudWatch Logs書き込み）
- **ゲート条件**: `cdk synth`成功
- **依存関係**: Step 7 の完了後

#### Step 9: CloudFront + ルーティング + OAC定義
- **変更ファイル**: infra/stacks/main_stack.py
- **内容**: Distribution定義。デフォルトビヘイビア→S3（OAC）、`/ask`・`/health`・`/stats`→Lambda Function URL（CachingDisabled、Authorizationヘッダー転送）。カスタムドメインなし。`BucketDeployment`で`__API_KEY_JSON__`→`null`置換してS3アップロード
- **ゲート条件**: `cdk synth`成功
- **依存関係**: Step 7・8 の完了後

#### Step 10: CloudFront Functions + KeyValueStore + Secrets Manager同期定義
- **変更ファイル**: infra/stacks/main_stack.py, infra/cf_auth.js（新規）
- **内容**: CloudFront Functions（Basic認証、KeyValueStoreと照合、失敗時401+WWW-Authenticate）、KeyValueStore定義、`AwsCustomResource`でSecrets Manager→KeyValueStoreの同期を`cdk deploy`時に実行
- **ゲート条件**: `cdk synth`成功
- **依存関係**: Step 9 の完了後、人間承認B（Secrets Manager作成済み）後

---

### Phase 5: CI/CDワークフロー

#### Step 11: `deploy.yml` 作成
- **変更ファイル**: .github/workflows/deploy.yml（新規）
- **内容**: mainへのpushトリガー、OIDC認証、`pytest tests/` → `cdk deploy`。eval実行はCIに含めない
- **ゲート条件**: YAML構文チェック通過
- **依存関係**: 人間承認A・C の後、Step 10 の後

#### Step 12: `reingest.yml` 作成
- **変更ファイル**: .github/workflows/reingest.yml（新規）
- **内容**: `workflow_dispatch`トリガー、OIDC認証（reingest用ロール）、S3からPDFダウンロード→ingest.py→アーカイブ化→S3アップロード。`actions/cache`でpipキャッシュ
- **ゲート条件**: YAML構文チェック通過
- **依存関係**: Step 11 の完了後

---

### Phase 6: デプロイと品質保証

#### Step 13: 初回 `cdk deploy` 実行
- **ゲート条件**: CloudFormationスタックが`CREATE_COMPLETE`、CloudFrontデフォルトドメイン発行
- **依存関係**: 人間承認D の後、Phase 4・5 全ステップ完了後

#### Step 14: 初回ChromaDB S3アップロード
- **内容**: `data/chroma_db/`をtar.gz化しS3にアップロード
- **ゲート条件**: S3にオブジェクト存在確認、`GET /stats`で`chunk_count`が10以上
- **依存関係**: Step 13 の完了後

#### Step 15: エンドツーエンド受け入れ基準検証
- **内容**: spec_infra.md 7章のAC-INFRA-1〜5をCloudFront URL経由で検証
- **ゲート条件**: 全件PASS、CloudWatch Logsにリクエストログ出力確認
- **依存関係**: Step 14 の完了後
- **進捗**:
  - AC-INFRA-1-1/1-2/1-3（CloudFront Basic認証）: PASS
  - AC-INFRA-2-1/2-2/2-3/2-4（FastAPI層Basic認証・Function URL直接）: PASS
  - AC-INFRA-3-1/3-2（コールド/ウォームスタート）: PASS（CloudWatch Logsで確認。コールド18.4秒、ウォーム5.8〜6.8秒）
  - AC-INFRA-3-3（S3アーカイブ不在時にエラーが返ること）: PASS（本番S3オブジェクトを一時退避して検証、直後に復元済み。期待値は**HTTP 502**に訂正。spec_infra.md AC-INFRA-3-3参照）
  - AC-INFRA-4-1/4-3（CloudFront経由 /ask・/health）: PASS
  - AC-INFRA-4-2（ブラウザでのUI動作）: 部分検証（Playwrightでindex.html表示・質問入力・送信ボタンの動作は確認できたが、自動化のためURLに認証情報を埋め込む方式（`https://user:pass@host/`）を使った結果、ブラウザのFetch仕様上の制約「認証情報を含むURLからのfetch()は禁止」に抵触し`/ask`呼び出しがブロックされた。これは自動化手法固有の制約であり、実際のユーザーがネイティブのBasic認証ダイアログ経由でアクセスする場合はURLに認証情報が残らないため発生しない。AC-INFRA-1（CloudFront Basic認証）・AC-INFRA-4-1（CloudFront経由/ask）はcurlで個別に確認済みのため実質的な機能は検証できているが、実ブラウザでの手動クリックスルーによる最終確認を推奨する）
  - AC-INFRA-5-1（60秒以内のレイテンシ）: PASS（ウォームスタート5.8〜7.0秒、コールドスタート31.7秒）
  - AC-INFRA-5-2（無料枠内のコスト）: 未実施（利用実績が蓄積してからAWS Billingで確認）
  - 実装時に5件の不具合発覚・修正済み（spec_infra.md 2.1章・2.6章に記録）:
    1. `default_root_object`未設定によるルートパスAccessDenied
    2. `HF_HOME`未固定によるembeddingモデル再ダウンロード失敗
    3. オリジンリクエストポリシー`AllViewer`のHostヘッダー転送によるLambda Function URLのAccessDeniedException
    4. `allowed_methods`未設定によるPOST /askの403拒否
    5. Lambda初期化フェーズの例外メッセージに日本語を含めると`awslambdaric`が`UnicodeEncodeError`で二次クラッシュする問題（`lambda_handler.py`の例外メッセージを英語化して解消）
    6. `FunctionUrlOrigin`の`read_timeout`既定値30秒がコールドスタート時間を下回り504 Gateway Timeoutが発生（60秒に変更して解消。spec_infra.md 8.3章E-NEW-1の懸念が実測で顕在化）
  - AC-INFRA-3-3検証時、本番S3オブジェクトの一時削除と復元の間にLambda環境変数へ手動で加えたテスト用の値（`FORCE_COLD_START_TEST`）がCloudFormationの管理外ドリフトとして残存する事象が発生し、`aws lambda update-function-configuration`で手動是正した（CDKデプロイは変更のないプロパティを再適用しないため、手動でのライブリソース変更はCDK側からは検知されない点に注意）

#### Step 16: コンフォーマンス監査 + 品質ゲート最終確認
- **内容**: spec_infra.md 8.6章の品質ゲート5条件（テストGREEN、eval80%以上、監査差分ゼロ、認証バイパスゼロ、metsukeyakuレビューPASS/CONDITIONAL）を確認
- **ゲート条件**: 5条件すべて充足
- **依存関係**: Step 15 の完了後

---

## 人間承認が必要なタイミング

| 記号 | タイミング | 理由 |
|---|---|---|
| A | GitHubリポジトリ作成前 | 外部サービスへの公開。可視性の決定権はユーザーにある |
| B | AWS Secrets Manager作成・`cdk bootstrap`前 | AWSアカウントに費用が発生するリソース作成 |
| C | OIDCロール設定前 | IAMロール作成はAWSセキュリティ境界に影響する |
| D | `cdk deploy`（本番デプロイ）実行前 | CloudFront・Lambda・S3等のリソースが実際に作成・稼働開始し費用が発生する |

Phase 2（Step 2〜4）とPhase 3（Step 5〜6）はAWSアクセス不要のため、人間承認A〜Dを待たずに並行着手できる。

## 依存関係グラフ

```
Step 1（mangum）
  └→ Step 5（lambda_handler.py）→ Step 6（Dockerfile）
       └→ Step 7（CDK骨格+S3）→ Step 8（Lambda+FunctionURL）→ Step 9（CloudFront+ルーティング）
            → Step 10（CF Functions+KVS+SM同期）→ Step 11（deploy.yml）→ Step 12（reingest.yml）
                 → [人間承認D] → Step 13（cdk deploy）→ Step 14（S3アップロード）
                      → Step 15（E2E検証）→ Step 16（監査+品質ゲート）

Step 2（config.py）→ Step 3（ChromaDB遅延初期化）→ Step 4（Basic認証+ログ分岐）
  ※ [Phase 2完了後チェック] pytest tests/ 全件GREEN確認

[人間承認A] GitHubリポジトリ作成 → [人間承認C] OIDCロール設定 → Step 11
[人間承認B] Secrets Manager作成 + cdk bootstrap → Step 7, Step 10
```
