# コンフォーマンス監査レポート

## 監査日時: 2026-08-18 (Phase E / Step 10)

## 監査者: auditor エージェント

## 対象コミットハッシュ: 284cb57 (eval設定)

---

## 仕様 vs 実装 照合結果

### 2章 API仕様

| spec項目 | 実装ファイル（行番号） | 状態 | 差分詳細 |
|---|---|---|---|
| POST /ask エンドポイント定義 | src/server.py:65 | MATCH | - |
| POST /ask X-API-Key認証必須 | src/server.py:41-43, 66 | MATCH | - |
| POST /ask リクエストボディ（question: string, 空文字不可） | src/server.py:26-27, 67-68 | MATCH | - |
| POST /ask レスポンス200（answer, sources[{page,section,title}]） | src/server.py:30-38, 82-86 | MATCH | - |
| POST /ask エラー400（question未指定/空文字） | src/server.py:67-68 | MATCH | - |
| POST /ask エラー403（認証失敗・未認証） | src/server.py:43 | MATCH | 401不使用・403で統一 |
| POST /ask エラー500（内部エラー） | src/server.py:77 | MATCH | - |
| HTTPステータスコード200/400/403/500のみ使用 | src/server.py:25-29 | MATCH | RequestValidationError用の`@app.exception_handler`を追加し、malformed JSON/型不正時も422ではなく400を返すよう修正済み（監査後の追補対応）。curlで実機確認済み |
| GET /health エンドポイント定義 | src/server.py:89-91 | MATCH | - |
| GET /health 認証不要（PENDING既定値） | src/server.py:46-48, 90 | MATCH | HEALTH_STATS_AUTH_REQUIRED=False |
| GET /health レスポンス{"status":"ok"} | src/server.py:91 | MATCH | - |
| GET /stats エンドポイント定義 | src/server.py:94-106 | MATCH | - |
| GET /stats 認証不要（PENDING既定値） | src/server.py:46-48, 95 | MATCH | - |
| GET /stats レスポンス（chunk_count: int, last_updated: string） | src/server.py:103-104 | MATCH | - |
| GET /stats last_updated ISO 8601形式（PENDING既定値） | src/config.py:35 | MATCH | - |

### 3章 データモデル

| spec項目 | 実装ファイル（行番号） | 状態 | 差分詳細 |
|---|---|---|---|
| チャンク: content フィールド | src/ingest.py:128 | MATCH | - |
| チャンク: section_number フィールド | src/ingest.py:128 | MATCH | - |
| チャンク: page_number フィールド（int, 1以上） | src/ingest.py:125-127 | MATCH | - |
| チャンク: title フィールド | src/ingest.py:124 | MATCH | - |
| チャンク: embedding（SentenceTransformer生成） | src/ingest.py:143-144 | MATCH | - |
| ChromaDB永続化パス data/chroma_db/ | src/config.py:15, src/ingest.py:37 | MATCH | - |
| PDFパスをレスポンス・ログに含めない | src/server.py, src/ingest.py | MATCH | レスポンス・ログにPDF_PATHは混入していない |

### 4章 処理フロー

