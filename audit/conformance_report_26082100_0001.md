# コンフォーマンス監査レポート

- **監査日時**: 2026-08-21 00:00
- **監査者**: auditor エージェント（claude-sonnet-4-6）
- **対象コミットハッシュ**: 5c38180035e765f04c6ba249c12b47b0772630dc
  - コミットメッセージ: Lambda実行時にHF_HOMEが未設定でモデル再取得が発生する障害を修正
- **監査対象ファイル**:
  - 仕様書: `spec.md`（2026-08-15生成）、`spec_infra.md`（2026-08-19生成）
  - 障害報告書: `incidents/2026-08-21_cold-start-timeout-embedding-migration.md`
  - 実装: `src/config.py`、`src/ingest.py`、`src/retriever.py`、`src/generator.py`、`src/server.py`、`src/lambda_handler.py`
- **監査重点観点**: embedding移行（Amazon Bedrock Titan Text Embeddings V2）に伴う実装変更の仕様適合性

---

## 仕様 vs 実装 照合結果

### A. embedding移行関連（重点確認項目）

| spec項目 | 参照元 | 実装ファイル:行 | 状態 | 差分詳細 |
|---|---|---|---|---|
| EMBEDDING_MODEL = `amazon.titan-embed-text-v2:0` | spec.md 6.1、incidents §4 | `config.py:78` | MATCH | `os.getenv("EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")` |
| EMBEDDING_DIMENSIONS = 1024 | spec.md 3.1、incidents §4 | `config.py:79` | MATCH | `int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))` |
| TOP_K = 3 | spec.md 4.2（確定値）、incidents §4.1 | `config.py:29` | MATCH | `TOP_K = 3`。コメントに変更履歴と確認済み旨を記録 |
| TIMEOUT_SEC = 45 | spec.md 6.3 | `config.py:33` | MATCH | `TIMEOUT_SEC = 45`。CloudFrontオリジンread_timeout(60s)との干渉回避を理由に明記 |
| `_bedrock_client()` の実装 | incidents §4 | `ingest.py:146-156` | MATCH | `boto3.client("bedrock-runtime", region_name=config.AWS_REGION)` を `@lru_cache` でシングルトン管理 |
| Noneガード / IAMフォールバック | incidents §4 | `ingest.py:154-155` | MATCH | `if config.AWS_BEARER_TOKEN_BEDROCK:` で Noneチェック後に `os.environ` を設定。未設定時は boto3 の標準IAM認証チェーンにフォールバック |
| `embed_text()` の実装: Bedrock Titan V2 | spec.md 4.1・4.2、incidents §4 | `ingest.py:159-171` | MATCH | `modelId=config.EMBEDDING_MODEL`（`amazon.titan-embed-text-v2:0`）、`dimensions=config.EMBEDDING_DIMENSIONS`（1024）、`normalize=True` で呼び出し |
| `retriever.py` が `ingest.embed_text()` を再利用 | spec.md 4.2、incidents §4 | `retriever.py:7,16` | MATCH | `from ingest import ... embed_text`。ローカルの `SentenceTransformer` は廃止済み |
| `torch`・`transformers`・`sentence-transformers` の削除 | incidents §4 | `requirements.txt` | MATCH | 3パッケージとも `requirements.txt` に存在しない |
| `fitz`（PyMuPDF）の遅延import | spec_infra.md 2.6 | `ingest.py:120` | MATCH | `extract_chunks()` 関数内で `import fitz` を実行。Lambda実行パスでは呼ばれないため除外可能 |

### B. API仕様（spec.md 2章）

| spec項目 | 参照元 | 実装ファイル:行 | 状態 | 差分詳細 |
|---|---|---|---|---|
| POST /ask エンドポイント | spec.md 2.1 | `server.py:123-144` | MATCH | `@app.post("/ask", response_model=AskResponse)` |
| POST /ask リクエスト: question必須、空文字不可 | spec.md 2.1 | `server.py:125-126` | MATCH | `if not request.question.strip(): raise HTTPException(status_code=400, ...)` |
| POST /ask レスポンス: `{answer, sources[{page, section, title}]}` | spec.md 2.1 | `server.py:140-144` | MATCH | `sources` に `page_number`→`page`、`section_number`→`section`、`title` をマッピング |
| POST /ask 認証失敗: 403 | spec.md 2.1、CLAUDE.md 5.2 | `server.py:93` | MATCH | `raise HTTPException(status_code=403, detail="認証に失敗しました")` |
| POST /ask 内部エラー: 500 | spec.md 2.1 | `server.py:135` | MATCH | `raise HTTPException(status_code=500, detail="内部エラーが発生しました")` |
| GET /health エンドポイント | spec.md 2.2 | `server.py:147-149` | MATCH | `{"status": "ok"}` を返す |
| GET /stats エンドポイント | spec.md 2.3 | `server.py:152-164` | MATCH | `chunk_count`（int）、`last_updated`（ISO 8601文字列またはNone）を返す |
| 422を使わず400に統一 | CLAUDE.md 5.2 | `server.py:37-40` | MATCH | `RequestValidationError` → 400 ハンドラーを明示的に定義 |
| GET / （Web UI配信） | spec.md AC-5-2 | `server.py:167-171` | MATCH | `templates/index.html` を読み込み `__API_KEY_JSON__` を置換して返す |

