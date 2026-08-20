# インフラ仕様書（spec_infra.md）

生成日: 2026-08-19
入力: ユーザーとの設計対話（決定事項）
生成エージェント: spec-writer（初版）+ ユーザー確認事項の反映（改訂）
位置づけ: spec.md（ngrok公開構成）の代替インフラとして独立した文書。既存のspec.mdおよびreq.mdのスコープは変更しない。

---

## 0. 本文書の目的と位置づけ

spec.md（ngrok公開構成）で定義した機能仕様はそのまま維持する。本文書は「公開方式をAWSサーバーレス構成に切り替える場合のインフラ仕様」を定義する独立文書である。

- **spec.md**: 機能仕様（API仕様・データモデル・処理フロー・受け入れ基準）の正典。ngrok公開を前提とした記述を含む。
- **spec_infra.md（本文書）**: AWSサーバーレス構成に置き換えた場合のインフラ仕様。spec.mdの機能仕様を継承し、インフラ層の差分のみを記述する。

**CLAUDE.md 5.4との整合性について:**
CLAUDE.md 5.4は「ベクトルDBの永続化パスは `data/chroma_db/` に固定する」と規定している。AWS構成では、S3が永続化の実体となり、`data/chroma_db/` に相当するパスはLambdaの `/tmp` 配下のローカルキャッシュ（`/tmp/chroma_db`）として扱う。この読み替えは本AWS構成においてのみ有効であり、ngrok構成（spec.md）の規定は変更しない。

---

## 1. システム概要

「ハーネスエンジニアリング入門」講座PDF RAGシステムをAWSサーバーレス構成で公開するためのインフラ仕様。

目的はコスト抑制（低頻度アクセスにおいて無料枠内に収まる構成）と、Tailscale+Nginx構成（スペシャルハンズオン手順書 Phase 7）の置き換えである。

**全体構成:**

```
[ブラウザ]
    | HTTPS
    v
[CloudFront]
    |-- Basic認証（CloudFront Functions で Authorization ヘッダー検証、認証情報は KeyValueStore に格納）
    |-- TLS終端
    |
    +-- [S3: 静的ホスティング]
    |   templates/index.html 相当のフロントエンドを配信
    |
    +-- [Lambda Function URL]
            |
            v
        [Lambda: FastAPI (Mangum アダプタ)]
            |-- Basic認証（FastAPI側、hmac.compare_digest によるタイミング攻撃対策、認証情報は Secrets Manager から取得・キャッシュ）
            |
            +-- [ChromaDB] Lambda /tmp にキャッシュ（S3が永続化の実体）
            |
            +-- [Amazon Bedrock] 回答生成（Claude、spec.mdの構成を変更なしで継承）
```

**採用理由と却下した案:**

| 案 | 採否 | 理由 |
|---|---|---|
| AWSサーバーレス（本仕様） | 採用 | 低頻度アクセスで無料枠内に収まりやすく、低コスト |
| Tailscale + Nginx（手順書 Phase 7） | 却下 | 常時起動のローカルマシンが必要。外部公開の安定性に課題 |
| AWS Lightsail（常時起動インスタンス） | 却下 | 固定費が発生する（常時課金） |
| EFS マウント + VPC + NAT Gateway | 却下 | NAT Gateway等の固定費が$30/月超となる |
| API Gateway（HTTP API） | 却下 | 統合タイムアウトの上限が30秒（REST APIでも既定29秒、引き上げにはAWSサポート申請が必要）であり、NFR-1の60秒タイムアウト要件と矛盾するため。Bedrock呼び出し＋コールドスタートが30秒を超えると、Lambda側の設定に関わらずAPI Gatewayが504を返してしまう |
| Lambda Function URL | 採用 | Lambda本体のタイムアウト（最大15分）をそのまま使え、API Gateway分の追加コストも発生しない。CloudFrontのオリジンとしても同様に利用可能 |
| S3イベント通知→Lambdaで完全自動ingest（PDFアップロードをトリガーに即時反映） | 却下 | PDFはほぼ固定という前提（ユーザー確認済み）に対してオーバースペック。ingest用Lambda（PyMuPDF・sentence-transformers同梱）の別途パッケージングも必要になり複雑化する |
| GitHub Actions（workflow_dispatch）による半自動ingest | 採用 | 人間の作業は「新PDFをS3にアップロードする」ことのみに縮小でき、以降のingest・アーカイブ化・配置は自動化される。トリガーは人間の意思による手動実行を維持しつつ、ローカル環境操作は不要にできる |
| Lambda ZIP/レイヤーで依存ライブラリを配布 | 却下（`@metsukeyaku`指摘により訂正） | `torch`（700MB超）+ `sentence-transformers` + `transformers` の合計サイズがLambda ZIP/レイヤーの上限（250MB非圧縮）を大幅に超過し、物理的にデプロイ不可能なため |
| Lambda Container Image（ECR） | 採用（`@metsukeyaku`指摘により訂正） | 最大10GBまで許容されるため既存の依存関係をそのまま利用できる。`retriever.py`・`ingest.py`のembedding実装（PyTorchベースのsentence-transformers）を変更せずに済み、ngrok構成とAWS構成でeval結果の同等性を保てる（Simplicity First: 既存の検証済みコードを変更しない） |

**トレードオフ（明示）:**
- コールドスタート時にレイテンシが発生する（`@metsukeyaku`再レビュー指摘C-NEW-1により訂正: Container Image化に伴い当初想定の「数秒」ではなく30〜60秒程度になるリスクがある。詳細は8.3章）。これは許容済み。
- PDFを差し替えて再ingest・S3再アップロードしても、ウォームなLambda実行環境は次のコールドスタートまで古いキャッシュを使い続ける（反映ラグ）。この反映ラグは許容済み（ユーザー確認済み）。

---

## 2. インフラコンポーネント仕様

### 2.1 CloudFront

**役割:** TLS終端・フロントエンド配信・Basic認証の実施・APIへのルーティング

