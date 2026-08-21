# CLAUDE.md

ハーネスエンジニアリング入門 講座PDF RAGシステムの開発プロジェクト。
Andrej Karpathy の行動指針をベースに、本講座の7セクションの概念をすべて組み込む。

## 1. Think Before Coding

**仮定を置くな。混乱を隠すな。トレードオフを表に出せ。**

実装の前に:
- 前提条件を明示的に述べよ。不確かなら聞け。
- 複数の解釈がありうるなら、黙って選ぶな。提示せよ。
- よりシンプルなアプローチがあるなら、それを言え。必要なら押し返せ。
- 不明点があったら止まれ。何がわからないか名前をつけて聞け。

## 2. Simplicity First

**問題を解く最小限のコード。投機的な実装はゼロ。**

- 頼まれていない機能を追加するな。
- 一度しか使わないコードに抽象化を入れるな。
- 頼まれていない「柔軟性」「設定可能性」を作るな。
- 起こり得ないシナリオのエラーハンドリングを書くな。
- 200行で書いて50行で済むなら、書き直せ。

自問: 「シニアエンジニアがこれを見て"複雑すぎる"と言うか？」 Yesなら簡素化せよ。

## 3. Surgical Changes

**必要な箇所だけ触れ。自分の散らかしだけ片付けろ。**

既存コードを編集する時:
- 隣接するコード・コメント・フォーマットを「改善」するな。
- 壊れていないものをリファクタリングするな。
- 自分のやり方と違っても、既存スタイルに合わせよ。
- 無関係なデッドコードに気づいたら言及はするが、削除するな。

テスト: 変更した全行が、ユーザーの依頼に直接紐づくこと。

## 4. Goal-Driven Execution

**成功基準を定義し、検証するまでループせよ。**

タスクを検証可能なゴールに変換する:
- 「バリデーション追加」→「不正入力のテストを書き、通るようにする」
- 「バグ修正」→「再現テストを書き、通るようにする」
- 「リファクタリング」→「テストがリファクタ前後で通ることを確認」

複数ステップのタスクでは簡潔な計画を述べよ:
```
1. [ステップ] → 検証: [チェック項目]
2. [ステップ] → 検証: [チェック項目]
3. [ステップ] → 検証: [チェック項目]
```

---

## 5. ハーネスエンジニアリング固有ルール

### 5.1 コンテキスト設計（柱1）
- LLMに渡すコンテキストは必要最小限にする
- RAGの検索結果は上位k件に絞り、全文を流し込まない（kのデフォルトは3とし、`config.py` の `TOP_K` 定数で管理する。3→5→3と変更を経ている。変更経緯はincidents/2026-08-21_cold-start-timeout-embedding-migration.md参照。ユーザー確認済み）
- システムプロンプトに講座外の知識で回答しない旨を明記する
- コンテキストに該当情報がない場合は「講座内容に該当する情報がありません」という文言を含む日本語で回答するよう、システムプロンプトに明記する
- 回答は常に日本語で生成する（英語での回答は禁止）