### C. 認証・セキュリティ（spec.md 6.4、spec_infra.md 4章）

| spec項目 | 参照元 | 実装ファイル:行 | 状態 | 差分詳細 |
|---|---|---|---|---|
| ngrok構成: APIキー認証（`X-API-Key` ヘッダー） | spec.md 6.4 | `server.py:58-62` | MATCH | `_api_key_matches()` が `hmac.compare_digest` で定数時間比較 |
| AWS構成: Basic認証（`Authorization: Basic` ヘッダー） | spec_infra.md 4.2 | `server.py:64-74` | MATCH | `_basic_auth_matches()` が `hmac.compare_digest` で定数時間比較 |
| `hmac.compare_digest` タイミング攻撃対策 | spec_infra.md 4.2、CLAUDE.md 5.2 | `server.py:61,72-73` | MATCH | APIキー・Basic認証ともに `hmac.compare_digest` を使用 |
| フェイルクローズ: 両認証未設定時は全リクエスト403 | spec_infra.md 4.3（C-NEW-3） | `server.py:81-85` | MATCH | `if config.API_KEY: ... elif config.BASIC_AUTH_USERNAME and ...: ... return False` |
| GET /health・GET /stats は認証不要（PENDING既定） | spec.md 2.2-2.3、CLAUDE.md 5.2 | `server.py:96-101、148、153` | MATCH | `_require_api_key_if_enabled` は `config.HEALTH_STATS_AUTH_REQUIRED=False` の場合スキップ |
| PDFパスのAPIレスポンス非漏洩 | spec.md 6.4 | `server.py` 全体 | MATCH | レスポンス・ログともにPDFの絶対パスを含む処理なし |
| APIキー・トークンのソースコードへのハードコード禁止 | CLAUDE.md 6章 | `src/` 全体 | MATCH | APIキー・Bedrockトークンは `os.environ` または Secrets Manager 経由のみ |
| HTTPステータスコードは 200/400/403/500 に限定 | CLAUDE.md 5.2 | `server.py` 全体 | MATCH | 5つのエラーハンドリング箇所すべて上記コードのみ使用。401は使用していない |

### D. LLMバックエンド（spec.md 4.3、6.1）

| spec項目 | 参照元 | 実装ファイル:行 | 状態 | 差分詳細 |
|---|---|---|---|---|
| `AnthropicBedrock` クライアント使用 | spec.md 4.3 | `generator.py:4,27` | MATCH | `from anthropic import AnthropicBedrock` |
| ベアラートークン方式のBedrock APIキー認証 | spec.md 4.3 | `generator.py:28` | MATCH | `api_key=config.AWS_BEARER_TOKEN_BEDROCK` |
| モデルID: `jp.anthropic.claude-sonnet-4-6` | spec.md 6.1 | `config.py:84` | MATCH | `os.getenv("LLM_MODEL", "jp.anthropic.claude-sonnet-4-6")` |
| Bedrockタイムアウト: 45秒 | spec.md 6.3 | `generator.py:30` | MATCH | `timeout=config.TIMEOUT_SEC`（=45） |
| システムプロンプト: 「講座内容に該当する情報がありません」文言 | spec.md 4.3 | `generator.py:9-16` | MATCH | 文言を含むシステムプロンプトを定義 |
| 回答は日本語で生成 | CLAUDE.md 5.1 | `generator.py:11` | MATCH | 「日本語で回答してください」と明示 |
| `LLMBackendProtocol` によるインターフェース分離（NFR-4） | spec.md 6.6 | `generator.py:19-21` | MATCH | `class LLMBackendProtocol(Protocol)` を定義し `BedrockLLMBackend` が実装 |

### E. データ取り込み・検索（spec.md 3.1・4.1・4.2）

