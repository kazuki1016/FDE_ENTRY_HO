# 障害報告書: Lambdaコールドスタートの深刻な遅延・タイムアウトにより、embeddingをAmazon Bedrockへ移行

- **報告日**: 2026-08-21
- **対象環境**: AWS本番環境（CloudFront + Lambda Function URL構成）
- **対象コンポーネント**: `AppFunction`（`infra/stacks/main_stack.py`定義のLambda）
- **関連インシデント**: [[2026-08-21_lambda-embedding-model-network-fallback]]（本件の直接のトリガー。HF_HOME修正のデプロイ後に本件が発生した）
- **ステータス**: コード対応済み・**S3データ未更新／本番デプロイ待ち**

## 1. 概要

`incidents/2026-08-21_lambda-embedding-model-network-fallback.md`の修正（Lambda環境変数への`HF_HOME`/`HF_HUB_OFFLINE`追加）をデプロイした直後、利用者から「本番でリリース後、60秒経っても`POST /ask`の回答が返ってこない」との報告を受けた。調査の結果、上記修正自体は正しく機能していたが、**Lambdaのコールドスタート（モジュールレベルの重いimport＋S3からのChromaDBダウンロード・展開）自体が15秒〜90秒（Lambda関数タイムアウト上限）まで大きくばらついており、これが直接の原因**と判明した。根本対応として、embedding生成をローカル実行のsentence-transformers（PyTorch）からAmazon Bedrock（Titan Text Embeddings V2）へ移行した。

## 2. 調査で得た証跡

対象ロググループ: `/aws/lambda/FdeRagAwsStack-AppFunction05AF654E-SqSW4krIUxW4`（リージョン: ap-northeast-1）。

### 2.1 ログストリーム `d4c955dc80cb4c0c918cb468020b41f7`（利用者報告分、2026-08-21 07:06 UTC）

| 時刻(UTC) | 出来事 |
|---|---|
| 07:06:22.497 | `INIT_REPORT Init Duration: 10000.17 ms Status: timeout`（AWS Lambdaの固定10秒INIT phase上限に到達） |
| 07:06:51.692 | joblibの警告（マルチプロセス検出失敗、致命的ではない） |
| 07:07:06.686 | `START RequestId` — モジュール初期化完了まで**約44秒**を要した |
| 07:07:22.070 | `/ask`のアプリログ出力。回答自体は正常に生成（`latency_ms: 15205`） |
| 07:07:22.074 | `REPORT ... Duration: 59539.36 ms` — CloudFrontのオリジンread_timeout（60秒）にぎりぎり間に合わないタイミング |

### 2.2 ログストリーム `fbe67b21ef9a4c038d4560feaf9024fa`（同日05:51〜05:53 UTC、より深刻な事例）

| 時刻(UTC) | 出来事 |
|---|---|
| 05:51:16.568 | `INIT_REPORT ... Status: timeout` |
| 05:52:26.358 | `START RequestId: 4c549b17...` |
| 05:52:46.627 | `REPORT ... Duration: 90000.00 ms ... Status: timeout` — **Lambda関数自体が90秒の上限で完全にタイムアウト（無応答で失敗）** |
| 05:52:53.963 | `START RequestId: a184061e...`（次のリクエスト） |
| 05:53:12.008 | 今度は正常応答（`Duration: 24678.48 ms`） |

同一の初期化処理でも15〜25秒で終わる場合と、90秒の関数タイムアウトに達し完全に失敗する場合があり、**再現性がなく予測不能**であることを確認した。

### 2.3 原因の特定

コールドスタート時にLambdaのモジュールレベルコード（`lambda_handler.py`）が以下を直列に実行しており、これが重い:
- S3から`chroma_db_latest.tar.gz`のダウンロード・`/tmp`への展開
- `torch`・`transformers`・`sentence-transformers`・`chromadb`（`onnxruntime`・`grpcio`・`opentelemetry-*`等の重量級の依存を含む）のPython import

AWS Lambdaの**INIT phaseには固定10秒の上限があり（設定変更不可）**、これを超えると初期化処理はInvoke phase（関数タイムアウト90秒の枠）に持ち越される。`requirements.txt`には`torch`・`transformers`・`sentence-transformers`に加えchromadb経由で`onnxruntime`・`grpcio`・`opentelemetry-*`・`kubernetes`等、非常に重い依存が含まれており、これがコールドスタート40〜90秒超の主因と判断した。

## 3. 対応方針の検討

対応案として以下を比較した:

| 案 | 内容 | 判断 |
|---|---|---|
| Provisioned Concurrency | 常時1インスタンス起動でコールドスタート自体をなくす | 概算月$42前後の固定費が発生する。トラフィックの少ない講座デモ用途では待機コストが呼び出しコストを上回る可能性が高く、根本解決にもならないため見送り |
| embeddingをAmazon Bedrock（Titan Text Embeddings V2）へ移行 | `torch`/`transformers`/`sentence-transformers`一式をLambdaの依存から完全に除去する | **採用**。コールドスタート時間の主因と考えられる重量級依存を根本的に除去できる |

**採用理由（ユーザー確認済み）:** Provisioned Concurrencyは可用性は改善するが固定費が継続的に発生し、コールドスタート自体の重さという根本原因には対処しない。embeddingのBedrock化は根本原因を直接除去でき、かつLLM呼び出しで既にAmazon Bedrock（ベアラートークン方式のBedrock APIキー認証）に依存している構成と一貫性がある（新規のシークレット・IAM権限追加が不要）。

## 4. 実施した対応

- `src/ingest.py`: `embed_text()`を追加（`boto3`の`bedrock-runtime`クライアント経由でTitan Text Embeddings V2を呼び出す）。認証は`AWS_BEARER_TOKEN_BEDROCK`環境変数によるベアラートークン方式（`generator.py`のLLM呼び出しと同じ認証情報を再利用、IAM権限追加不要）
- `src/retriever.py`: ローカル`SentenceTransformer`ロードを廃止し、`ingest.embed_text()`を再利用
- `src/config.py`: `EMBEDDING_MODEL`を`amazon.titan-embed-text-v2:0`に、`EMBEDDING_DIMENSIONS=1024`を追加（両方PENDING）
- `Dockerfile`: torch CPU専用インストール・embeddingモデルの事前焼き込みステップを削除
- `infra/stacks/main_stack.py`: 不要になった`HF_HOME`・`HF_HUB_OFFLINE`環境変数を削除
- `requirements.txt`: `torch`・`transformers`・`sentence-transformers`を削除
- ローカル`data/chroma_db/`を新embeddingで再ingest（109チャンク、旧384次元→新1024次元のため再作成が必須だった）
- 全15ユニットテストGREEN確認済み

### 4.1 embedding変更に伴う付随的な再検証

- eval（`evals/eval_set.json`全10問）を新embeddingで再実行し、TOP_K=5で**10/10(100%)**を確認（旧モデルは同条件で**9/10(90%)**）
- `config.TOP_K`が元々3で設計されていた経緯（旧モデルではk=3でスコア70%止まりだったため5に変更）を踏まえ、新embeddingでTOP_K=3を再検証したところ**9/10（90%）**となり、旧モデルの同条件（70%）を明確に上回った。コンテキスト最小化（CLAUDE.md 5.1）を優先し、`TOP_K`を3に確定した（ユーザー確認済み）

## 5. 未対応事項・フォローアップ

- ~~S3上の`chroma_db_latest.tar.gz`（AWS Lambda用）は旧384次元embeddingのまま未更新~~ **完了（2026-08-21）**: ローカル環境から新embedding（1024次元）で再生成しS3へアップロード済み
- ~~`reingest.yml`用IAMロール（`AWS_REINGEST_ROLE_ARN`）に`bedrock:InvokeModel`権限が未付与~~ **完了（2026-08-21）**: インラインポリシー`BedrockEmbedInvoke`（`amazon.titan-embed-text-v2:0`のARNに限定）を`GitHubActionsReingestRole`へ追加済み
- ~~`GitHubActionsReingestRole`のOIDC trust policyが旧形式のまま~~ **完了（2026-08-21）**: `GitHubActionsDeployRole`と同じ問題（sub条件がGitHub immutable ID形式`repo:kazuki1016@71158437/FDE_ENTRY_HO@1340135191:*`になっておらず`AssumeRoleWithWebIdentity`が拒否される）がreingest用ロールにも残っていたため修正。デプロイ用ロールを修正した際にreingest用ロールへの横展開が漏れていた
- ~~S3に元PDF（`source/harness_engineering_intro.pdf`）が未アップロード~~ **完了（2026-08-21）**: アップロード済み
- **`reingest.yml`のworkflow_dispatchによる実際の動作確認済み（2026-08-21）**: 上記3件の修正後、全ステップGREENで完走（run 32468506547、2分28秒）。S3の`chroma_db_latest.tar.gz`が最新embeddingで更新されたことを確認
- 新しいリリースの発行による本番デプロイが未実施
- デプロイ後、コールドスタート時間が実際に改善したかの再測定（CloudWatch Logsの`Init Duration`・`REPORT`行）が必要
- `spec.md`・`spec_infra.md`・`req.md`のsentence-transformers関連記述は本件と合わせて更新済み