| 項目 | 値 |
|---|---|
| TLS終端 | CloudFrontにて処理（デフォルトドメイン使用のためCloudFront提供のデフォルト証明書を使用。8章参照） |
| Basic認証実装 | CloudFront Functions（Viewer Request イベントで Authorization ヘッダーを検証） |
| ルーティング（`@metsukeyaku`指摘 C-2 により訂正） | 既存FastAPIのルートは `/ask`・`/health`・`/stats`（`/api/`プレフィックスなし。`server.py`の実装に合わせる）。CloudFrontのビヘイビアで `/ask`・`/health`・`/stats` の各パスパターンを明示的にLambda Function URLへ、それ以外（デフォルトビヘイビア `*`）をS3オリジンへ振り分ける。FastAPI側にルートプレフィックスを追加する変更は行わない（Surgical Changes） |
| オリジンリクエストポリシー（実装時にAC-INFRA-4の検証で訂正） | Lambda Function URL向けビヘイビアは `Authorization` ヘッダーをオリジンに転送するオリジンリクエストポリシーを使用する（理由: 4.3章参照。ブラウザが自動付与するBasic認証ヘッダーをFastAPI層の検証にも使う）。当初 `AllViewer` マネージドポリシーを採用したが、これは`Host`ヘッダーも転送してしまい、Lambda Function URL側のドメイン検証と不一致になって`AccessDeniedException`（403）が返る不具合が実装時に発覚した。**確定**: `AllViewerExceptHostHeader`マネージドポリシー（`Host`ヘッダーのみ除外）に変更する。当該ビヘイビアは`CachingDisabled`（P1参照）のため、認証ヘッダー付きレスポンスが他ユーザーに誤配信されるリスクはない（`@metsukeyaku`再レビュー指摘E-NEW-2）。将来的にキャッシュを有効化する変更を行う場合は、この相互作用に注意すること |
| 許可HTTPメソッド（実装時にAC-INFRA-4の検証で発覚） | `/ask`・`/health`・`/stats`ビヘイビアは`allowed_methods`を明示的に`ALLOW_ALL`（GET/HEAD/OPTIONS/PUT/POST/PATCH/DELETE）に設定する。未設定時のCloudFrontデフォルトはGET/HEADのみで、`POST /ask`がCloudFrontに403拒否される |
| ルートオブジェクト（実装時にAC-INFRA-1-3の検証で発覚） | Distributionに`default_root_object="index.html"`を設定する。未設定だとルートパス`/`へのリクエストが空キーのオブジェクトを探しに行き、S3（OAC経由）が`AccessDenied`を返す |
| オリジンのread_timeout（実装時にAC-INFRA-3-3検証後の復旧確認で発覚） | Lambda Function URL向け`FunctionUrlOrigin`は`read_timeout=Duration.seconds(60)`を明示的に設定する。既定値30秒だとコールドスタート（S3ダウンロード・展開＋Secrets Manager取得＋embeddingモデルロード＋Bedrock呼び出し）が上限を超え、CloudFrontが504 Gateway Timeoutを返す（実測30.3秒で504発生を確認）。8.3章E-NEW-1で事前に懸念されていた「コールドスタートが30〜60秒程度になるリスク」が実際に顕在化した形。60秒はNFR-1のSLAと整合し、AWSサポート申請なしで設定可能な上限のため採用する（Lambda自体のタイムアウトは90秒のままで変更しない） |
| カスタムドメイン | **確定**: 使用しない。CloudFrontのデフォルトドメイン（`*.cloudfront.net`）を使用する（ユーザー確認済み） |
| [推奨デフォルト値（PENDING）] キャッシュ設定 | `/ask`・`/health`・`/stats` ルートはキャッシュ無効化（`CachingDisabled` マネージドポリシー）を推奨。回答は質問ごとに動的なためキャッシュ対象外。S3側の静的ファイルはCloudFrontのデフォルトキャッシュ動作でよい |
| [推奨デフォルト値（PENDING）] スロットリング設定 | 明示的なレート制限は設定しない（AWS標準のDDoS保護のみ）。低頻度アクセスのハンズオン用途のため追加設定は不要と判断 |

**CloudFront Functions（Basic認証）の仕様:**

- イベント: Viewer Request
- 検証対象: HTTP `Authorization` ヘッダー（`Basic` スキーム）
- 検証失敗時: HTTP 401を返しチャレンジヘッダー（`WWW-Authenticate: Basic realm="..."` ）を付与してブラウザに認証ダイアログを表示させる
- ユーザー名・パスワードの管理方法: **確定**: CloudFront KeyValueStore に格納する。CloudFront FunctionsのJSランタイムには外部API呼び出し機能がなく、Secrets Managerを実行時に直接呼び出すことはできない（AWS既知の制約）。そのため、Secrets Managerを認証情報の一元管理先（source of truth）とし、デプロイ時（またはローテーション時）にSecrets ManagerからKeyValueStoreへ値を同期する運用とする
- 同期メカニズム（`@metsukeyaku`指摘 C-4 により追記）: Secrets Managerから値を読み取りKeyValueStoreへ書き込む処理を `cdk deploy` の一部として実行する。追加の手動スクリプトやCIステップは不要（`cdk deploy` 一発で完結させる方針を維持）。Secrets Manager側のシークレットは事前に（初回デプロイ前に）作成されている必要がある点に注意（`@metsukeyaku`再レビュー指摘E-NEW-3: 値が変わっていなくてもデプロイのたびにAPIコールが発生しうるが、低頻度デプロイのため実害は軽微と判断し許容する）
  - **実装方式の訂正（実装時の発見）**: 当初想定していたCDKの `AwsCustomResource`（単発SDK呼び出し）では表現できないと判明した。CloudFront KeyValueStoreの`UpdateKeys` APIはKVS自体のETagによる楽観ロックを要求し、「`DescribeKeyValueStore`でETag取得→`UpdateKeys`」の2段階呼び出しが必要なため、専用の小さなLambda関数（インライン、boto3使用）+ `custom_resources.Provider` + `CustomResource` の組み合わせに変更した（`infra/stacks/main_stack.py`の`_KVS_SYNC_LAMBDA_CODE`参照）。`cdk deploy`一発で完結する点・追加の手動ステップが不要な点は変わらない
- [推奨デフォルト値（PENDING）] レルム文字列 | `"FDE RAG System"`（スペシャルハンズオン手順書のNginx設定 `auth_basic "FDE RAG System";` を踏襲）

### 2.2 S3（フロントエンド配信）

**役割:** `templates/index.html` 相当の静的ファイルをCloudFront経由で配信する

| 項目 | 値 |
|---|---|
| バケットの公開設定 | S3バケット直接アクセスは禁止（CloudFront経由のみ許可。OAC: Origin Access Control を使用） |
| 配置ファイル | `templates/index.html`（既存ファイルをそのまま使用する） |
| [要確認] バケット名 | グローバルユニークな名前が必要。AWSアカウントID等を含めた命名は実装時（デプロイ時）に機械的に決定するため、事前確定は不要 |
| [推奨デフォルト値（PENDING）] リージョン | `ap-northeast-1`（東京）。Bedrock呼び出し・Lambdaと同一リージョンに揃え、リージョン間レイテンシ・データ転送を避ける |

### 2.3 Lambda Function URL

**役割:** HTTPリクエストをLambdaに直接転送する（API Gatewayは使用しない。理由は1章参照）

| 項目 | 値 |
|---|---|
| 認証タイプ | **確定**: `NONE`（Function URL自体の認証は無効化。認証はCloudFront Functions層とFastAPI層の2層で実施するため） |
| 呼び出しモード | `BUFFERED`（レスポンスストリーミングは不要） |
| エンドポイント | `POST /ask`、`GET /health`、`GET /stats`（spec.md 2章の仕様を継承） |
| タイムアウト上限 | Lambda関数自体のタイムアウト設定に従う（API Gatewayのような追加の30秒キャップは存在しない） |
| CORSの設定要否 | **確定**: 不要。CloudFrontが単一オリジンとしてフロントエンド（S3）とAPI（Lambda Function URL）の両方を配信する構成（2.1章のパスベースルーティング）のため、ブラウザから見て同一オリジンとなりCORSは発生しない |

### 2.4 Lambda

**役割:** FastAPIアプリケーション（Mangumアダプタ経由）をサーバーレスで実行する