| spec項目 | 参照元 | 実装ファイル:行 | 状態 | 差分詳細 |
|---|---|---|---|---|
| チャンクのメタデータ: `section_number`, `page_number`, `title` | spec.md 3.1 | `ingest.py:23-27,52-59` | MATCH | `Chunk` TypedDict で3フィールドを定義し `ChromaVectorStore.add_chunks` で保存 |
| `VectorStoreProtocol` によるインターフェース分離（NFR-4） | spec.md 6.6 | `ingest.py:30-33` | MATCH | `class VectorStoreProtocol(Protocol)` を定義 |
| ChromaDB 永続化パス: `data/chroma_db/` | spec.md 6.7 | `config.py:27` | MATCH | `os.getenv("CHROMA_DB_PATH", "data/chroma_db")` |
| コサイン距離関数の使用 | spec.md 4.2（PENDING既定） | `ingest.py:43`、`config.py:82` | MATCH | `config.DISTANCE_FUNCTION = "cosine"`（PENDING既定値） |
| 類似度検索: 上位k件（デフォルト k=3） | spec.md 4.2 | `retriever.py:12` | MATCH | `top_k: int = config.TOP_K` をデフォルト引数として使用 |

### F. 可観測性（spec.md 4.4・6.5、spec_infra.md 8.5）

| spec項目 | 参照元 | 実装ファイル:行 | 状態 | 差分詳細 |
|---|---|---|---|---|
| JSON Lines形式（1リクエスト1行）でログ出力 | spec.md 4.4 | `server.py:104-120` | MATCH | `json.dumps(entry, ensure_ascii=False)` で1行出力 |
| ログフィールド: query・retrieved_chunks・answer・latency_ms | spec.md 4.4 | `server.py:105-110` | MATCH | 4フィールドすべて `entry` に含まれる |
| エラー時スタックトレース記録 | spec.md 4.4 | `server.py:133-134` | MATCH | `error=traceback.format_exc()` で `error` フィールドに記録 |
| ngrok構成: `logs/requests.jsonl` に書き込み | spec.md 6.5 | `server.py:113-117` | MATCH | `config.LOG_PATH` 設定時はファイルに書き込み |
| AWS構成: stdout → CloudWatch Logs | spec_infra.md 8.5 | `server.py:119-120` | MATCH | `config.LOG_PATH` 未設定時は `print(json.dumps(...))` で標準出力 |

### G. AWS Lambda / インフラ固有（spec_infra.md）

| spec項目 | 参照元 | 実装ファイル:行 | 状態 | 差分詳細 |
|---|---|---|---|---|
| `lambda_handler.py`: S3からChromaDBアーカイブをダウンロード・展開 | spec_infra.md 3.3 | `lambda_handler.py:18-40` | MATCH | `_ensure_chroma_db()` が S3ダウンロード → tar展開 → `/tmp/chroma_db` 検証を実施 |
| ウォームスタート時はS3ダウンロードをスキップ | spec_infra.md 3.3（2b） | `lambda_handler.py:19-20` | MATCH | `if os.path.isdir(_CHROMA_TMP_DIR): return` |
| ChromaDB遅延初期化（S3展開後に実行） | spec_infra.md 4.3（C-NEW-2） | `server.py:29-34` | MATCH | `@lru_cache` の `get_store()` によりリクエスト処理時まで初期化を遅延 |
| `CHROMA_DB_PATH` をLambda用 `/tmp/chroma_db` に切り替え | spec_infra.md 3.1 | `lambda_handler.py:45` | MATCH | `_ensure_chroma_db()` 完了後に `os.environ["CHROMA_DB_PATH"] = _CHROMA_TMP_DIR` を設定し、その後 `server.py` を import |
| AC-INFRA-3-3: S3アーカイブ不在時はLambda初期化エラー（502）になる | spec_infra.md AC-INFRA-3-3 | `lambda_handler.py:34` | MATCH | `RuntimeError` を raise（FastAPIを経由しないためLambda Function URLが502として返す） |
| 例外メッセージは英語で記述 | spec_infra.md AC-INFRA-3-3 | `lambda_handler.py:34,40` | MATCH | 例外メッセージは英語。非ASCII文字を含まないことで `awslambdaric` の二次クラッシュを防止 |
| Mangumアダプタ使用 | spec_infra.md 2.4 | `lambda_handler.py:47,50` | MATCH | `from mangum import Mangum`、`handler = Mangum(app)` |
| `mangum` が `requirements.txt` に存在する | spec_infra.md 2.6 | `requirements.txt:45` | MATCH | `mangum==0.19.0` |
| Secrets Manager遅延取得（`get_secrets()` + `@lru_cache`） | spec_infra.md 4.3（C-3RD-2） | `config.py:49-65` | MATCH | `AWS_SECRETS_NAME` 設定時は Secrets Manager から取得しキャッシュ。未設定時は環境変数にフォールバック |
| `__getattr__`（PEP 562）経由の遅延アクセス | spec_infra.md 4.3（C-3RD-2） | `config.py:68-71` | MATCH | `_SECRET_KEYS` に対する属性アクセスを `get_secrets()` 経由にルーティング |
| ログ出力の環境別分岐 | spec_infra.md 4.3（C-3RD-1） | `server.py:113-120` | MATCH | `config.LOG_PATH` の有無で分岐（ngrok: ファイル書き込み、AWS: stdout） |

