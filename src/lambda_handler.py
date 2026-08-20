"""AWS Lambda エントリーポイント（spec_infra.md 3.3章・9章）。

Lambda Function URL のイベントを FastAPI アプリへ Mangum で橋渡しする。コールドスタート時は
S3 から ChromaDB アーカイブ（tar.gz）をダウンロード・展開してから server.app をインポートする。
server.py の ChromaDB クライアントは get_store() で遅延初期化されるため（spec_infra.md 4.3章
C-NEW-2）、本モジュールが CHROMA_DB_PATH を /tmp/chroma_db に切り替えた後に import すれば、
S3ダウンロードより前に空のDBが作られてしまう不整合は起きない。
"""
import os
import tarfile

import boto3

_CHROMA_TMP_DIR = "/tmp/chroma_db"
_CHROMA_ARCHIVE_PATH = "/tmp/chroma_db_latest.tar.gz"


def _ensure_chroma_db() -> None:
    if os.path.isdir(_CHROMA_TMP_DIR):
        return  # ウォームスタート: 展開済みのキャッシュをそのまま使う（spec_infra.md 3.3章 2b）

    bucket = os.environ["CHROMA_S3_BUCKET"]
    key = os.environ.get("CHROMA_S3_KEY", "chroma_db_latest.tar.gz")

    s3 = boto3.client("s3")
    try:
        s3.download_file(bucket, key, _CHROMA_ARCHIVE_PATH)
    except Exception as exc:
        # S3にアーカイブが存在しない場合もここに到達する（spec_infra.md AC-INFRA-3-3）。
        # ここはLambdaのコールドスタート初期化中（Mangum/FastAPI起動前）に発生するため、
        # 例外メッセージはFastAPI経由の日本語レスポンスにはならない。ASCII以外の文字を含めると
        # awslambdaricのpost_init_errorがLatin-1エンコードに失敗しUnicodeEncodeErrorで
        # 二次クラッシュする（実装時にAC-INFRA-3-3の検証で発覚）ため、英語で記述する。
        raise RuntimeError(f"Failed to fetch ChromaDB archive: s3://{bucket}/{key}") from exc

    with tarfile.open(_CHROMA_ARCHIVE_PATH) as tar:
        tar.extractall("/tmp")

    if not os.path.isdir(_CHROMA_TMP_DIR):
        raise RuntimeError(f"{_CHROMA_TMP_DIR} not found after extracting ChromaDB archive")


# server.py（config経由）が CHROMA_DB_PATH を読み込む前に、Lambda用のパスへ切り替える。
_ensure_chroma_db()
os.environ["CHROMA_DB_PATH"] = _CHROMA_TMP_DIR

from mangum import Mangum  # noqa: E402
from server import app  # noqa: E402

handler = Mangum(app)
