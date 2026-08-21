"""アプリケーション設定。値は環境変数（.env）から読み込む。

spec.md 付記の [要確認] 項目は CLAUDE.md 5.2 の3段階区分に従う:
- 確定値: ユーザー確認済み
- PENDING: 未確認だが合理的な既定値を使用中（コメント付き）

AWS構成（spec_infra.md）向けの注記:
- `API_KEY` はngrok構成でのみ設定される（AWS構成ではBasic認証を使うため未設定=Noneでよい）
- `AWS_BEARER_TOKEN_BEDROCK`・`BASIC_AUTH_USERNAME`・`BASIC_AUTH_PASSWORD` は
  モジュール読み込み時に即評価すると、値が未設定の環境（Lambda等）で `KeyError` により
  インポート自体が失敗する（spec_infra.md 4.3章 C-1・C-NEW-2・C-3RD-2 で指摘）。
  そのため `__getattr__`（PEP 562）経由の遅延取得にしている。`AWS_SECRETS_NAME` が
  設定されていれば AWS Secrets Manager から取得し（`get_secrets()`、初回アクセス時に
  1度だけ呼ばれ以降はキャッシュされる）、未設定なら対応する環境変数にフォールバックする
  （ngrok構成の既存動作を変えない）。
"""
import json
import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

# ── 確定値 ──
PDF_PATH = os.getenv("PDF_PATH", "harness_engineering_intro.pdf")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "data/chroma_db")
LOG_PATH = os.getenv("LOG_PATH")  # 未設定時はAWS構成とみなし標準出力に切り替える（server.py _log_request参照）
TOP_K = 5  # eval実行時、k=3ではSection5/Capstoneの正解ページが上位に入らずスコア70%だったため5に変更（ユーザー確認済み）
TIMEOUT_SEC = 45  # 元は60。CloudFrontのLambda Function URLオリジンread_timeoutも60秒で、
# ベクトル検索・Lambdaオーバーヘッド分の余白がなくCloudFront側のタイムアウトが先に発生し
# HTMLエラーページが返る不具合が本番で発生したため、余白を確保する値に短縮した（ユーザー確認済み）

API_KEY_HEADER = "X-API-Key"
API_KEY = os.environ.get("APP_API_KEY")  # ngrok構成でのみ設定。AWS構成ではNone（Basic認証を使用）

# LLMバックエンドはAmazon Bedrock経由でClaudeを呼び出す（ユーザー確認済み）。
# ベアラートークン方式のBedrock APIキー認証を使用し、AWS IAMアクセスキー/シークレットは使用しない。
# 値自体は下部の __getattr__ 経由で遅延取得する（AWS_BEARER_TOKEN_BEDROCK）。
AWS_SECRETS_NAME = os.getenv("AWS_SECRETS_NAME")  # AWS構成でのみ設定。Secrets Manager由来の値取得を有効化する
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")  # 確定値。東京リージョン（ユーザー確認済み）

_SECRET_KEYS = ("AWS_BEARER_TOKEN_BEDROCK", "BASIC_AUTH_USERNAME", "BASIC_AUTH_PASSWORD")


@lru_cache(maxsize=1)
def get_secrets() -> dict:
    """Secrets Manager由来の値を遅延取得しキャッシュする（spec_infra.md 4.3章）。

    AWS_SECRETS_NAME が未設定の場合（ngrok構成）は、対応する環境変数へフォールバックする。
    """
    if not AWS_SECRETS_NAME:
        return {
            "AWS_BEARER_TOKEN_BEDROCK": os.environ.get("AWS_BEARER_TOKEN_BEDROCK"),
            "BASIC_AUTH_USERNAME": os.environ.get("BASIC_AUTH_USERNAME"),
            "BASIC_AUTH_PASSWORD": os.environ.get("BASIC_AUTH_PASSWORD"),
        }
    import boto3

    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    raw = client.get_secret_value(SecretId=AWS_SECRETS_NAME)["SecretString"]
    return json.loads(raw)


def __getattr__(name: str):
    if name in _SECRET_KEYS:
        return get_secrets().get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# ── PENDING（ユーザー未確認。デフォルト値を使用中） ──
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")  # [PENDING] ユーザー未確認。日本語コンテンツのため多言語モデルをデフォルトとして使用中
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))  # [PENDING] ユーザー未確認。デフォルト値を使用中
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))  # [PENDING] ユーザー未確認。デフォルト値を使用中
DISTANCE_FUNCTION = os.getenv("DISTANCE_FUNCTION", "cosine")  # [PENDING] ユーザー未確認。デフォルト値を使用中
# モデルはclaude-sonnet-4.6を使用（ユーザー確認済み）。BedrockモデルID表記は jp.anthropic.claude-sonnet-4-6（東京リージョンAWS_REGIONに合わせたリージョンプレフィックス）。[PENDING] 実機での疎通検証が必要
ANTHROPIC_MODEL = os.getenv("LLM_MODEL", "jp.anthropic.claude-sonnet-4-6")
LAST_UPDATED_FORMAT = "%Y-%m-%dT%H:%M:%S%z"  # [PENDING] ユーザー未確認。ISO 8601をデフォルトとして使用中
HEALTH_STATS_AUTH_REQUIRED = False  # [PENDING] ユーザー未確認。認証不要をデフォルトとして使用中