| spec項目 | 実装ファイル（行番号） | 状態 | 差分詳細 |
|---|---|---|---|
| PDF読み込み（PyMuPDF/fitz） | src/ingest.py:12, 115 | MATCH | - |
| セクション単位チャンク分割（Section 0〜7, Capstone） | src/ingest.py:78-111 | MATCH | - |
| メタデータ付与（section_number, page_number, title） | src/ingest.py:122-134 | MATCH | - |
| Embedding生成（SentenceTransformer） | src/ingest.py:143 | MATCH | - |
| ChromaDB upsert保存 | src/ingest.py:44-58 | MATCH | - |
| クエリembedding生成（retriever） | src/retriever.py:25 | MATCH | - |
| コサイン類似度検索（PENDING既定値） | src/config.py:32, src/ingest.py:39-41 | MATCH | DISTANCE_FUNCTION="cosine" |
| TOP_K=5（evalでk=3→5に変更、確定値） | src/config.py:17 | MATCH | spec.md付記#15と一致 |
| システムプロンプト（コンテキスト外知識不使用） | src/generator.py:9-16 | MATCH | - |
| システムプロンプト（日本語で回答） | src/generator.py:11 | MATCH | - |
| システムプロンプト（「講座内容に該当する情報がありません」文言） | src/generator.py:13-15 | MATCH | - |
| Amazon Bedrock（AnthropicBedrock）経由呼び出し | src/generator.py:4, 27-31 | MATCH | ベアラートークン方式 |
| 外部API 60秒タイムアウト | src/config.py:18, src/generator.py:31 | MATCH | TIMEOUT_SECをAnthropicBedrockに渡す |
| ロギング JSON Lines形式（1リクエスト1行） | src/server.py:51-62 | MATCH | - |
| ロギング出力先 logs/requests.jsonl | src/config.py:16 | MATCH | - |
| ロギング項目（query, retrieved_chunks, answer, latency_ms） | src/server.py:52-57 | MATCH | - |
| ロギング エラー時スタックトレース | src/server.py:75-76 | MATCH | traceback.format_exc()使用 |

### 6章 制約と前提（NFR）

| spec項目 | 実装ファイル（行番号） | 状態 | 差分詳細 |
|---|---|---|---|
| NFR-4 LLMバックエンド抽象化（LLMBackendProtocol） | src/generator.py:19-21 | MATCH | Protocol定義済み、generate_answer()が引数で受け取る |
| NFR-4 ベクトルDB抽象化（VectorStoreProtocol） | src/ingest.py:28-31 | MATCH | Protocol定義済み |
| NFR-4 server.pyがanthropicに直接依存しない | src/server.py | MATCH | import anthropicなし |
| NFR-4 server.pyがchromadbに直接依存しない | src/server.py | MATCH | import chromadbなし（ingest.ChromaVectorStoreを介す） |
| APIキーのハードコード禁止 | src/config.py:21, 25 | MATCH | os.environ["APP_API_KEY"]等で環境変数から取得 |
| PDF_PATH管理（config.pyのPDF_PATH） | src/config.py:14 | MATCH | - |
| ディレクトリ構成（CLAUDE.md準拠） | ファイルシステム | MATCH | src/, tests/, evals/, templates/, data/chroma_db/, logs/requests.jsonl 全て存在。audit/は本監査で新規作成 |

---

## 未実装項目
なし

## 余剰実装
なし（スコープクリープなし）

---

## 差分サマリ

- MATCH: **43件**
- PARTIAL: **0件**（FastAPI 422ステータスコード問題は監査後に追補対応済み。RequestValidationErrorハンドラーを追加し400に変換）
- MISMATCH: **0件**
- 未実装: **0件**

---

## 品質メトリクス

### M-1: テスト通過率

実行コマンド: `PYTHONPATH=src .venv/bin/python -m pytest tests/ -v`

| カテゴリ | テスト数 |
|---|---|
| 全テスト数 | 11 |
| 通過数 | 11 |
| 失敗数 | 0 |

**結果: 11/11 PASS（100%）**

内訳:
- test_generator.py: 2/2 PASS
- test_ingest.py: 2/2 PASS
- test_retriever.py: 3/3 PASS
- test_server.py: 4/4 PASS

### M-2: eval スコア

実行コマンド: `PYTHONPATH=src .venv/bin/python evals/run_eval.py`

| # | 質問 | 結果 |
|---|---|---|
| 1 | FDEとは何ですか？ | PASS |
| 2 | ハーネス設計の5本柱を教えてください | PASS |
| 3 | Spec-Driven Developmentとは？ | PASS |
| 4 | フィードフォワード設計の目的は？ | PASS |
| 5 | 品質ゲートとは？ | PASS |
| 6 | testとevalの違いは？ | PASS |
| 7 | コンフォーマンス監査とは？ | PASS |
| 8 | rippable harnessとは？ | PASS |
| 9 | Capstoneの評価観点は？ | FAIL（期待キーワード「仕様の質, 制御の質, 検証の質, 監査と判断」が回答に含まれなかった。Capstoneページのコンテキストに該当キーワードが存在しないことが原因） |
| 10 | この講座に関係ない質問です | PASS |

