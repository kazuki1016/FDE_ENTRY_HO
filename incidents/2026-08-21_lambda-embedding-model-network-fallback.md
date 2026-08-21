# 障害報告書: Lambda実行時にembeddingモデルの焼き込みキャッシュが効かず、コールドスタート遅延と一部リクエストの500エラーが発生

- **報告日**: 2026-08-21
- **対象環境**: AWS本番環境（CloudFront + Lambda Function URL構成）
- **対象コンポーネント**: `AppFunction`（`infra/stacks/main_stack.py`定義のLambda、物理名 `FdeRagAwsStack-AppFunction05AF654E-SqSW4krIUxW4`）
- **ステータス**: 修正コード適用済み・**デプロイ待ち**（`infra/stacks/main_stack.py`にHF_HOME/HF_HUB_OFFLINEを追加済み。再デプロイ後の再測定が未実施）

## 1. 概要

`POST /ask` において、コールドスタート時のレイテンシが数秒〜68秒まで大きくばらつき、一部リクエストは実際に500エラーで失敗していた。原因は、Dockerイメージのビルド時にembeddingモデルの重みを`/opt/hf_cache`へ事前ダウンロード・同梱する対策（Dockerfile:23-31）が、**Lambda実行時には効いていなかった**ことによる。

## 2. 発端

利用者から「本番でPOST /askが以下のエラーになった」との報告を受けた（別件、CloudFrontのオリジンタイムアウトとBedrock呼び出しタイムアウトの二重取りが原因。`config.py`の`TIMEOUT_SEC`を60→45秒に短縮する対応を別途実施・コミット済み: `0e776a5`）。この対応の一環でコールドスタート対策を検討・実測する過程で、本障害を発見した。

## 3. 調査で得た証跡

対象ロググループ: `/aws/lambda/FdeRagAwsStack-AppFunction05AF654E-SqSW4krIUxW4`（リージョン: ap-northeast-1）。2026-08-20 13:40〜14:33 UTC の直近ログを調査。

### 3.1 INIT phase のタイムアウト（AWS Lambdaの固定10秒上限）

直近30件のREPORTログ中5件で、Lambda実行環境のINIT phase（モジュールレベルコード実行）がAWSの固定10秒上限に到達していた。

| 時刻(UTC) | Init Duration | 直後のRequestId | Duration |
|---|---|---|---|
| 13:40:46 | 10000.27 ms (timeout) | 111af95e | 68172.06 ms |
| 13:52:44 | 9999.65 ms (timeout) | be307bb8 | 55999.14 ms |
| 14:04:18 | 10000.26 ms (timeout) | 606a7e47 | 36463.83 ms |
| 14:15:14 | 9999.36 ms (timeout) | 5a6b52cc | 18438.36 ms |
| 14:26:26 | 9999.78 ms (timeout) | 21a246d7 | 20996.45 ms |
| 14:30:05 | 9999.80 ms (timeout) | 9aadfdb1 | 21118.99 ms |

INIT phaseの10秒上限はAWS Lambdaのプラットフォーム制約であり、Lambda関数自体のタイムアウト設定（本関数は90秒）を変更しても回避できない。上限超過時、初期化処理はInvoke phase（関数タイムアウト90秒の枠）に持ち越され、リクエストのDurationに計上される。

### 3.2 実際の500エラー（EntryNotFoundError → FileNotFoundError）

2026-08-20 13:53:51 UTC、`query: "ハーネスエンジニアリングとは何ですか？"` のリクエスト（RequestId: `10fbddb5`、latency_ms: 3785）で以下のエラーが発生し、`/ask`が500を返した。

```
huggingface_hub.errors.EntryNotFoundError: 404 Client Error.
Entry Not Found for url: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/main/adapter_config.json.

（このエラーのハンドリング中、否定結果のキャッシュ書き込みを試みて連鎖的に失敗）

FileNotFoundError: [Errno 2] No such file or directory: '/home/sbx_user1051/.cache/huggingface/hub/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/refs'
...（'/home/sbx_user1051/.cache/huggingface' まで同様のFileNotFoundErrorが連鎖）...
  File "/var/task/server.py", line 130, in ask
    chunks = search(request.question, store=get_store())
```

サンプル期間中の`/ask`リクエスト11件中1件（約9%）でこのエラーが発生し、クライアントには500エラーが返っていた。

