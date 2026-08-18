# 仕様書（spec.md）

生成日: 2026-08-15
入力: req.md
生成エージェント: spec-writer

---

## 1. システム概要

「ハーネスエンジニアリング入門」講座PDF（harness_engineering_intro.pdf, 100ページ）を対象とした質問応答RAGシステムである。

システムはPDFをセクション単位でチャンク化し、sentence-transformersでembeddingに変換してChromaDB（ローカル永続化）に格納する。ユーザーからの自然言語質問に対して、ベクトル類似度検索で関連チャンクを上位k件取得し、Amazon Bedrock経由でClaudeをLLMバックエンドとして回答を生成する。FastAPIサーバーとしてローカル起動し、ngrokトンネルでHTTPS公開する。

**設計上の重要変更（req.md 変更履歴より）:**
当初はローカルLLM（bonsai-8b-mlx）を想定していたが、開発機がIntel Mac（x86_64）のためMLXフレームワークが動作しない。LLMバックエンドはAnthropic Claude APIに変更した。さらにその後、Amazon BedrockのAPIキー（ベアラートークン方式）経由でClaudeを呼び出す構成に変更した（ユーザー確認済み。AWS IAMアクセスキー/シークレットは使用しない）。NFR-4の「差し替え可能な設計」に従い、LLMバックエンドはインターフェース分離で実装する。

**基本特性:**
- ステートレスAPI（会話履歴を保持しない）
- コンテキスト外の知識で回答しない（ハルシネーション防止）
- 全リクエストをJSON Lines形式でログ出力する

---

## 2. API仕様

### 2.1 POST /ask

**目的:** 自然言語の質問を受け取り、PDF内容に基づく回答を返す

**認証:** 必須（APIキー認証。`X-API-Key` ヘッダーで指定する）

**リクエスト:**
```json
{
  "question": "string"
}
```

| フィールド | 型 | 必須 | 制約 |
|---|---|---|---|
| question | string | 必須 | 空文字不可 |