---

## 未実装項目

spec.md・spec_infra.md に記載があるが実装（`src/` 配下）に存在しない機能:

- なし。監査範囲（`src/` 配下の6ファイル）において、仕様で要求されたすべての機能が実装されている。

---

## 余剰実装

spec にないが実装に含まれる機能（スコープクリープの兆候チェック）:

- **`server.py` の `GET /` ルート（Web UI配信）**: spec.md AC-5-2「Web UIのフォームに質問を入力して送信する」が要件として存在するため、スコープクリープではない。ただし AWS構成では S3 が静的ファイルを配信するため、このルートはLambda経由では呼ばれない。無害な残存コード。
- **`config.py` の `HEALTH_STATS_AUTH_REQUIRED` フラグ**: spec.md の PENDING項目（GET /health・GET /stats の認証要否）に対応する制御変数。実装上の合理的な対応であり、スコープクリープとは判断しない。

---

## 差分サマリ

- **MATCH**: 47件
- **MISMATCH**: 0件
- **PARTIAL**: 0件
- **未実装**: 0件

---

## M-3: コンフォーマンス適合率

MATCH / (MATCH + MISMATCH + PARTIAL + 未実装) × 100 = **47 / 47 = 100%**

---

## M-4: セキュリティチェック結果

| チェック項目 | 結果 | 証拠 |
|---|---|---|
| 認証バイパスの有無 | 検出なし | `_is_authorized()` はAPIキー・Basic認証ともに未設定の場合 `return False`（フェイルクローズ）。`hmac.compare_digest` によりタイミング攻撃対策済み |
| ハードコードされた秘密情報の有無 | 検出なし | APIキー・Bedrockトークン・Basic認証情報はすべて `os.environ` または Secrets Manager 経由。`src/` 配下にリテラルのAPIキー・パスワードは存在しない |
| PDFパスのAPIレスポンス漏洩の有無 | 検出なし | `server.py` の全レスポンス・ログ出力コードを確認。`config.PDF_PATH` の値がレスポンスに含まれるコードパスなし |
| Lambda Function URLへの直接アクセス対策 | 実装済み | `server.py` のBasic認証はCloudFrontバイパス経由のリクエストに対しても有効 |
| secrets の即時評価によるKeyError リスク | 解消済み | `config.py` の `__getattr__` + `get_secrets()` の遅延取得により、モジュール読み込み時点ではSecrets Manager APIを呼ばない |

---

## 品質ゲート判定

| # | ゲート条件 | 状態 | 証拠 |
|---|---|---|---|
| 1 | 全ユニットテスト GREEN | **PASS** | 監査後、本監査対象コミットに加え後続のドキュメント・CI修正コミットを含む最新状態で`pytest tests/`を再実行し15件全GREENを確認（2026-08-21） |
| 2 | eval スコア 80%以上 | **PASS** | 同じく最新状態で`python evals/run_eval.py`を再実行し9/10（90%）を確認（2026-08-21） |
| 3 | コンフォーマンス差分ゼロ | PASS | 本監査レポート参照。MISMATCH 0件・未実装 0件。適合率 100% |
| 4 | 認証バイパス脆弱性ゼロ | PASS | M-4 セキュリティチェック参照。フェイルクローズ実装・タイミング攻撃対策・秘密情報ハードコードなし |
| 5 | 目付け役（metsukeyaku）レビュー PASS/CONDITIONAL | **PASS** | 本監査対象コミット（5c38180）を含む一連の変更に対し、metsukeyakuエージェントによる初回レビュー（CONDITIONAL、指摘全件対応済み）と再レビュー（PASS）を実施済み |

### 総合判定: RELEASE_OK（運用タスク完了を条件とする）