### 3.3 デプロイ済みLambdaの環境変数

```
$ aws lambda get-function-configuration --function-name FdeRagAwsStack-AppFunction05AF654E-SqSW4krIUxW4 --query "Environment.Variables"
{
    "CHROMA_S3_KEY": "chroma_db_latest.tar.gz",
    "CHROMA_S3_BUCKET": "fde-rag-chroma-215552491011",
    "AWS_SECRETS_NAME": "fde-rag/aws-secrets"
}
```

`HF_HOME` が含まれていない。

## 4. 根本原因

`Dockerfile:29` は `ENV HF_HOME=/opt/hf_cache` を設定し、ビルド時（`RUN python -c "...SentenceTransformer(...)"`）にembeddingモデルの重みをこのパスへ事前ダウンロード・同梱している（実行時にHugging Face Hubへネットワークアクセスしないための対策、Dockerfileコメント参照）。

しかし、**AWS Lambdaのコンテナイメージ関数では、Dockerfileの`ENV`命令はビルド時のみ有効で、実行時のLambda環境変数には自動的に引き継がれない**。実行時に有効化するには、Lambda関数の環境変数として別途明示的に設定する必要があるが、`infra/stacks/main_stack.py:77-86`の`environment={}`にはその設定がなく、実行時の`HF_HOME`は未設定に戻る。

結果として、`sentence-transformers`（`retriever.py:14-16`・`server.py:29-34`で遅延ロード）はビルド時に焼き込んだ`/opt/hf_cache`のモデルを見つけられず、実行時に毎回Hugging Face Hubへネットワーク経由でモデル確認・取得を試みている。これが:

1. **コールドスタート時間の大きなばらつき（3.1節）**: 本来ローカルディスク読み込みのみで完結するはずの処理が、ネットワーク往復を伴うため、ネットワーク状況次第で数秒〜68秒まで変動する
2. **一部リクエストの500エラー（3.2節）**: そのネットワーク問い合わせ中、否定結果（PEFTアダプター設定なし＝404）をキャッシュへ書き込もうとする処理が、書き込み先をデフォルトの`~/.cache/huggingface`（Lambdaでは`/tmp`以外読み取り専用のため書き込み不可）に解決してしまい、未処理の`FileNotFoundError`でクラッシュする

という2つの症状の共通原因になっている。

## 5. 影響範囲

- `POST /ask` のコールドスタート時レイテンシが不安定化し、CloudFrontのオリジンタイムアウト（60秒）や Bedrock呼び出しタイムアウト（`config.TIMEOUT_SEC`、現在45秒）に対する余裕を圧迫する。当初報告された「CloudFrontがHTMLのタイムアウトページを返しJSON.parseが失敗する」事象の一因になっていた可能性が高い
- サンプル期間中、`/ask`リクエストの約9%が本障害により500エラーで失敗
- `GET /health`・`GET /stats`は`get_store()`のみでembeddingモデルをロードしないため、本障害の影響を受けない

## 6. 対応内容（コード適用済み・デプロイ待ち）

`infra/stacks/main_stack.py` のLambda `environment` に以下を追加する:

```python
environment={
    "CHROMA_S3_BUCKET": chroma_bucket.bucket_name,
    "CHROMA_S3_KEY": "chroma_db_latest.tar.gz",
    "AWS_SECRETS_NAME": SECRETS_NAME,
    "HF_HOME": "/opt/hf_cache",
    "HF_HUB_OFFLINE": "1",  # ネットワーク問い合わせ自体を止め、焼き込み済みモデルのみを使う
},
```

`HF_HOME`だけでもモデルはローカルの焼き込み済みキャッシュから見つかるようになるはずだが、`HF_HUB_OFFLINE=1`を併せて設定することで、そもそもHugging Face Hubへのネットワーク問い合わせ自体を止め、根本原因である「実行時にネットワークアクセスが発生する」状態を確実に断つ（Dockerfileのコメントが元々意図していた「実行時のHugging Faceへのネットワーク依存を排除する」を実際に有効化する）。

## 7. 未対応事項・フォローアップ

- コード適用のみ完了。**リリース（`cdk deploy`）による本番反映と、反映後のコールドスタート時間・エラー率の再測定が未実施**
- 修正後もコールドスタート自体（コンテナ起動・重いimport・S3からのChromaDBダウンロード/展開）の所要時間は残るため、必要であれば別途最適化を検討する