| 項目 | 値 |
|---|---|
| ランタイム | **Python 3.12**（コンテナイメージ内。実装時の発見により訂正: `public.ecr.aws/lambda/python:3.11`はAmazon Linux 2ベースでEOL済み（サポート終了2026-06-30）、glibcが古くonnxruntime・pymupdf・numpy等のプリビルドwheelと非互換で、Dockerビルドが失敗した。`3.12`はAmazon Linux 2023ベース（サポート終了2029-06-30）でこの問題が解消する。ユーザー確認済み） |
| エントリーポイント | Mangumアダプタでラップした FastAPI アプリ（Lambda Function URLのイベント形式に対応） |
| 依存ライブラリのパッケージング（**`@metsukeyaku`指摘 R-1 により訂正**） | **確定**: Lambda Container Image（Amazon ECR）を使用する。`requirements.txt` には `torch==2.2.2`（700MB超）・`sentence-transformers`・`transformers` が含まれ、合計サイズがLambda ZIP/レイヤーの上限（250MB非圧縮）を大幅に超過し物理的にデプロイ不可能なため。Container Imageは最大10GBまで許容され、既存の依存関係・embedding実装（`retriever.py`・`ingest.py`）を変更せずに済む（1章の却下案参照） |
| `/tmp` の用途 | ChromaDBのローカルキャッシュ（`/tmp/chroma_db`）を展開する。容量上限はLambda仕様による（通常512MB〜10GB） |
| [推奨デフォルト値（PENDING）、`@metsukeyaku`指摘 C-5 により見直し] メモリサイズ | **3008MB**（旧案の1024MBはPyTorch+sentence-transformersのモデルロードに不足する可能性が高いと指摘されたため引き上げ）。Lambdaはメモリ量に比例してCPU割当も増えるため、コールドスタート短縮にも寄与する。実装後に実測して調整すること |
| タイムアウト設定 | **確定**: 90秒。Lambda Function URL採用によりAPI Gatewayの30秒キャップが解消されたため、NFR-1の60秒に加えてS3ダウンロード・展開等のコールドスタート分の余裕を持たせる |
| 環境変数・シークレットの管理 | **確定**: AWS Secrets Manager で管理する（ユーザー指定）。Basic認証のユーザー名・パスワード、Bedrock APIキー（`AWS_BEARER_TOKEN_BEDROCK`）を格納する。Lambdaランタイムはコールドスタート時に一度Secrets Managerから取得し、実行環境のメモリ上にキャッシュする（ウォーム呼び出しのたびに再取得しない。Secrets Manager APIコール数とレイテンシを抑えるため）。`AWS_REGION`は**Lambdaランタイムが自動設定する予約済み環境変数**（実装時に発覚: CDKで手動設定しようとすると`ReservedEnvironmentVariable`エラーになる）であり、明示的な設定は不要・不可。`config.py`の`os.getenv("AWS_REGION", ...)`はLambda組み込みの値をそのまま読む |
| VPC接続 | **確定**: 不要。ChromaDBはS3経由でローカルキャッシュ化するため、VPC・EFSは使用しない |

### 2.5 S3（ChromaDB永続化）

**役割:** ChromaDBのデータを永続化する唯一の実体。Lambdaの `/tmp` はキャッシュに過ぎない。

| 項目 | 値 |
|---|---|
| 配置物 | `data/chroma_db/` をアーカイブ（tar.gz）したファイル |
| アップロードタイミング | オフラインでの再ingest時のみ（PDFが変わった時）。頻繁には行わない |
| Lambdaからのアクセス権限 | Lambda実行ロール（IAMロール）にS3バケットの読み取り権限を付与 |
| [推奨デフォルト値（PENDING）] バケット名 | フロントエンド用S3とは**別バケット**を推奨。用途ごとにIAMポリシーを分離し、最小権限を保ちやすくするため |
| アーカイブ形式 | **確定**: tar.gz |
| [推奨デフォルト値（PENDING）] バケットのリージョン | `ap-northeast-1`（Lambda・フロントエンド用S3と同一リージョン） |

### 2.6 ECR（Lambda Container Imageレジストリ）（新設、`@metsukeyaku`指摘 R-1 対応）

**役割:** Lambda関数のコンテナイメージ（FastAPI + Mangum + 依存ライブラリ一式）を保管する

| 項目 | 値 |
|---|---|
| リポジトリ | プロジェクト用ECRリポジトリを1つ新規作成（CDKの `DockerImageFunction` / `DockerImageAsset` 経由で自動作成・push可能） |
| イメージのビルド | `cdk deploy` 実行時にDockerビルドが自動実行される（CDK標準機能）。CI環境（GitHub Actions）にもDockerビルド環境が必要（9.2章参照） |
| ベースイメージ | **確定**: `public.ecr.aws/lambda/python:3.12`（Amazon Linux 2023ベース）。Python 3.11イメージ（Amazon Linux 2ベース、EOL済み）はglibcの古さが原因で複数パッケージのビルドに失敗したため実装時に変更した（127行目参照）。マルチステージビルドは不要と判明（pymupdf/pyngrokをイメージから除外することで単純な`pip install`で完結する。requirements.txt除外の詳細は`Dockerfile`参照） |
| 依存関係（`@metsukeyaku`再レビュー指摘L-1により追記） | **確定**: `requirements.txt`に`mangum`パッケージを追加する（現状未記載）。Dockerfileでは`requirements.txt`をそのままインストールする |
| torchのビルド（実装時の発見により追記） | **確定**: `torch`はデフォルトでCUDA同梱版がインストールされ`nvidia-*`パッケージ込みで4GB超になり、Lambdaの10GB上限を圧迫する（実装時に10.1GBで超過を確認）。`--index-url https://download.pytorch.org/whl/cpu`でCPU専用ビルドを明示的にインストールする（LambdaはCPUのみでnvidiaパッケージは不要）。この対応でイメージサイズは3.82GBまで縮小した |
| requirements.txtからの除外（実装時の発見により追記） | **確定**: `pymupdf`（PDF取り込み専用。Cコンパイラなしではソースビルド不可）・`pyngrok`（ngrok構成専用）はLambda実行時に不要なため、Dockerfile内で`grep -v`により除外してインストールする。`ingest.py`の`import fitz`は`extract_chunks`関数内への遅延importに変更済み（Lambda実行パスでは呼ばれないため） |
| `.dockerignore`（実装時の発見により追記） | **確定**: プロジェクトルートに`.dockerignore`が必要。CDKの`DockerImageCode.from_image_asset()`はビルドコンテキストとしてプロジェクトルート全体をコピーするため、これがないと`.venv/`（数GB）や`infra/cdk.out/`自身（再帰的に自己参照し無限増殖する）まで含めてコピーしようとし、ディスクを圧迫して`ENOSPC`でビルドが失敗する（実装時に実際に発生し、ホストディスクの空き容量が557MBまで逼迫した）。`.venv/`・`.git/`・`data/`・`logs/`・`tests/`・`infra/cdk.out/`・`*.pdf`等を除外する |
| embeddingモデルの重み（`@metsukeyaku`再レビュー指摘L-2・E-NEW-1により追記） | **確定**: `SentenceTransformer`のモデル重みはビルド時にContainer Imageへ事前同梱する（実行時のHugging Faceからのダウンロードはコールドスタートを不安定・長時間化させるため行わない）。DockerfileのビルドステップでHugging Faceからモデルをダウンロードしイメージ内にキャッシュする |
| `HF_HOME`の固定（実装時にAC-INFRA-2-3の検証で発覚） | **確定**: Dockerfileで`ENV HF_HOME=/opt/hf_cache`をモデルダウンロード前に設定する。未設定だとビルド時（rootユーザー、`HOME=/root`）のキャッシュ先と実行時（Lambdaの非rootユーザー、`HOME=/home/sbx_user1051`、読み取り専用）のキャッシュ探索先が一致せず、実行時にモデルキャッシュが見つからずHugging Faceへの再ダウンロードを試みて`/ask`が500エラーになる（`Errno 30 Read-only file system`） |
| ライフサイクルポリシー | [推奨デフォルト値（PENDING）] 古いイメージの自動削除（例: 直近5世代のみ保持）を設定し、ECRのストレージ費用を抑える |

---

## 3. データ永続化モデル（ChromaDB on S3 + Lambda /tmp キャッシュ）

### 3.1 CLAUDE.md 5.4 の読み替え

CLAUDE.md 5.4「ベクトルDBの永続化パスは `data/chroma_db/` に固定する」は、このAWS構成では以下のように読み替える:

| ngrok構成（CLAUDE.md原文） | AWS構成（本仕様）での読み替え |
|---|---|
| 永続化の実体: `data/chroma_db/`（ローカルファイルシステム） | 永続化の実体: S3（アーカイブファイル） |
| 参照時のパス: `data/chroma_db/` | 参照時のパス: `/tmp/chroma_db`（Lambda内ローカルキャッシュ） |

この読み替えはAWS構成においてのみ有効。ngrok構成（spec.md）の規定は変更しない。

### 3.2 データ更新フロー（半自動・PDFが変わった時のみ実行）

**確定（ユーザー確認済み）**: GitHub Actions（`workflow_dispatch`、手動トリガー）で自動化する。人間が行うのは「新しいPDFをS3の決められた場所にアップロードする」ことと「GitHub Actions画面でワークフローを起動する」ことの2アクションのみ。ローカルのPython環境・AWS CLI設定は不要になる（9章参照）。

