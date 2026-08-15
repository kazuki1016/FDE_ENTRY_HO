"""アプリケーション設定。値は環境変数（.env）から読み込む。

spec.md 付記の [要確認] 項目は CLAUDE.md 5.2 の3段階区分に従う:
- 確定値: ユーザー確認済み
- PENDING: 未確認だが合理的な既定値を使用中（コメント付き）
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ── 確定値 ──
PDF_PATH = os.getenv("PDF_PATH", "harness_engineering_intro.pdf")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "data/chroma_db")
LOG_PATH = os.getenv("LOG_PATH", "logs/requests.jsonl")
TOP_K = 3
TIMEOUT_SEC = 60

API_KEY_HEADER = "X-API-Key"
API_KEY = os.environ["APP_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# ── PENDING（ユーザー未確認。デフォルト値を使用中） ──
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")  # [PENDING] ユーザー未確認。デフォルト値を使用中
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))  # [PENDING] ユーザー未確認。デフォルト値を使用中
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))  # [PENDING] ユーザー未確認。デフォルト値を使用中
DISTANCE_FUNCTION = os.getenv("DISTANCE_FUNCTION", "cosine")  # [PENDING] ユーザー未確認。デフォルト値を使用中
ANTHROPIC_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5")  # [PENDING] ユーザー未確認。デフォルト値を使用中
LAST_UPDATED_FORMAT = "%Y-%m-%dT%H:%M:%S%z"  # [PENDING] ユーザー未確認。ISO 8601をデフォルトとして使用中
HEALTH_STATS_AUTH_REQUIRED = False  # [PENDING] ユーザー未確認。認証不要をデフォルトとして使用中