**スコア: 9/10（90%） → 合格基準80%以上 PASS**

### M-3: コンフォーマンス適合率

MATCH / (MATCH + PARTIAL + MISMATCH + 未実装) × 100 = 43 / 43 × 100 = **100%**（追補対応後）

### M-4: セキュリティチェック

| チェック項目 | 結果 | 詳細 |
|---|---|---|
| 認証バイパスの有無 | なし | `_require_api_key`はx_api_key != config.API_KEYで厳密に判定。NoneをAPIキーとして受理しない |
| ハードコードされた秘密情報の有無 | なし | APP_API_KEY・AWS_BEARER_TOKEN_BEDROCKはos.environ["..."]で環境変数から取得。ソースコードに値なし |
| PDFパスのAPIレスポンス漏洩の有無 | なし | レスポンスはanswer/sourcesのみ。sources要素はpage/section/titleのみ（PDF_PATHを含まない） |
| PDFパスのログ漏洩の有無 | なし | _log_request()はquery/retrieved_chunks/answer/latency_ms/errorのみ記録 |
| 禁止コマンド（rm -rf等）の使用 | なし | ソースコード内に該当なし |

---

## 品質ゲート判定

| # | ゲート条件 | 状態 | 証拠 |
|---|---|---|---|
| 1 | 全ユニットテスト GREEN | **PASS** | pytest実行結果: 11/11 PASSED（実行時間62.55s） |
| 2 | eval スコア 80%以上 | **PASS** | eval実行結果: 9/10 = 90%（合格基準: 80%） |
| 3 | コンフォーマンス差分ゼロ | **PASS** | 監査後にRequestValidationErrorハンドラーを追加し400に変換する修正を実施。curlで malformed JSON / question型不正の両ケースが400（422ではない）を返すことを実機確認済み。pytest再実行（11/11 PASS）でも回帰なしを確認 |
| 4 | 認証バイパス脆弱性ゼロ | **PASS** | セキュリティチェック完了。バイパス経路なし |
| 5 | 目付け役（metsukeyaku）レビュー PASS または CONDITIONAL | **PASS**（CONDITIONAL条件はユーザーがリスク受容し解消） | Step11で実施。認証バイパス検査5パターン全て403（PASS）。CONDITIONAL条件（下記）はユーザー確認済み |

### 総合判定: RELEASE_OK（品質ゲート1〜5、全条件PASS）

## Step 11: 目付け役（metsukeyaku）レビュー結果

### 認証バイパス検査（5パターン + 参考1件）

| # | パターン | 期待 | 結果 |
|---|---|---|---|
| 1 | `X-API-Key` ヘッダーなし | 403 | 403 PASS |
| 2 | `X-API-Key` に空文字 | 403 | 403 PASS |
| 3 | `X-API-Key` にランダム文字列 | 403 | 403 PASS |
| 4 | 正しいキーの大文字小文字を変えた値 | 403 | 403 PASS |
| 5 | `Authorization: Bearer <正しいキー>` で送信（X-API-Keyなし） | 403 | 403 PASS |
| 参考 | 正規の `X-API-Key` で送信 | 200 | 200 PASS |

`POST /ask` への直接的な認証バイパス経路は検出されなかった。

### レビュー判定: CONDITIONAL → ユーザー確認によりPASSへ解消

**CONDITIONAL条件（要検討事項）:** `GET /`（Web UI）が認証なしでHTMLを返し、そのHTML内のJavaScriptに `config.API_KEY` の実値が `json.dumps()` で埋め込まれている（src/server.py）。ngrok URLを知る第三者が `GET /` にアクセスするだけでPOST /ask用のAPIキーを取得できる。

- 根拠: req.md NFR-2（APIキーでアクセス制限）の実効性低下
- 背景: req.md AC-5-2（Web UIで質問→回答）を満たすにはブラウザ側にキーを渡す必要があり、req.md自体に内在する要件間のトレードオフ
- 代替案（提示のみ）: サーバーサイド中継エンドポイント（`POST /web-ask` 等）を追加しAPIキーをブラウザに渡さない方式
- **ユーザー判断: リスクを受容し現行実装のまま維持する（代替案は不採用）**