```
1. 人間: 新しい harness_engineering_intro.pdf を S3（source用パス）にアップロードする
   - [要確認] アップロード先のS3バケットパス（オブジェクトキー）は、2.5章のバケット名確定後に決定する

2. 人間: GitHub Actions で reingest ワークフロー（workflow_dispatch）を手動起動する

3. GitHub Actions ランナー上で自動実行:
   a. S3からPDFをダウンロードする
   b. ingest.py を実行する（既存実装は変更不要）→ data/chroma_db/ が生成される
   c. data/chroma_db/ をアーカイブ化する
      - 形式: tar.gz（確定）
      - [推奨デフォルト値（PENDING）] ファイル名: `chroma_db_latest.tar.gz` 固定名で上書き運用する
        （反映ラグを許容する方針のため、日付付きバージョニングは行わずシンプルに保つ）
   d. アーカイブをS3（ChromaDB永続化用バケット）にアップロードする（`aws s3 cp`）

【備考】
- このフローは頻繁には実行されない（PDFが差し替わった時のみ）
- トリガーは人間の意思による手動実行を維持する（PDFアップロードのみで自動連鎖させることはしない。1章の却下案参照）
- これが唯一の永続化ポイントである
```

### 3.3 Lambda起動時フロー（キャッシュ取得）

```
1. Lambdaハンドラー先頭で /tmp/chroma_db の存在を確認する

2a. /tmp/chroma_db が存在しない場合（コールドスタート）:
    - S3から chroma_db_latest.tar.gz をダウンロードする
    - ダウンロードしたアーカイブを /tmp/ に展開する（/tmp/chroma_db が生成される）
    - ChromaDB クライアントを /tmp/chroma_db を参照して初期化する

2b. /tmp/chroma_db が存在する場合（ウォームスタート）:
    - S3ダウンロード・展開をスキップする
    - 展開済みの /tmp/chroma_db をそのまま使用する

3. 通常のクエリ処理を続行する（ChromaDBへの読み取りのみ）
```

**`GET /stats`の`last_updated`挙動差異について（`@metsukeyaku`再レビュー指摘L-3）:**
既存実装（`server.py`）は`chroma.sqlite3`のファイル`mtime`を`last_updated`として返す。AWS構成ではtar.gz展開時刻がこの値になり得るため、ngrok構成（PDF ingest実行時刻）とは意味合いが異なる場合がある。実害は小さい（Section 5.2 PENDING項目の一部として扱う）ため、実装時に許容できる程度の差異として記録するに留める。

### 3.4 反映ラグの扱い

- PDFを差し替えて再ingest・S3再アップロードを行っても、ウォームな（起動中の）Lambda実行環境は `/tmp/chroma_db` のキャッシュを使い続ける
- 次のコールドスタートが発生するまで新データは反映されない
- **このラグは許容する（ユーザー確認済み）**
- キャッシュ無効化の仕組み（S3イベント通知、Lambda再起動など）は実装しない

### 3.5 同時実行時の整合性

Lambda実行環境が複数同時に起動した場合でも、クエリ処理はChromaDBへの読み取りのみを行う。API経由での書き込み（再ingest）は行わない設計のため、複数の実行環境間でデータ不整合は発生しない。

---

## 4. 認証仕様（2層構成）

### 4.1 フロントエンド層（CloudFront Functions）

| 項目 | 値 |
|---|---|
| 認証方式 | Basic認証（HTTPヘッダー `Authorization: Basic <base64>` を検証） |
| 実装場所 | CloudFront Functions（Viewer Request イベント） |
| 検証失敗時のレスポンス | HTTP 401 + `WWW-Authenticate: Basic realm="..."` |
| 対象リクエスト | CloudFrontに到達する全リクエスト（静的ファイル・API両方） |
| ユーザー名・パスワードの管理方法 | **確定**: CloudFront KeyValueStore に格納。Secrets Managerを一元管理のsource of truthとし、デプロイ時にKeyValueStoreへ同期する（2.1章参照。CloudFront Functionsの実行時制約によりSecrets Managerの直接呼び出しは不可のため） |
| [推奨デフォルト値（PENDING）] レルム文字列 | `"FDE RAG System"` |

### 4.2 バックエンド層（Lambda上のFastAPI）

| 項目 | 値 |
|---|---|
| 認証方式 | Basic認証（HTTPヘッダー `Authorization: Basic <base64>` を検証） |
| 実装場所 | FastAPIのミドルウェアまたは依存関数 |
| タイミング攻撃対策 | `hmac.compare_digest` を使用して定数時間比較を行う（既存のAPIキー比較実装と同方針） |
| 適用エンドポイント | `POST /ask`（必須）。`GET /health`・`GET /stats` は認証不要（CLAUDE.md 5.2 PENDING既定に従う） |
| 認証失敗時のHTTPステータス | 403（CLAUDE.md 5.2: 401は使用しない。認証失敗・未認証は常に403で統一する） |
| ユーザー名・パスワードの管理方法 | **確定**: AWS Secrets Manager で管理する（ユーザー指定）。Lambdaランタイムはコールドスタート時に一度取得し、実行環境内にキャッシュする |

**2層認証の意図:**
CloudFront層のBasic認証はフロントエンド（S3静的ファイル）への不正アクセスを防ぐ目的で設置する。S3単体ではBasic認証を実装できないため必須の構成である。FastAPI層のBasic認証はバックエンドAPIへの直接アクセス（CloudFrontをバイパスする経路、すなわちLambda Function URLへの直接アクセス）に対する防御として機能する。

### 4.3 共有コードへの影響（`@metsukeyaku`指摘 R-2・C-1 により新設）

ngrok構成とAWS構成は `server.py`・`config.py`・`templates/index.html` を共有する（別実装は作らない）。以下の最小限の変更が実装フェーズで必要になる。いずれもngrok構成の既存動作には影響しない（後方互換）。

