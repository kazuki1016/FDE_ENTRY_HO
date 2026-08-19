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
        # S3にアーカイブが存在しない場合もここに到達する（spec_infra.md AC-INFRA-3-3: 500を期待）
        raise RuntimeError(f"ChromaDBアーカイブの取得に失敗しました: s3://{bucket}/{key}") from exc

    with tarfile.open(_CHROMA_ARCHIVE_PATH) as tar:
        tar.extractall("/tmp")

    if not os.path.isdir(_CHROMA_TMP_DIR):
        raise RuntimeError(f"ChromaDBアーカイブの展開後に {_CHROMA_TMP_DIR} が見つかりません")


# server.py（config経由）が CHROMA_DB_PATH を読み込む前に、Lambda用のパスへ切り替える。
_ensure_chroma_db()
os.environ["CHROMA_DB_PATH"] = _CHROMA_TMP_DIR

from mangum import Mangum  # noqa: E402
from server import app  # noqa: E402

handler = Mangum(app)
