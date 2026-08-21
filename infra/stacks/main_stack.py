"""AWSサーバーレス構成のメインスタック（spec_infra.md）。

CloudFront + S3(フロントエンド) + S3(ChromaDB永続化) + Lambda(Container Image) +
Lambda Function URL + CloudFront Functions(Basic認証、KeyValueStore) を定義する。

Secrets Manager（Bedrock APIキー・Basic認証情報。BASIC_AUTH_USERNAME/PASSWORD/
AWS_BEARER_TOKEN_BEDROCKをキーに持つ1つのシークレット）は、人間承認B（cdk bootstrap
と合わせて実施）で事前に作成されている前提。ここではSecret.from_secret_name_v2で
参照するのみで、作成はしない（spec_infra.md 8.2章）。
"""
import datetime as _dt
import pathlib

from aws_cdk import (
    BundlingOptions,
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import custom_resources as cr
from constructs import Construct

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]

# [要確認] spec_infra.md 付記: Secrets Managerのシークレット名（人間承認Bで作成する際に合わせる）
SECRETS_NAME = "fde-rag/aws-secrets"

# Secrets Manager → CloudFront KeyValueStore 同期用カスタムリソースLambdaのコード置き場
# （spec_infra.md 2.1章 C-4。実装方針の詳細は infra/lambda/kvs_sync/index.py のdocstring参照）
_KVS_SYNC_LAMBDA_DIR = str(_PROJECT_ROOT / "infra" / "lambda" / "kvs_sync")


class MainStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── 2.5章: S3（ChromaDB永続化）。フロントエンド用とは別バケット（P6） ──
        # バケット名はアカウントIDを含めて固定する（グローバルに一意にするため）。
        # デプロイ前から名前が判明するため、GitHub ActionsのCHROMA_S3_BUCKET変数を
        # 事前に設定できる（ユーザー確認済み。付記#1・要確認#6を解消）。
        chroma_bucket = s3.Bucket(
            self,
            "ChromaDbBucket",
            bucket_name=f"fde-rag-chroma-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── 2.2章: S3（フロントエンド配信）。CloudFront OAC経由のみアクセス許可 ──
        frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"fde-rag-frontend-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Secrets Manager（人間承認Bで事前作成。ここでは参照のみ）
        secret = secretsmanager.Secret.from_secret_name_v2(self, "AppSecret", SECRETS_NAME)

        # ── 2.4章・2.6章: Lambda（Container Image） ──
        function = lambda_.DockerImageFunction(
            self,
            "AppFunction",
            code=lambda_.DockerImageCode.from_image_asset(str(_PROJECT_ROOT)),
            timeout=Duration.seconds(90),
            memory_size=3008,
            environment={
                # AWS_REGIONはLambdaランタイムが自動設定する予約済み環境変数のため
                # 手動指定はできない（config.pyのos.getenv("AWS_REGION", ...)は
                # このLambda組み込みの値をそのまま読む）。
                "CHROMA_S3_BUCKET": chroma_bucket.bucket_name,
                "CHROMA_S3_KEY": "chroma_db_latest.tar.gz",
                "AWS_SECRETS_NAME": SECRETS_NAME,
                # DockerfileのENV命令はビルド時のみ有効で実行時のLambda環境変数には
                # 引き継がれないため、HF_HOMEをここで明示的に再設定する必要がある。
                # 未設定だと実行時にsentence-transformersがビルド時焼き込み済みの
                # /opt/hf_cacheを見つけられずHugging Face Hubへネットワーク問い合わせ
                # してしまい、コールドスタート遅延の増大と一部リクエストの500エラー
                # （否定結果キャッシュの書き込み失敗）の原因になっていた
                # （incidents/2026-08-21_lambda-embedding-model-network-fallback.md）。
                "HF_HOME": "/opt/hf_cache",
                "HF_HUB_OFFLINE": "1",
                # LOG_PATH・APP_API_KEYは意図的に設定しない
                # （config.pyがNone判定でAWS構成の挙動＝標準出力ログ・Basic認証に切り替える）
            },
        )
        chroma_bucket.grant_read(function)
        secret.grant_read(function)

        # ── 2.3章: Lambda Function URL（認証タイプ NONE。認証はCloudFront/FastAPI層で行う） ──
        function_url = function.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        # ── 4.1章: CloudFront Functions + KeyValueStore（Basic認証） ──
        kvs = cloudfront.KeyValueStore(self, "AuthKeyValueStore")
        auth_function = cloudfront.Function(
            self,
            "BasicAuthFunction",
            code=cloudfront.FunctionCode.from_file(file_path=str(_PROJECT_ROOT / "infra" / "cf_auth.js")),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            key_value_store=kvs,
        )
        auth_function_association = cloudfront.FunctionAssociation(
            function=auth_function,
            event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
        )

        # ── 2.1章: CloudFront。/ask・/health・/statsのみLambda Function URLへ、それ以外はS3へ ──
        s3_origin = origins.S3BucketOrigin.with_origin_access_control(frontend_bucket)
        lambda_origin = origins.FunctionUrlOrigin(
            function_url,
            # read_timeoutの既定値30秒だとコールドスタート（S3ダウンロード・展開＋
            # Secrets Manager取得＋embeddingモデルロード＋Bedrock呼び出し）が
            # 上限を超えCloudFrontが504を返す（実装時にAC-INFRA-3-3検証後の
            # 復旧確認で実測30.3秒により発覚。spec_infra.md 8.3章E-NEW-1で
            # 事前に懸念されていたリスクが実際に顕在化した）。NFR-1のSLA（60秒）に
            # 合わせて60秒に設定する（AWSサポート申請なしで設定可能な上限）。
            read_timeout=Duration.seconds(60),
        )

        api_behavior = cloudfront.BehaviorOptions(
            origin=lambda_origin,
            cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
            # Authorizationヘッダーをオリジンへ転送する（FastAPI層のBasic認証にも使うため。4.3章）。
            # ALL_VIEWERだとHostヘッダーもそのまま転送され、Lambda Function URL側の
            # ドメイン検証と不一致になりAccessDeniedException(403)を返す
            # （実装時にAC-INFRA-4の検証で発覚）。Lambda Function URLをオリジンにする場合は
            # AWS公式にHostヘッダーを除外したポリシーの使用が推奨されている。
            origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            # allowed_methods未設定だとデフォルトでGET/HEADのみ許可となり、/askへの
            # POSTがCloudFrontに403拒否される（実装時にAC-INFRA-4の検証で発覚）。
            allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            function_associations=[auth_function_association],
        )

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            # default_root_object未設定だと "/" が空キーのオブジェクトを探しに行きS3が
            # AccessDeniedを返す（実装時にAC-INFRA-1-3の検証で発覚）。
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=s3_origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                function_associations=[auth_function_association],
            ),
            additional_behaviors={
                "/ask": api_behavior,
                "/health": api_behavior,
                "/stats": api_behavior,
            },
            # カスタムドメインは使用しない（確定。2.1章）。デフォルトの *.cloudfront.net を使う
        )

        # ── 4.3章 R-2: index.htmlの __API_KEY_JSON__ を null に置換してからS3へデプロイする ──
        # （templates/index.html のソースファイル自体は変更しない）
        index_html = (_PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        index_html = index_html.replace("__API_KEY_JSON__", "null")
        s3deploy.BucketDeployment(
            self,
            "DeployFrontend",
            sources=[s3deploy.Source.data("index.html", index_html)],
            destination_bucket=frontend_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # ── 2.1章 C-4: Secrets Manager → KeyValueStore 同期（cdk deploy時に自動実行） ──
        sync_function = lambda_.Function(
            self,
            "KvsSyncFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.seconds(30),
            # CloudFront KeyValueStoreのデータプレーンAPI（cloudfront-keyvaluestore）は
            # awscrt(botocore[crt])を要求するが、Lambda組み込みのboto3/botocoreには
            # 含まれない（実装時に "Missing Dependency" エラーで発覚）。
            # requirements.txt（infra/lambda/kvs_sync/）をDockerでバンドルして同梱する。
            code=lambda_.Code.from_asset(
                _KVS_SYNC_LAMBDA_DIR,
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
        )
        secret.grant_read(sync_function)
        sync_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudfront-keyvaluestore:DescribeKeyValueStore",
                    "cloudfront-keyvaluestore:UpdateKeys",
                ],
                resources=[kvs.key_value_store_arn],
            )
        )

        provider = cr.Provider(self, "KvsSyncProvider", on_event_handler=sync_function)
        CustomResource(
            self,
            "KvsSyncResource",
            service_token=provider.service_token,
            properties={
                "KvsArn": kvs.key_value_store_arn,
                "SecretArn": secret.secret_arn,
                # KvsArn・SecretArnはSecrets Manager側でシークレット値（Basic認証情報）を
                # ローテーションしてもARN自体は変わらないため、このプロパティだけでは
                # cdk deploy時にCloudFormationがUpdateを検知せずKVS同期がスキップされてしまう
                # （実装時にmetsukeyaku最終レビュー指摘C-2で発覚）。デプロイのたびに変化する
                # 値を追加し、synth 2.1章の想定どおり毎回同期を強制する。
                "ForceUpdate": str(_dt.datetime.now(_dt.timezone.utc).isoformat()),
            },
        )

        # ── 出力 ──
        CfnOutput(self, "DistributionDomainName", value=distribution.distribution_domain_name)
        CfnOutput(self, "FunctionUrl", value=function_url.url)
        CfnOutput(self, "ChromaBucketName", value=chroma_bucket.bucket_name)
        CfnOutput(self, "FrontendBucketName", value=frontend_bucket.bucket_name)