| 対象 | 現状の問題（`@metsukeyaku`指摘） | 必要な変更方針 |
|---|---|---|
| `config.py`（21行目・25行目、`@metsukeyaku`再レビュー指摘C-3RD-2により取得方式を明確化） | `API_KEY = os.environ["APP_API_KEY"]`（21行目）に加え、`AWS_BEARER_TOKEN_BEDROCK = os.environ["AWS_BEARER_TOKEN_BEDROCK"]`（25行目）もモジュール読み込み時に即評価される。AWS構成でSecrets Managerから値を取得する場合、素朴な`boto3`呼び出しをモジュールレベルに置くと同じ`KeyError`/初期化順序問題（C-NEW-2と同種）が再発する | **確定方針**: Lambda Extension等の新規コンポーネントは追加せず、C-NEW-2で導入する遅延初期化パターンを`config.py`の全Secrets Manager由来の値（`AWS_BEARER_TOKEN_BEDROCK`・`BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD`）に統一適用する。具体的には、これらをモジュールレベルの`os.environ[...]`直接参照ではなく、単一の遅延ロード関数（例: `get_secrets()`、`@lru_cache`でキャッシュ）内でboto3の`secretsmanager.get_secret_value`を呼び出して取得する形に変更する。初回アクセス時（Lambdaハンドラー実行後）に1度だけ呼ばれ、以降のウォーム呼び出しはキャッシュを再利用する（2.4章の「コールドスタート時に一度取得」という既存方針と整合）。`APP_API_KEY`は引き続き`os.environ.get("APP_API_KEY")`（ngrok構成でのみ値が設定される、Secrets Manager経由ではない通常の環境変数）のままでよい |
| `server.py`（認証ロジック） | 現状は`X-API-Key`ヘッダー検証のみ実装済み。Basic認証の検証ロジックが存在しない | 新規にBasic認証用の依存関数を追加する。`config.API_KEY`が設定されていればAPIキー方式、`config.BASIC_AUTH_USERNAME`等が設定されていればBasic認証方式で検証する、環境に応じた分岐とする（剥がせる設計の考え方を踏襲）。**境界条件（`@metsukeyaku`再レビュー指摘C-NEW-3により追記、確定方針）**: 両方設定されている状態は運用上想定しない（ngrok構成では`APP_API_KEY`のみ、AWS構成ではBasic認証用変数のみをそれぞれ設定する）。どちらも未設定の場合は**フェイルクローズ（全リクエストを403で拒否）**とし、認証なしでの通過を絶対に許可しない（CLAUDE.md 6章「認証バイパスの脆弱性ゼロ」品質ゲートに直結するため） |
| `server.py`（127行目）・`templates/index.html` | GET `/` ルートは`index.html`配信時に`__API_KEY_JSON__`を実際のAPIキーへ動的置換している。AWS構成ではS3が`index.html`を直接静的配信するため、このFastAPIルート自体が経由されず置換が発生しない（R-2） | **確定方針**: AWS構成ではBasic認証をCloudFront層・FastAPI層とも同一の認証情報で運用する。ブラウザはCloudFront層への初回認証成功後、同一オリジンへの以降のリクエスト（`index.html`のJSが発行する`/ask`へのfetch呼び出しを含む）に`Authorization: Basic ...`ヘッダーを自動付与するため、JS側でAPIキーを保持・送信する仕組みは不要になる。既存の`X-API-Key`送信コードはAWS構成では単に無視される無害な残存コードとなるが、置換前の`__API_KEY_JSON__`という文字列がそのまま静的ファイルに残るのを避けるため、S3へのアップロード時（CDKデプロイ処理の一部、またはCIのビルドステップ）に`__API_KEY_JSON__`を`null`へ一括置換してからアップロードする。`templates/index.html`のソースファイル自体は変更しない |
| `server.py`（25行目、ChromaDB初期化） | `@metsukeyaku`再レビュー指摘C-NEW-2: `_store = ChromaVectorStore(config.CHROMA_DB_PATH)`はモジュール読み込み時（インポート時）に即実行される。`ChromaVectorStore.__init__`は`chromadb.PersistentClient(path=...)`を呼び出すため、3.3章のLambda起動時フロー（S3からのダウンロード・展開）より**先に**空のChromaDBが`/tmp/chroma_db`に作成されてしまい、検索結果が常に0件になる致命的な不整合が生じる | **確定方針**: モジュールレベルの即時初期化をやめ、遅延初期化に変更する（`retriever.py`が`SentenceTransformer`ロードに`@lru_cache`を使っている既存パターンに倣う）。具体的には`_store`をファクトリ関数（`get_store()`、`@lru_cache`または同等のシングルトン管理）に置き換えるか、FastAPIの`lifespan`イベントで初期化する。これにより、Lambdaハンドラーが3.3章のS3ダウンロード・展開処理を完了させた後に初めてChromaDBクライアントが初期化されるようにする。ngrok構成では起動時に`data/chroma_db/`が既に存在するため、遅延初期化に変更しても動作に影響しない |
| `server.py`（`_log_request`関数）・`config.py`（`LOG_PATH`）（`@metsukeyaku`再レビュー指摘C-3RD-1により追加） | `_log_request`は`config.LOG_PATH`（既定`logs/requests.jsonl`）へのファイル書き込みを行う。Lambda Container Imageのファイルシステムは`/tmp`以外読み取り専用のため、この相対パスへの書き込みは`PermissionError`で失敗する。8.5章では「stdout経由でCloudWatch Logsに自動収集」と出力方式の意図は既に記載済みだが、本表（実装変更カタログ）への記載が漏れていた | **確定方針**: `_log_request`の出力先を環境に応じて分岐する。`config.LOG_PATH`が設定されていれば従来通りファイル書き込み（ngrok構成）、未設定またはAWS構成判定時は`print(json.dumps(...))`で標準出力に書き出す（AWS構成、Lambdaの標準機能でCloudWatch Logsに自動収集される。8.5章参照）。ngrok構成の既存動作に影響しない |

---

## 5. LLMバックエンド仕様（変更なし）

### 5.1 結論

AWS構成でもLLMバックエンドは**spec.mdのAmazon Bedrock経由の構成をそのまま継承し、変更しない**。

### 5.2 理由

spec.mdで定義されている `AnthropicBedrock` クライアント（ベアラートークン方式のBedrock APIキー認証）は、OS依存のないHTTPS API呼び出しである。当初のローカルLLM（bonsai-8b-mlx、Apple Silicon専用MLXフレームワーク）とは異なり、Lambdaの標準Linux実行環境（Python 3.12。実装時の発見により3.11から変更。2.4章参照）上でも問題なく動作する。したがって、AWS構成に切り替えるという理由だけでLLM呼び出し経路を変更する必要はない（Simplicity First: 動作する既存構成を理由なく変更しない）。

### 5.3 実装方針

`generator.py` の既存実装（`AnthropicBedrock` クラス、Protocol/抽象基底クラス経由、CLAUDE.md NFR-4「剥がせる設計」）はそのまま流用する。コード変更は不要。Bedrock APIキー（`AWS_BEARER_TOKEN_BEDROCK`）・`AWS_REGION`をLambda側で利用可能にする点のみがAWS構成での追加対応事項である（詳細は2.4章・8章）。

---

## 6. 処理フロー（AWS構成）

### 6.1 データ更新フロー（半自動・PDFが変わった時のみ）

```
[人間]
1. harness_engineering_intro.pdf を S3（source用パス）にアップロードする
2. GitHub Actions の reingest ワークフロー（workflow_dispatch）を起動する

[GitHub Actions ランナー（自動実行）]
3. S3からPDFをダウンロードする
4. ingest.py を実行する → data/chroma_db/ が生成される
5. data/chroma_db/ を chroma_db_latest.tar.gz にアーカイブ化する
6. アーカイブをS3（ChromaDB永続化用バケット）にアップロードする（aws s3 cp）
```

詳細は3.2章・9章を参照。

### 6.2 ブラウザからのリクエスト処理フロー（オンライン）

```
[ブラウザ]
    | HTTPS リクエスト
    v
[CloudFront: Viewer Request]
    1. CloudFront Functions が Authorization ヘッダーを検証する（KeyValueStore の認証情報と照合）
       - 検証失敗 → HTTP 401 を返す（ブラウザに認証ダイアログ表示）
       - 検証成功 → 続行

    2. パスによってオリジンを振り分ける（2.1章参照）
       - /ask, /health, /stats → Lambda Function URL へ転送（Authorizationヘッダーも転送）
       - それ以外（デフォルト） → S3 へ転送（静的ファイル配信）

[Lambda Function URL]
    3. リクエストをLambdaに転送する

[Lambda: FastAPI on Mangum]
    4. Mangumアダプタ が Function URL のイベントを FastAPI リクエストに変換する

    5. /tmp/chroma_db の存在確認（コールドスタート判定）
       - 存在しない場合: S3からアーカイブをダウンロード・展開する
       - 存在する場合: スキップ
       - 併せて、Secrets ManagerからBasic認証情報・Bedrock APIキーを取得する（コールドスタート時のみ、以降はキャッシュを使用）

    6. POST /ask の場合: Basic認証を検証する（hmac.compare_digest）
       - 検証失敗 → HTTP 403 を返す

    7. ベクトル検索（ChromaDB、/tmp/chroma_db 参照）
       - 質問文をembeddingに変換する
       - 上位k件（デフォルト k=5）を取得する

    8. Amazon Bedrock経由でClaudeが回答を生成する（spec.mdの構成を変更なしで継承）

    9. レスポンスを返す
       - JSON形式: {"answer": "string", "sources": [...]}

    10. リクエストログを記録する
        [推奨デフォルト値（PENDING）] 標準出力（stdout）にJSON Lines形式で出力し、Lambdaの標準機能でCloudWatch Logsに自動収集させる
        （`/tmp` はエフェメラルなため `logs/requests.jsonl` への直接書き込みでは永続化されない。ngrok構成とは出力方式が異なる点に注意）
```