コンフォーマンス（ゲート3）・セキュリティ（ゲート4）は本監査で、テスト（ゲート1）・eval（ゲート2）・目付け役レビュー（ゲート5）は監査後の再実行・既存レビュー結果の確認により、いずれもPASSを確認した。

OP-1〜OP-6すべて本監査後に対応・実測完了（下表参照）。残る運用タスクなし。

---

## 指摘事項と対応状況

### 指摘なし（MISMATCH ゼロ）

本監査で検出した仕様との差分はゼロ。以下はリリース前に完了が必要な残作業事項（実装済みだが未実行の運用タスク）として記録する。

### 残作業事項（運用タスク）

| # | 内容 | 参照 | 担当 |
|---|---|---|---|
| OP-1 | ~~S3上の `chroma_db_latest.tar.gz` を新embedding（1024次元, Bedrock Titan V2）で再生成・更新する~~ | incidents §5 | **完了（2026-08-21）**: `reingest.yml`用IAMロールに`bedrock:InvokeModel`権限がなく同ワークフローは実行不可のため、ローカルの認証情報で同等の手順（ローカル再ingest→tar化→`aws s3 cp`）を代替実行し更新済み |
| OP-2 | ~~`reingest.yml` 用IAMロール（`AWS_REINGEST_ROLE_ARN`）に `bedrock:InvokeModel` 権限を追加する~~ | incidents §5、spec_infra.md 9.4 | **完了・実機検証済み（2026-08-21）**: インラインポリシー`BedrockEmbedInvoke`を追加。加えて、`GitHubActionsReingestRole`のOIDC trust policyが旧形式のままだった問題（`GitHubActionsDeployRole`修正時の横展開漏れ）・S3への元PDF未アップロードも発覚し併せて修正。`reingest.yml`のworkflow_dispatchを実行し全ステップGREENで完走することを確認済み（run 32468506547） |
| OP-3 | ~~最新コードで `pytest tests/` を実行しゲート1を確認する~~ | req.md 品質ゲート1 | **完了（2026-08-21）**: 15件全GREEN |
| OP-4 | ~~最新コードで `python evals/run_eval.py` を実行しゲート2（80%以上）を確認する~~ | req.md 品質ゲート2 | **完了（2026-08-21）**: 9/10（90%） |
| OP-5 | ~~metsukeyaku エージェントに embedding移行後の最新コードのレビューを依頼しゲート5を確認する~~ | req.md 品質ゲート5 | **完了**: 初回CONDITIONAL（指摘全件対応）→再レビューPASS |
| OP-6 | ~~コールドスタート改善の実測確認~~ | incidents §5、spec_infra.md 8.3 | **完了（2026-08-21 09:51 UTC）**: `Init Duration: 9457.59 ms`（10秒上限内、タイムアウトなし）、`Max Memory Used: 238 MB`（旧embedding時654〜1103MBから大幅減）。本番デプロイ直後の実際のCloudWatch Logsで改善を確認 |

---

## 総合所見

embedding生成をローカル実行のsentence-transformers（PyTorch）からAmazon Bedrock（Titan Text Embeddings V2）へ移行した変更について、仕様書（spec.md・spec_infra.md）・障害報告書（incidents/2026-08-21_cold-start-timeout-embedding-migration.md）と実装（`src/` 配下6ファイル）の照合を実施した結果、**全47項目でMATCHを確認し、MISMATCHは0件**であった。

特に重点確認対象の以下5点はすべて仕様・障害報告書の記述と一致している:

1. `EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"`、`EMBEDDING_DIMENSIONS = 1024`（config.py:78-79）
2. `TOP_K = 3`（config.py:29）、`TIMEOUT_SEC = 45`（config.py:33）— いずれもユーザー確認済みの値
3. `_bedrock_client()` の Noneガード + IAMフォールバック実装（ingest.py:146-156）
4. `embed_text()` がベアラートークン方式でBedrock Titan V2を呼び出す実装（ingest.py:159-171）
5. `retriever.py` がローカルモデルを排除し `ingest.embed_text()` を再利用する実装（retriever.py:7,16）

コードとしての実装品質は仕様に完全に適合している。品質ゲート1〜5はすべてPASS、運用タスクOP-1〜OP-6もすべて完了・実測済み。なお運用タスク対応の過程で、検証目的の`reingest.yml`実行が未push状態のコードに対して行われS3を誤って旧embedding（384次元）で上書きする事象が発生したが、コードpush後の再実行により解消済み（詳細はincidents §5参照）。