### 5.2 制約設計 / フィードフォワード（柱2）
- 実装前に必ず `req.md` の受け入れ基準を確認する。AWS構成を採用する場合は `spec_infra.md` の受け入れ基準（7章）も確認する
- 新規ファイル作成時は、このCLAUDE.mdの制約に違反しないか確認する
- spec.md に残る `[要確認]` 項目は、以下の3段階で扱う。値を無断で確定させたまま実装を進めない:
  1. **確定値**: ユーザーに確認済みの値。`config.py` に定数として記録する。`POST /ask` の認証方式: **ngrok構成ではAPIキー認証（`X-API-Key`ヘッダー、既存実装・監査済み。spec.md 6.4章に記録）を維持する。AWS構成ではこれとは別方式としてBasic認証を採用する**（ユーザー確認済み。spec_infra.md 4章に記録。FastAPI層は`hmac.compare_digest`によるタイミング攻撃対策必須。CloudFront Functions層はJSランタイムに`crypto.timingSafeEqual`相当の機能がなくタイミング安全な比較を実装できないため、通常の文字列比較（`!==`）を使用する—FastAPI層が第2防衛線として機能するため実質的リスクは軽微と判断。spec_infra.md 8.7章参照）。両者は別デプロイ構成向けの別方式であり、一方が他方を置き換えるものではない。LLMモデル: claude-sonnet-4.6（Bedrock表記: `jp.anthropic.claude-sonnet-4-6`、東京リージョン、ユーザー確認済み。spec.md付記#14）。PDFファイル配置パス: プロジェクトルート直下（`config.py` の `PDF_PATH`、ユーザー確認済み。spec.md付記#10）
  2. **推奨デフォルト値（PENDING）**: 未確認だが実装を進めるための合理的な既定値がある項目。`config.py` に `# [PENDING] ユーザー未確認。デフォルト値を使用中` というコメント付きで記載し、実装をブロックしない。対象: embeddingモデル名（現在: Amazon Bedrock Titan Text Embeddings V2, `amazon.titan-embed-text-v2:0`。元はsentence-transformers。incidents/参照）、embedding次元数（現在1024次元、`config.EMBEDDING_DIMENSIONS`）、チャンクサイズ/overlap、距離関数、セクション境界検出方法、`GET /health`・`GET /stats` の認証要否（既定は認証不要）、`last_updated` のフォーマット（既定はISO 8601）
  3. **ブロック値**: 合理的な推測が不可能、またはセキュリティ・データ配置に直結する項目。値が確定するまで `raise NotImplementedError("[要確認] ...")` で実装をブロックする。現時点で該当項目なし
- LLMバックエンド（generator.py）とベクトルDB（retriever.py・ingest.py）は抽象インターフェース（Python Protocolまたは抽象基底クラス）を介して実装し、Anthropic ClaudeやChromaDBへの直接依存を `server.py` に書かない（NFR-4: 剥がせる設計）
- ngrokはCLIツール呼び出しのため、Protocol等による抽象化は行わない（Simplicity First優先）。起動コマンド・パラメータは `config.py` の定数として外出しし、`server.py` に直書きしない程度の疎結合で足りる（NFR-4）
- APIエンドポイントのエラーはFastAPIの `HTTPException` のみで表現し、使用するステータスコードは200/400/403/500に限定する（401は使用しない。認証失敗・未認証は常に403で統一する）
- `POST /ask` は認証必須とする（**確定**: ngrok構成はAPIキー認証、AWS構成はBasic認証。FastAPI層は`hmac.compare_digest`によるタイミング攻撃対策を使用する。AWS構成のCloudFront Functions層は通常の文字列比較を使用する—spec_infra.md 8.7章参照）。未認証・認証失敗時は403を返す（**例外**: AWS構成のCloudFront Functions層はブラウザの認証ダイアログ表示のため401を使用する。CloudFront層はFastAPIの外側でありこの規定の適用範囲外と解釈する。spec_infra.md 8.7章参照）。`GET /health`・`GET /stats` の認証要否は上記PENDINGの既定（認証不要）に従う
- 以下のディレクトリ構成を厳守する:

```
FDE_ENTRY_HO/
├── CLAUDE.md
├── req.md
├── spec.md              (要件から生成)
├── spec_infra.md        (AWSサーバーレス構成のインフラ仕様。AWS構成採用時のみ参照)
├── data/
│   ├── chroma_db/       (ベクトルDB永続化先、5.4。ngrok構成のみ。AWS構成ではS3が永続化の実体)
│   └── (PDFファイル)     (配置パスは実装前に確認し config.py の PDF_PATH で管理)
├── src/
│   ├── ingest.py        (PDF取り込み・チャンキング)
│   ├── retriever.py     (ベクトル検索)
│   ├── generator.py     (LLM回答生成)
│   ├── server.py        (FastAPI サーバー)
│   ├── config.py        (設定・環境変数)
│   └── lambda_handler.py (Lambdaエントリーポイント。AWS構成採用時のみ存在)
├── tests/
│   ├── test_ingest.py
│   ├── test_retriever.py
│   ├── test_generator.py
│   └── test_server.py
├── evals/
│   ├── eval_set.json    (eval入力セット)
│   ├── run_eval.py      (eval実行スクリプト。正解率を評価)
│   └── run_latency_eval.py (AWS本番エンドポイントへの応答時間評価。コールドスタート含む実測。AWS構成採用時のみ意味を持つ)
├── audit/
│   └── conformance_report_YYMMDDHH_XXXX.md  (命名規則は .claude/agents/auditor.md に従う)
├── logs/
│   └── requests.jsonl   (可観測性ログ、5.5。ngrok構成のみ。AWS構成ではstdout→CloudWatch Logs)
├── templates/
│   └── index.html       (簡易Web UI)
├── incidents/           (障害報告書。日付_内容.md 形式)
├── requirements.txt
├── Dockerfile           (Lambda Container Imageビルド定義。AWS構成採用時のみ存在)
├── .dockerignore        (AWS構成採用時のみ存在。spec_infra.md 2.6章)
├── infra/               (AWS CDKアプリ。AWS構成採用時のみ存在)
│   ├── app.py           (CDKアプリエントリーポイント)
│   └── stacks/          (CDK Stack定義)
├── .github/
│   └── workflows/       (GitHub Actionsワークフロー定義。AWS構成採用時のみ存在)
│       ├── deploy.yml   (コードデプロイ: pytest → cdk deploy。GitHub Releaseのpublishedイベントがトリガー。evalはCI/CDに含めない、5.2章参照)
│       └── reingest.yml (PDF再ingest: workflow_dispatch)
└── .claude/
    └── agents/
```

#### AWS構成固有制約（spec_infra.md 採用時のみ適用）

- **シークレット管理**: LambdaランタイムのBasic認証クレデンシャルおよびBedrock APIキー（`AWS_BEARER_TOKEN_BEDROCK`）はAWS Secrets Managerで管理する。Lambda環境変数への平文保存は禁止する（理由: 実行ロール権限を持つ全員が参照できるため）
- **CI/CD認証**: GitHub ActionsからAWSへの認証はOIDC連携のIAMロールAssumeRoleのみ使用する。長期的なAWSアクセスキー（`AWS_ACCESS_KEY_ID` 等）をGitHub Secretsに保存しない（理由: 漏洩リスクを排除する。spec_infra.md 9.2章）
- **CI/CDパイプライン順序**: `deploy.yml` は `pytest tests/` → `cdk deploy` の順で実行する。トリガーはGitHub Releaseの`published`イベントのみ（push毎の自動デプロイは行わない。意図的なリリース判断をデプロイの起点とする。ユーザー確認済み）。テスト失敗時は後続ステップに進まない（理由: 品質ゲートをバイパスしたデプロイを構造的に防止する）。**eval実行（`python evals/run_eval.py`）はCI/CDから除外する**（理由: 毎デプロイでBedrock API呼び出し10問分の課金が発生し、ChromaDBデータ準備の複雑化も伴うため。auditor・metsukeyakuレビュー同様、mainマージ前に人間が手動実行し80%以上を確認する運用とする。spec_infra.md 9.2章`@metsukeyaku`指摘C-3）