---

## 7. 受け入れ基準（検証可能形式）

spec.mdと同じ「入力 | 操作 | 期待出力」の3列形式で定義する。以下はAWS構成に固有の基準であり、spec.md AC-1〜AC-4の機能基準はそのまま継承する。

### AC-INFRA-1: CloudFront Basic認証（フロントエンド）

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-INFRA-1-1 | Authorizationヘッダーなし | CloudFrontのURL（ルートパス）にGETリクエストを送る | HTTP 401 と `WWW-Authenticate: Basic` ヘッダーが返ること |
| AC-INFRA-1-2 | 誤ったユーザー名・パスワードのBasic認証ヘッダー | CloudFrontのURL（ルートパス）にGETリクエストを送る | HTTP 401 が返ること |
| AC-INFRA-1-3 | 正しいユーザー名・パスワードのBasic認証ヘッダー | CloudFrontのURL（ルートパス）にGETリクエストを送る | HTTP 200 と index.html の内容が返ること |

### AC-INFRA-2: バックエンドBasic認証（Lambda/FastAPI）

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-INFRA-2-1 | Authorizationヘッダーなし | `POST /ask` に `{"question": "FDEとは？"}` を送る | HTTP 403 が返ること |
| AC-INFRA-2-2 | 誤ったユーザー名・パスワードのBasic認証ヘッダー | `POST /ask` に `{"question": "FDEとは？"}` を送る | HTTP 403 が返ること |
| AC-INFRA-2-3 | 正しいBasic認証ヘッダー | `POST /ask` に `{"question": "FDEとは？"}` を送る | HTTP 200 と `{"answer": "...", "sources": [...]}` が返ること |
| AC-INFRA-2-4 | 正しいBasic認証ヘッダーなし | `GET /health` を呼ぶ | HTTP 200 と `{"status": "ok"}` が返ること（認証不要） |

### AC-INFRA-3: ChromaDB on S3 の動作

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-INFRA-3-1 | S3上にChromaDBアーカイブが配置済みの状態、`/tmp/chroma_db` が存在しないコールドスタート | Lambda関数を起動して `POST /ask` を呼ぶ | S3からアーカイブをダウンロードして `/tmp/chroma_db` に展開し、HTTP 200 と正常な回答が返ること |
| AC-INFRA-3-2 | `/tmp/chroma_db` が既に存在するウォームスタート | 同一Lambda実行環境で `POST /ask` を再度呼ぶ | S3へのダウンロードが発生せず（ログ等で確認）、HTTP 200 と正常な回答が返ること |
| AC-INFRA-3-3（実装時の検証で訂正） | S3上のアーカイブが存在しない（または空） | Lambda関数を起動して `POST /ask` を呼ぶ | **HTTP 502** が返ること（初期化失敗）。ChromaDBのダウンロードは`lambda_handler.py`のモジュール読み込み時（Mangum/FastAPI初期化より前）に行われるため、失敗時はLambda自体の初期化エラー（`Runtime.ExitError`）となりFastAPIの`HTTPException`を経由しない。Lambda Function URLは初期化エラーを502として返す仕様であり、CLAUDE.md 5.2章の「200/400/403/500に限定」はFastAPIエンドポイントのエラー表現に関する制約のため、この初期化フェーズの失敗は対象外と解釈する。当初は500を想定していたが実装時の検証で502が正しい実態と判明した。あわせて、初期化フェーズの例外メッセージに日本語（非ASCII文字）を含めると`awslambdaric`の`post_init_error`が`UnicodeEncodeError`で二次クラッシュすることが判明したため、`lambda_handler.py`内の例外メッセージは英語で記述する（FastAPI経由の日本語レスポンスにはならない箇所のため、5.1章の「常に日本語で生成」はここでは適用対象外） |

### AC-INFRA-4: エンドツーエンド動作（AWS構成）

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-INFRA-4-1 | 正しいBasic認証ヘッダー、question: "FDEとは何ですか？" | CloudFrontのURL経由で `POST /ask` を呼ぶ（HTTPS） | HTTP 200 と `{"answer": "...", "sources": [...]}` が返ること |
| AC-INFRA-4-2 | 正しいBasic認証ヘッダー | CloudFrontのURL経由でブラウザで index.html にアクセスし、質問を入力して送信する | 画面上に回答テキストが表示されること |
| AC-INFRA-4-3 | 正しいBasic認証ヘッダー | CloudFrontのURL経由で `GET /health` を呼ぶ | HTTP 200 と `{"status": "ok"}` が返ること |

### AC-INFRA-5: コスト・パフォーマンス

| # | 入力 | 操作 | 期待出力 |
|---|---|---|---|
| AC-INFRA-5-1 | ウォームスタート時の任意の質問 | `POST /ask` を呼ぶ | 60秒以内に回答が返ること（NFR-1を継承。Lambda Function URL採用によりAPI Gatewayのタイムアウト上限による制約は受けない） |
| AC-INFRA-5-2 | — | AWS Billing画面を確認する | 低頻度アクセス（月数十リクエスト程度）においてAWS無料枠内に収まること（[要確認] 具体的なリクエスト数の閾値は未確定） |

---

## 8. 制約と前提

### 8.1 技術スタック（AWS構成追加分）

spec.mdの技術スタック（6.1章）に加えて、以下のコンポーネントを使用する。

| コンポーネント | 技術 | 備考 |
|---|---|---|
| CDN・認証 | Amazon CloudFront + CloudFront Functions + CloudFront KeyValueStore | Basic認証（フロント層）、TLS終端 |
| 静的ホスティング | Amazon S3 | CloudFront経由でのみアクセス（OAC設定） |
| API呼び出し口 | AWS Lambda Function URL | API Gatewayは不使用（1章参照）。認証タイプ `NONE` |
| サーバーレス実行環境 | AWS Lambda | Python 3.12ランタイム（実装時の発見により3.11から変更。2.4章・2.6章参照） |
| Lambdaアダプタ | Mangum | FastAPIをLambdaで動作させる |
| ChromaDB永続化 | Amazon S3 | tar.gzアーカイブを格納 |
| Lambdaイメージレジストリ | Amazon ECR | Lambda Container Image用（2.6章。`@metsukeyaku`指摘R-1対応） |
| LLM呼び出し | Amazon Bedrock経由のClaude（変更なし） | spec.mdの`AnthropicBedrock`クライアントをそのまま継承 |
| シークレット管理 | AWS Secrets Manager | Basic認証クレデンシャル（バックエンド層）、Bedrock APIキーを格納。フロント層（CloudFront Functions）向けにはKeyValueStoreへ同期 |
| IaC（インフラ構築） | AWS CDK（Python） | **確定**（ユーザー確認済み）。CloudFront・S3（x2）・Lambda・Function URL・IAMロール・Secrets Manager・KeyValueStoreを宣言的に管理する。既存コードと言語を統一でき、追加費用は発生しない（内部でCloudFormationを生成）。`boto3`（AWS SDK）はLambda実行時のランタイム処理（S3ダウンロード・Secrets Manager取得・Bedrock呼び出し）にのみ使用し、インフラ構築そのものには使わない |

**ディレクトリ構成への影響（要CLAUDE.md追記）:**
CLAUDE.md 5.2章のディレクトリ構成は現状ngrok構成のみを想定しており、CDKアプリ用のディレクトリが定義されていない。AWS構成を採用する場合、新規ディレクトリ `infra/`（CDKアプリ本体、`infra/app.py`・`infra/stacks/`等）を追加する必要がある。この追加はCLAUDE.md本体の更新（`@constraint-designer`によるレビュー推奨）を伴う。CDK Stack構成（1 Stackにまとめるか複数に分割するか）は過剰設計を避け、実装時に必要最小限で判断する。