### 軽微な指摘と対応状況

| # | 指摘 | 対応 |
|---|---|---|
| 1 | req.md FR-2本文が「デフォルト3件」のまま未更新 | 対応済み。「デフォルト5件」に修正、変更履歴参照を追記 |
| 2 | 監査レポートのファイル名について、CLAUDE.md（静的名）と `.claude/agents/auditor.md`（`conformance_report_YYMMDDHH_XXXX.md` 命名規則）が不一致 | 対応済み。auditor.mdの命名規則を正としてCLAUDE.md・spec.md・release-manager.md・手順書.mdを統一。本ファイルも `conformance_report_26081817_0001.md` にリネーム |
| 3 | `tests/test_retriever.py` のテスト関数名が「上位3件」のまま（実際はTOP_K=5で上位5件） | 対応済み。「上位5件」に一括置換 |
| 4 | APIキー比較が定数時間比較でない（タイミング攻撃への理論上の弱さ） | 対応済み。`hmac.compare_digest()` に変更 |

### 見落とし候補（対応せず、既知の制約として記録）

- `question` フィールドに最大長制限がない（spec.md未規定のため対応せず。将来の本番運用時に検討）
- `GET /stats` の `last_updated` はChromaDB内部ファイルのmtimeに依存（ChromaDBのバージョンアップで変わる可能性。spec.mdはフォーマットのみ規定でこの点は未規定）
- ログファイル追記は単一プロセス前提（マルチワーカー構成にする場合は書き込み競合対策が必要）
- `BedrockLLMBackend` はリクエストごとに再生成（NFR-4の抽象化設計とのトレードオフ。性能上の非効率だが機能上の問題はない）

### 良い判断の認知（目付け役コメントより）

- NFR-4のProtocol抽象化設計は適切でSimplicity Firstに反しない
- RequestValidationErrorハンドラーの追加は正しい対処
- eval Q5の差し替え（PDFに存在しない用語→実在する用語）は正当な判断
- TOP_K 3→5の変更はデータドリブンでCLAUDE.md/req.md/spec.mdを整合的に更新できている
- Bedrock経由への変更はNFR-4に従いProtocolベースで実装されている

### 追補対応の記録:
- 指摘: spec.mdでは `POST /ask` のエラーレスポンスとして400/403/500のみを規定しているが、FastAPIのデフォルト動作としてPydantic ValidationError（422）が返る経路が残存していた（malformed JSONボディ、question型不正など）。
- 対処: `src/server.py` に `@app.exception_handler(RequestValidationError)` を追加し、422を400に変換するハンドラーを実装。
- 検証: `curl` で `{invalid json` （構文エラー）・`{"question": 123}` （型不正）の両方が `HTTP 400` を返すことを確認。`pytest tests/` 再実行で11/11 PASS（回帰なし）を確認。

---

## 指摘事項と対応状況

| # | 指摘事項 | 重要度 | 対応状況 |
|---|---|---|---|
| 1 | FastAPI 422 ステータスコードが仕様外（spec.mdは200/400/403/500のみ規定） | Medium | **対応済み**。`exception_handler`（RequestValidationError → 400変換）を追加し実機確認済み |

---

## 総合所見

全体的に仕様との整合性は高く（追補対応後の適合率100%）、主要な機能要件・非機能要件は正しく実装されている。

セキュリティ面では APIキーのハードコードなし、PDFパス漏洩なし、認証バイパスなし と適切に実装されている。

テスト通過率は11/11（100%）、evalスコアは90%（9/10）であり、いずれも合格基準を満たしている。

監査時点で発見されたFastAPIフレームワークの422レスポンス問題は、RequestValidationErrorハンドラーの追加により即日対処し、実機確認済み。品質ゲート1〜4は全てPASSした。

ゲート5（目付け役レビュー）はStep11で実施予定であり、本時点では判定保留とする。