### 5.3 検証ループ / フィードバック（柱3）
- コード変更のたびにテストを実行し、失敗を自己修正する
- eval は `evals/eval_set.json` の全10問で実行する。合格基準はスコア80%以上（8問以上正解）とし、閾値未達の場合はngrok公開を行わない
- `POST /ask` は外部API（Amazon Bedrock経由のClaude）呼び出しに45秒のタイムアウトを設定する（NFR-1のSLA60秒に対し、ベクトル検索・Lambdaオーバーヘッド分の余白を確保するため。AWS構成ではCloudFrontのLambda Function URLオリジンread_timeoutも60秒固定であり、Bedrock呼び出しに60秒フルを許可すると余白なく衝突し、CloudFrontがHTMLのタイムアウトページを返してしまう不具合が本番で発生したため45秒に短縮した。incidents/2026-08-21_cold-start-timeout-embedding-migration.md参照）。タイムアウト時は500エラーとして扱う
- 失敗したテストのログをそのまま修正の入力に使う
- pytest のテスト関数名は日本語で記述する（可読性のため。例: `def test_チャンク数が10件以上であること():`）。`tests/` 配下の全テストファイルに適用する

### 5.4 メモリ設計（柱4）
- RAGのチャンクには必ずメタデータ（section, page, title）を付与する
- 会話履歴は保持しない（ステートレスAPI）
- ベクトルDBの永続化パスは `data/chroma_db/` に固定する（ngrok構成。AWS構成では読み替えあり: S3が永続化の実体、Lambda起動時に `/tmp/chroma_db` にキャッシュ展開。詳細は spec_infra.md 3章）

### 5.5 可観測性（柱5）
- 全APIリクエストをログ出力する（query, retrieved_chunks, answer, latency_ms）
- ログ形式はJSON Lines（1リクエスト1行）
- ログファイルは `logs/requests.jsonl` に出力する（ngrok構成。AWS構成では stdout に出力し CloudWatch Logs に自動収集する。`/tmp` はエフェメラルなため永続化先として使用しない）
- エラーはスタックトレースを含めてログに記録する

## 6. 禁止事項

- API キー・トークンをソースコードにハードコードしない（環境変数 or .env）
- AWS構成: LambdaランタイムのシークレットをLambda環境変数またはソースコードに平文で保存しない（AWS Secrets Managerのみ使用。spec_infra.md 2.4章・8.4章）
- AWS構成: GitHubリポジトリに長期的なAWSアクセスキー（`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` 等）を保存しない（OIDC連携のみ使用。spec_infra.md 9.2章）
- PDFの絶対パスをAPIレスポンスに含めない
- ngrok公開前に以下の品質ゲート（req.md記載）を全て通過していること。1件でも未達なら公開しない:
  1. 全ユニットテスト GREEN
  2. eval スコア 80%以上（`evals/eval_set.json` 全10問で計測）
  3. コンフォーマンス監査 差分ゼロ（spec.md vs 実装。`audit/conformance_report_YYMMDDHH_XXXX.md` にauditorエージェントが記録する）
  4. 認証バイパスの脆弱性ゼロ
  5. 目付け役（metsukeyaku）のレビューが PASS または CONDITIONAL
- `rm -rf`、`git push --force`、`git reset --hard` は使用禁止

## 7. サブエージェント一覧

本プロジェクトでは以下のサブエージェントを活用する:

| エージェント | 役割 | 起動タイミング |
|---|---|---|
| spec-writer | req.mdからspec.mdを生成 | Section 2 フェーズ |
| constraint-designer | 制約ファイルの設計・検証 | Section 3 フェーズ |
| stage-gate | 計画→承認→実装の進行管理 | Section 4 フェーズ |
| test-strategist | テスト戦略立案・eval設計 | Section 5 フェーズ |
| auditor | コンフォーマンス監査・メトリクス | Section 6 フェーズ |
| release-manager | リリース判定・ngrok公開管理 | Section 7 フェーズ |
| metsukeyaku | 設計レビュー・批判的検査 | 全フェーズ（横断） |

## 8. コミット規約

- コミットメッセージは日本語可。変更の「なぜ」を書く
- 1コミット1論理変更。巨大なコミットは分割する
- テストが通らない状態でコミットしない