### 8.2 環境前提

- Bedrock APIキー（`AWS_BEARER_TOKEN_BEDROCK`）・Basic認証クレデンシャルは AWS Secrets Manager に格納されていること（確定値）。`AWS_REGION`は非機密値のため通常のLambda環境変数でよい
- Lambda実行ロールにS3バケットの読み取り権限（`s3:GetObject`）が付与されていること
- [推奨デフォルト値（PENDING）] Lambda実行ロールの最小権限ポリシー: 以下の3つに限定することを推奨する
  1. 対象S3バケットに対する `s3:GetObject`（ChromaDBアーカイブの読み取りのみ）
  2. 対象Secretsに対する `secretsmanager:GetSecretValue`（個別シークレットARNを指定し、ワイルドカードは使用しない）
  3. CloudWatch Logsへの書き込み（`logs:CreateLogGroup`、`logs:CreateLogStream`、`logs:PutLogEvents`）
- APIキー・トークン類はソースコードにハードコードしない（CLAUDE.md 6章 禁止事項を継承）
- PDFファイルの絶対パスをAPIレスポンス・ログに含めない（CLAUDE.md 6章 禁止事項を継承）

### 8.3 パフォーマンス要件

| 項目 | 要件値 | 備考 |
|---|---|---|
| 回答生成レイテンシ（ウォームスタート） | 60秒以内（NFR-1継承） | Lambda関数自体のタイムアウトは90秒に設定（2.4章）。API Gatewayを使用しないため30秒キャップの制約を受けない |
| コールドスタート時のレイテンシ（`@metsukeyaku`指摘 E-1 により見直し） | [推奨デフォルト値（PENDING）] 明確な数値上限は定めず、デプロイ後に実測して問題ない範囲か確認する運用とする。Container Image化（2.6章）によりPyTorch等のロード時間が加わるため、当初想定の「数秒〜10秒」よりも長くなる可能性が高く、**30〜60秒程度になるリスクがある**点を正直に記載する。Lambdaタイムアウト90秒には収まる想定だが、NFR-1（60秒）のSLAをコールドスタート時は満たせない可能性がある。実装後に実測し、必要であれば有償のProvisioned Concurrencyの採用も選択肢として検討する（ただし「料金を抑えたい」という方針とはトレードオフになるため、まずは実測してから判断する） |
| 90秒タイムアウト超過リスク（`@metsukeyaku`再レビュー指摘E-NEW-1により追記） | コールドスタートの内訳（Container Image起動＋S3からのChromaDBダウンロード・展開＋Secrets Manager取得＋embeddingモデルロード＋Bedrock呼び出し）を合算すると90秒のLambdaタイムアウトを超過するリスクがある。2.6章の方針（embeddingモデルをイメージに事前同梱）により「モデルロード」の所要時間はHugging Faceへのネットワーク待ちがなくなり大幅に短縮される見込みだが、実装後の実測による検証が必須。超過が判明した場合はLambdaタイムアウトの引き上げ（Function URLはAPI Gatewayのような上限を持たないため可能）を優先し、Provisioned Concurrencyはコスト増を伴う最終手段とする |

### 8.4 セキュリティ要件

- CloudFront層でBasic認証を行い、フロントエンドへの不正アクセスを防ぐ
- Lambda/FastAPI層でもBasic認証を行い、Lambda Function URLへの直接アクセス（CloudFrontバイパス）に対応する
- `POST /ask` への未認証・認証失敗リクエストは HTTP 403 で拒否する（spec.md 2.1章のエラー仕様を継承）
- `hmac.compare_digest` によるタイミング攻撃対策を実施する
- S3バケットへの直接パブリックアクセスを禁止する（CloudFront OACのみ許可）
- 認証情報はAWS Secrets Manager（バックエンド層）・CloudFront KeyValueStore（フロント層、Secrets Managerから同期）で管理し、コード・環境変数への平文ハードコードは行わない
- （`@metsukeyaku`指摘 E-2）Lambda Function URLのURL自体（ランダム文字列）が何らかの経路（ログ・エラーレスポンス等）で漏洩したとしても、FastAPI層のBasic認証（4.2章）が防御になる。追加のWAF・IP制限は「料金を抑えたい」方針に対してオーバースペックと判断し導入しない

### 8.5 可観測性要件

- 全APIリクエストのquery, retrieved_chunks, answer, latency_msをログ出力する（NFR-3継承）
- ログ出力先は標準出力（stdout）経由でCloudWatch Logsに自動収集させる（8.1章・6.2章参照）。`/tmp`はエフェメラルなため永続化先としては使用しない
- エラー時はスタックトレースを含めてログに記録する

### 8.6 品質ゲート（AWS公開時）

ngrok構成の品質ゲート（req.md / spec.md 6.8章）を継承し、以下を追加する:

1. 全ユニットテスト GREEN（継承）
2. evalスコア 80%以上（継承）
3. コンフォーマンス監査 差分ゼロ（継承）
4. 認証バイパスの脆弱性ゼロ（継承）: CloudFront経由・Lambda Function URL直接経由の両方でBasic認証が機能していること
5. 目付け役（metsukeyaku）のレビューが PASS または CONDITIONAL（継承）

### 8.7 CLAUDE.md との整合性確認

| CLAUDE.md 規定 | AWS構成での扱い |
|---|---|
| 5.2「POST /askの認証方式（ブロック値）」 | **確定**: Basic認証（ユーザー確認済み）。本文書に記録 |
| 5.4「ベクトルDBの永続化パスは `data/chroma_db/` に固定する」 | **読み替え**: S3が永続化の実体、`/tmp/chroma_db` がLambdaのローカルキャッシュ（本文書 1章・3章に明記） |
| 5.2 NFR-4「LLMバックエンドはインターフェース分離で実装する」 | 継承。既存の`AnthropicBedrock`実装クラス（Amazon Bedrock経由）をそのまま流用し、コード変更なし |
| 6章「401は使用しない、認証失敗は403で統一」 | FastAPI層は403で統一。CloudFront Functions層はブラウザ認証ダイアログのために401を使用（CloudFront層はFastAPIの外側であり、同規定の適用範囲外と解釈する） |
| 6章「ngrokはCLIツール呼び出しのため抽象化しない」 | AWS構成ではngrokは使用しない。CloudFront+Lambda Function URLへの切り替えはインフラ層の変更であり、コードへの影響はLambdaエントリーポイント（Mangum）の追加のみ |
| 6章「APIキー・トークンをソースコードにハードコードしない」 | 継承。AWS Secrets Manager（バックエンド）・KeyValueStore（フロント、Secrets Manager同期）で管理する（8.1・8.4章） |

---

## 9. デプロイ自動化（CI/CD）

### 9.1 方針

**確定（ユーザー確認済み）**: 手動デプロイではなく、GitHub Actionsによる自動化を採用する。本プロジェクトには現時点でGitHubリモートリポジトリが存在しないため、新規作成する（実装フェーズで対応）。

### 9.2 ワークフロー1: ソースコード・インフラのデプロイ

| 項目 | 値 |
|---|---|
| トリガー | **確定**（ユーザー確認済み、実装時に訂正）: リリースの公開（GitHub Releaseの`published`イベント）。push毎の自動デプロイではなく、リリースという明示的な意思表示をデプロイの起点にする |
| 実行内容（`@metsukeyaku`指摘 C-3 により訂正） | ①`pytest tests/` 実行（失敗したらデプロイ中止） → ②`cdk deploy`（Lambda Container Imageのビルド・pushを含むインフラ全体を更新） |
| AWS認証 | **確定**: OIDC（OpenID Connect）連携によるIAMロールAssumeRoleを使用する。長期的なAWSアクセスキーをGitHub Secretsに保存しない（CLAUDE.md 6章「APIキー・トークンをハードコードしない」の精神をCI認証にも適用） |
| Dockerビルド環境 | GitHub Actions標準ランナー（`ubuntu-latest`）にはDockerが標準搭載されているため追加セットアップ不要。`cdk deploy`がイメージのビルド・ECRへのpushを内部で実行する |
| [要確認] ワークフローファイル名・配置 | `.github/workflows/deploy.yml`を想定（一般的な命名慣習） |