**レスポンス（200 OK）:**
```json
{
  "answer": "string",
  "sources": [
    {
      "page": "int",
      "section": "string",
      "title": "string"
    }
  ]
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| answer | string | 生成された回答文。PDF外の質問には「講座内容に該当する情報がありません」を含む文を返す |
| sources | array | 参照チャンクのメタデータ一覧（0件以上） |
| sources[].page | int | 参照ページ番号 |
| sources[].section | string | セクション識別子（例: "Section 1"） |
| sources[].title | string | スライドタイトル |

**エラーレスポンス:**

| HTTPステータス | 条件 |
|---|---|
| 400 | `question` フィールドが未指定または空文字 |
| 403 | 認証失敗・未認証（CLAUDE.md 5.2: 401は使用しない） |
| 500 | Anthropic Claude API呼び出し失敗、ChromaDB障害、その他内部エラー |

---

### 2.2 GET /health

**目的:** サーバーの死活監視

**認証:** [要確認] req.mdに認証要否の記載なし

**レスポンス（200 OK）:**
```json
{
  "status": "ok"
}
```

**エラーレスポンス:**

| HTTPステータス | 条件 |
|---|---|
| 500 | サーバー内部エラー |

---

### 2.3 GET /stats

**目的:** 取り込み済みデータの状態を返す

**認証:** [要確認] req.mdに認証要否の記載なし

**レスポンス（200 OK）:**
```json
{
  "chunk_count": "int",
  "last_updated": "string"
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| chunk_count | int | ChromaDBに格納済みのチャンク総数 |
| last_updated | string | 最終取り込み日時 [要確認] フォーマット未指定（ISO 8601を想定） |

**エラーレスポンス:**

| HTTPステータス | 条件 |
|---|---|
| 500 | ChromaDB参照失敗、その他内部エラー |

---

## 3. データモデル

### 3.1 チャンク構造

PDFを分割した1チャンクが保持するフィールド定義を以下に示す。

| フィールド | 型 | 必須 | 制約 | 説明 |
|---|---|---|---|---|
| content | string | 必須 | 空文字不可 | チャンクの本文テキスト |
| section_number | string | 必須 | 空文字不可 | セクション識別子（例: "Section 0", "Section 1", "Capstone"） |
| page_number | int | 必須 | 1以上 | PDFのページ番号 |
| title | string | 必須 | 空文字不可 | スライドタイトル |
| embedding | vector | 必須 | — | sentence-transformersが生成するベクトル [要確認] 次元数未指定 |

**備考:**
- チャンク分割はセクション単位（Section 0〜7 および Capstone）で意味的に行う
- [要確認] チャンクサイズ（文字数）および重複（overlap）パラメータはreq.mdに未記載
- ChromaDBへの永続化パスは `data/chroma_db/`
- PDFファイルの絶対パスはいかなるレスポンス・ログにも含めない

---

## 4. 処理フロー

### 4.1 取り込みフロー（ingest.py）

```
1. PDF読み込み
   - PyMuPDFでharness_engineering_intro.pdfを開く
   - 全100ページを対象とする

2. チャンク分割
   - セクション単位（Section 0〜7, Capstone）で分割する
   - [要確認] セクション境界の検出方法（ページヘッダー・目次解析 等）はreq.mdに未記載

3. メタデータ付与
   - 各チャンクにsection_number, page_number, titleを付与する

4. Embedding生成
   - sentence-transformersを使用してチャンクをベクトルに変換する
   - [要確認] 使用するembeddingモデル名はreq.mdに未記載

5. ベクトルDB格納
   - ChromaDBのコレクションにチャンクとembeddingを保存する
   - 永続化先: data/chroma_db/
```

**事後確認:** 格納後、チャンク数が10以上であること（AC-1）

---

### 4.2 検索フロー（retriever.py）

```
1. クエリembedding生成
   - ユーザーの質問文をsentence-transformersでベクトルに変換する

2. 類似度検索
   - ChromaDBでコサイン類似度（または同等の距離関数）により検索する
   - [要確認] 距離関数の種類はreq.mdに未記載
   - 上位k件を返す（デフォルト k=5。当初k=3だったが、evalスコア70%止まりだったためk=5に変更。CLAUDE.md 5.1参照）

3. 結果返却
   - 各チャンクのcontent, section_number, page_number, titleを含めて返す
```

---

### 4.3 生成フロー（generator.py）

```
1. プロンプト構築
   - システムプロンプト: 「提供されたコンテキストのみを使用して回答すること。
     コンテキストに情報がない場合は「講座内容に該当する情報がありません」と答えること」
   - コンテキスト: 取得したチャンク上位k件のcontent（全文を流し込まない設計）
   - ユーザーターン: 質問文

2. Amazon Bedrock経由でClaude呼び出し
   - anthropic SDKの `AnthropicBedrock` クライアントを使用する（ベアラートークン方式のBedrock APIキー認証。ユーザー確認済み。boto3への直接依存はしない）
   - 使用するモデルはclaude-sonnet-4.6（ユーザー確認済み）。BedrockモデルID表記は `jp.anthropic.claude-sonnet-4-6`（東京リージョン）。[要確認] 実機での疎通検証が必要
   - LLMバックエンドはインターフェース分離で実装する（NFR-4）

3. レスポンス整形
   - 回答文に参照元ページ番号を付記する
   - sources配列にsection_number, page_number, titleを格納する
```

---

### 4.4 ロギング

全リクエストについて以下をJSON Lines形式（1リクエスト1行）で `logs/requests.jsonl` に記録する:
- query（質問文）
- retrieved_chunks（検索結果チャンク一覧）
- answer（生成回答）
- latency_ms（応答生成にかかったミリ秒）
- エラー発生時はスタックトレースを含める

---

## 5. 受け入れ基準（検証可能形式）

req.mdに記載されたAC-1〜AC-5の全項目を「入力 | 操作 | 期待出力」形式で定義する。

### AC-1: PDF取り込み

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-1-1 | harness_engineering_intro.pdf（100ページ） | ingest.pyを実行してPDFを取り込む | ChromaDBに格納されたチャンク数が10以上であること |
| AC-1-2 | harness_engineering_intro.pdf（100ページ） | ingest.pyを実行してPDFを取り込む | 格納された全チャンクがsection_number, page_number, titleの3フィールドをすべて持ち、いずれも空でないこと |

---

### AC-2: 検索精度

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-2-1 | question: "ハーネス設計の5本柱とは？" | retriever.pyで上位5件を検索する | 返された5件のうち少なくとも1件のsection_numberが "Section 1" であること |
| AC-2-2 | question: "コンフォーマンス監査とは？" | retriever.pyで上位5件を検索する | 返された5件のうち少なくとも1件のsection_numberが "Section 6" であること |
| AC-2-3 | question: "rippable harnessとは？" | retriever.pyで上位5件を検索する | 返された5件のうち少なくとも1件のsection_numberが "Section 7" であること |

---

### AC-3: 回答品質

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-3-1 | question: PDFに記載のある任意の質問（例: "ハーネス設計の5本柱とは？"） | POST /ask を呼ぶ | レスポンスのsources配列が1件以上あり、各要素にpage（int）が含まれること |
| AC-3-2 | question: PDFに記載のない質問（例: "この講座に関係ない質問です"） | POST /ask を呼ぶ | answerフィールドに「講座内容に該当する情報がありません」を含む文字列が返ること |
| AC-3-3 | question: 日本語の任意の質問文 | POST /ask を呼ぶ | answerフィールドが日本語で返ること |

---

### AC-4: API動作

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-4-1 | question: "FDEとは何ですか？"（認証済みリクエスト） | POST /ask を呼ぶ | HTTPステータス200、レスポンスボディが {"answer": "string", "sources": [...]} の形式であること |
| AC-4-2 | （リクエストボディなし、認証済み） | GET /health を呼ぶ | HTTPステータス200、レスポンスボディが {"status": "ok"} であること |
| AC-4-3 | 認証ヘッダーなし（`X-API-Key` 不提供） | POST /ask を呼ぶ | HTTPステータス403が返ること |

---

### AC-5: ngrok公開

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-5-1 | ngrok起動済みのHTTPS URL | ブラウザまたはcurlでngrok URLに対してPOST /ask を呼ぶ | HTTPステータス200が返り、answerフィールドに回答文字列が含まれること |
| AC-5-2 | ngrok URLにブラウザでアクセス | Web UIのフォームに質問を入力して送信する | 画面上に回答テキストが表示されること |

---

## 6. 制約と前提

### 6.1 技術スタック

| コンポーネント | 技術 | バージョン / 備考 |
|---|---|---|
| 実装言語 | Python | 3.11以上 |
| PDF読み込み | PyMuPDF | — |
| Embedding生成 | sentence-transformers | [要確認] モデル名未指定 |
| ベクトルストア | ChromaDB | 永続化パス: data/chroma_db/ |
| LLMバックエンド | Amazon Bedrock経由のClaude Sonnet 4.6 | anthropic SDKの `AnthropicBedrock`（ベアラートークン方式のBedrock APIキー認証）。モデルID: `jp.anthropic.claude-sonnet-4-6`（東京リージョン、確定値）。[要確認] 実機疎通は未検証 |
| APIサーバー | FastAPI + Uvicorn | — |
| トンネル公開 | ngrok | HTTPS URL |

### 6.2 環境前提

- 開発機: Intel Mac（x86_64）。MLXフレームワーク（Apple Silicon専用）は使用不可
- Amazon BedrockのAPIキー（ベアラートークン、`AWS_BEARER_TOKEN_BEDROCK`）とリージョン（`AWS_REGION`）が環境変数または.envファイルで設定されていること（確定値。AWS IAMアクセスキー/シークレットは使用しない）
- APIキー・トークン類はソースコードにハードコードしない
- PDFファイル `harness_engineering_intro.pdf` はプロジェクトルート直下に配置済みであること（確定値。`config.py` の `PDF_PATH` で管理する）

### 6.3 パフォーマンス要件

| 項目 | 要件値 |
|---|---|
| 回答生成レイテンシ（POST /ask） | 60秒以内（外部API呼び出しのネットワーク遅延を含む） |

### 6.4 セキュリティ要件

- ngrok公開時、APIキー認証（`X-API-Key` ヘッダー）でアクセスを制限する（確定値）
- PDFファイルの絶対パスをAPIレスポンス・ログに含めない

### 6.5 可観測性要件

- 全APIリクエストのquery, retrieved_chunks, answer, latency_msをログ出力する
- ログ形式: JSON Lines（1リクエスト1行）
- ログ出力先: `logs/requests.jsonl`
- エラー時はスタックトレースを含めてログに記録する

### 6.6 差し替え可能性要件（NFR-4）

以下のコンポーネントはインターフェース分離により、実装を差し替え可能にする:
- LLMバックエンド: Anthropic Claude API以外に切り替え可能
- ベクトルDB: ChromaDB以外に切り替え可能
- トンネルツール: ngrok以外に切り替え可能

### 6.7 ディレクトリ構成（CLAUDE.md準拠）

```
FDE_ENTRY_HO/
├── CLAUDE.md
├── req.md
├── spec.md
├── src/
│   ├── ingest.py
│   ├── retriever.py
│   ├── generator.py
│   ├── server.py
│   └── config.py
├── tests/
│   ├── test_ingest.py
│   ├── test_retriever.py
│   ├── test_generator.py
│   └── test_server.py
├── evals/
│   ├── eval_set.json
│   └── run_eval.py
├── audit/
│   └── conformance_report.md
├── templates/
│   └── index.html
├── data/
│   └── chroma_db/
├── logs/
│   └── requests.jsonl
└── requirements.txt
```

### 6.8 品質ゲート（リリース条件）

ngrok公開前に以下の全条件を満たすこと:
1. 全ユニットテスト GREEN
2. evalスコア 80%以上（eval_set.jsonの全10問で計測）
3. コンフォーマンス監査 差分ゼロ（spec vs 実装）
4. 認証バイパスの脆弱性ゼロ
5. 目付け役（metsukeyaku）のレビューが PASS または CONDITIONAL

---

## 付記: [要確認] 項目一覧

### 解消済み（ユーザー確認済み・確定値）

| # | 箇所 | 内容 | 確定値 |
|---|---|---|---|
| 10 | 6.2 環境前提 | PDFファイルの配置パス | プロジェクトルート直下（`config.py` の `PDF_PATH` で管理） |
| 11 | 6.4 セキュリティ / 2.1 POST /ask | 認証方式 | APIキー認証のみ（`X-API-Key` ヘッダー） |
| 12 | 1 システム概要 / 6.1 技術スタック | LLMバックエンドの呼び出し経路 | Amazon Bedrock経由（`AnthropicBedrock`、ベアラートークン方式のBedrock APIキー認証。AWS IAMアクセスキー/シークレットは不使用） |
| 13 | 6.1 技術スタック | AWSリージョン | 東京リージョン（`ap-northeast-1`） |
| 14 | 4.3 生成フロー / 6.1 技術スタック | 使用モデル | claude-sonnet-4.6（Bedrock表記: `jp.anthropic.claude-sonnet-4-6`） |
| 15 | 4.2 検索フロー / AC-2 | 検索上位k件（TOP_K） | 5件（当初3件だったが、eval実行でSection 5・Capstoneの正解チャンクが上位3件に入らずスコア70%だったため5に変更） |

### 未解決（CLAUDE.md 5.2 PENDING区分。config.py実装時に既定値をコメント付きで記録し、実装はブロックしない）

| # | 箇所 | 内容 |
|---|---|---|
| 1 | 2.2 GET /health | 認証要否がreq.mdに記載なし（既定: 認証不要） |
| 2 | 2.3 GET /stats | 認証要否がreq.mdに記載なし（既定: 認証不要） |
| 3 | 2.3 GET /stats | last_updatedフィールドのフォーマット（ISO 8601と仮定） |
| 4 | 3.1 チャンク構造 | embeddingの次元数未指定 |
| 5 | 4.1 取り込みフロー | セクション境界の検出方法（ページヘッダー解析か目次解析か等） |
| 6 | 4.1 取り込みフロー | チャンクサイズ（文字数）および重複（overlap）パラメータ |
| 7 | 4.1 取り込みフロー | 使用するembeddingモデル名 |
| 8 | 4.2 検索フロー | ChromaDBの距離関数の種類 |
| 9 | 4.3 生成フロー | BedrockモデルID `jp.anthropic.claude-sonnet-4-6` の実機での疎通検証が未実施 |