**スコープ外（本ワークフローに含めない）:**
- コンフォーマンス監査（`@auditor`）・目付け役レビュー（`@metsukeyaku`）はClaude Codeのサブエージェントによる対話的レビューであり、GitHub Actions上での自動実行は行わない。これらはPR作成前・main merge前に人間が手動で実行する運用とする（既存のスペシャルハンズオン手順書Phase 5の運用を継続）。
- **eval実行（`python evals/run_eval.py`）もCIから除外する**（`@metsukeyaku`指摘 C-3 により訂正。当初案はpushのたびにevalを自動実行する設計だったが、以下の理由で撤回した: ①毎push時にBedrock API呼び出し10問分の課金が発生し「料金を抑えたい」方針に反する、②GitHub Actionsランナー上でのChromaDBデータ準備方法（PDFからの都度ingestかS3からのダウンロードか）が未整理のまま自動化すると複雑化する。auditor/metsukeyakuと同様、mainマージ前に人間が手動で`python evals/run_eval.py`を実行し80%以上を確認する運用とする（CLAUDE.md 5.3章の既存運用を継続）

### 9.3 ワークフロー2: PDF再ingest

| 項目 | 値 |
|---|---|
| トリガー | `workflow_dispatch`（GitHub Actions画面からの手動起動） |
| 実行内容 | 3.2章参照。S3からPDFダウンロード → ingest.py実行 → アーカイブ化 → S3アップロード |
| AWS認証 | ワークフロー1と同様、OIDC連携のIAMロールを使用 |
| 依存ライブラリのインストール（`@metsukeyaku`指摘 E-3） | `ingest.py`の実行にはPyTorch・sentence-transformers等が必要で、GitHub Actionsランナー上でのインストール・モデルダウンロードに数分かかる。頻度が低い（PDF差し替え時のみ）ため許容するが、`actions/cache`でpipキャッシュを効かせて2回目以降を高速化することを推奨する |
| [要確認] ワークフローファイル名・配置 | `.github/workflows/reingest.yml`を想定 |

### 9.4 IAMロール（OIDC用）の権限

デプロイ用ロールとreingest用ロールは、8.2章の最小権限方針に加えて以下が必要:

- デプロイ用ロール: CDKが操作する各サービス（CloudFront・S3・Lambda・IAM・Secrets Manager等）へのデプロイ権限。CDKの `cdk bootstrap` が生成するデプロイ用ロールの利用を基本とする
- reingest用ロール: S3（source PDF読み取り、ChromaDBアーカイブ書き込み）への限定権限のみ

[要確認] 上記2ロールの信頼関係（trust policy、対象GitHubリポジトリ・ブランチの限定）の具体的な設定内容は未確定

### 9.5 ディレクトリ構成への影響（要CLAUDE.md追記、8.1章の内容に追加）

`.github/workflows/`（GitHub Actionsのワークフロー定義）を新規追加する。8.1章で述べた`infra/`（CDKアプリ）と合わせて、AWS構成採用時のCLAUDE.md 5.2章ディレクトリ構成の更新対象となる。

---

## 付記: [要確認] 項目一覧

本仕様書に記載した未確定項目をまとめる。値が確定次第、本文書を更新すること。

| # | 箇所 | 内容 |
|---|---|---|
| ~~1~~ | 2.2 S3（フロントエンド） | **解消**: `fde-rag-frontend-<AWSアカウントID>`に固定した（ユーザー確認済み。`infra/app.py`でCDK_DEFAULT_ACCOUNTを明示的にStackへ渡し、`main_stack.py`でアカウントIDを含むバケット名を組み立てる。GitHub ActionsのVariable設定前に判明させるため） |
| 2 | 3.2 データ更新フロー | アップロード先のS3バケットパス（オブジェクトキー）。2.5章のバケット名確定後に決定 |
| 3 | 7 受け入れ基準 AC-INFRA-5-2 | 無料枠内に収まる具体的なリクエスト数の閾値 |
| 4 | 9.4 IAMロール（OIDC） | デプロイ用・reingest用ロールの信頼関係（trust policy）の具体的な設定内容 |
| 6 | 9.2 / 9.3 CI/CDワークフロー（実装時に判明） | GitHubリポジトリに以下のSecrets/Variablesの設定が必要（人間承認B・Cの完了後に登録する）。未設定の間はワークフローの実行自体は失敗する（YAML構文は妥当）:<br>Secrets: `APP_API_KEY`・`AWS_BEARER_TOKEN_BEDROCK`（deploy.ymlのテスト実行用）<br>Variables: `AWS_DEPLOY_ROLE_ARN`・`AWS_REINGEST_ROLE_ARN`・`AWS_REGION`・`CHROMA_S3_BUCKET` |
| 7 | 9.3 reingestワークフロー（実装時に判明） | source PDFのS3配置キーを `source/harness_engineering_intro.pdf`（ChromaDB永続化用バケット内、`chroma_db_latest.tar.gz`と同居）と仮決めした。2.5章のバケット名確定・要確認#1と合わせて確定させる |
| 5 | 2.6 ECR | Lambda Container Imageのベースイメージ（`@metsukeyaku`指摘R-1対応で新設） |

**推奨デフォルト値（PENDING）として記載した項目**（実装をブロックしないが、最終確認が望ましい）:

| # | 箇所 | 内容 | 推奨値 |
|---|---|---|---|
| P1 | 2.1 CloudFront | キャッシュ設定 | `/ask`等の動的パスはキャッシュ無効化 |
| P2 | 2.1 CloudFront | スロットリング設定 | 明示設定なし |
| P3 | 2.1 / 4.1 CloudFront Functions | レルム文字列 | `"FDE RAG System"` |
| P4 | 2.2 S3（フロントエンド） | リージョン | `ap-northeast-1` |
| P5 | 2.4 Lambda | メモリサイズ | **3008MB**（`@metsukeyaku`指摘C-5により1024MBから見直し） |
| ~~P6~~ | 2.5 S3（ChromaDB永続化） | バケット名 | **解消**: `fde-rag-chroma-<AWSアカウントID>`に固定（フロント用とは別バケット。上記1と同様の理由） |
| P7 | 2.5 S3（ChromaDB永続化） | リージョン | `ap-northeast-1` |
| P8 | 3.2 データ更新フロー | アーカイブファイル名 | `chroma_db_latest.tar.gz` 固定 |
| P9 | 3.2 データ更新フロー | アップロードツール | AWS CLI（`aws s3 cp`） |
| P10 | 6.2 / 8.5 処理フロー | ログ出力先 | stdout → CloudWatch Logs自動収集 |
| P11 | 8.2 環境前提 | Lambda実行ロールの最小権限ポリシー | S3 GetObject限定 + Secrets Manager GetSecretValue限定 + CloudWatch Logs書き込み |
| P12 | 8.3 パフォーマンス要件 | コールドスタート許容上限 | 数値化せず実測で確認（30〜60秒に達するリスクを許容） |
| P13 | 9.2 / 9.3 CI/CDワークフロー | ワークフローファイル名 | `.github/workflows/deploy.yml`、`.github/workflows/reingest.yml` |
| P15 | 9.2 / 9.3 CI/CDワークフロー | 使用するGitHub Actions（`uses:`）のバージョン | `actions/checkout@v6`・`actions/setup-python@v6`・`actions/setup-node@v6`・`aws-actions/configure-aws-credentials@v6`（実装時に確認。node-versionはEOL済みの20ではなく22を使用） |
| P14 | 2.6 ECR | イメージのライフサイクルポリシー | 直近5世代のみ保持 |
