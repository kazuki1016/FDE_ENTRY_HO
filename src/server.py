"""FastAPI サーバー（spec.md 2章）。POST /ask, GET /health, GET /stats を実装する。

LLMバックエンド（generator.py）とベクトルDB（ingest.py・retriever.py）への直接依存は
持たず、それぞれの公開関数（generate_answer, search）を介して利用する（NFR-4）。
"""
import base64
import hmac
import json
import os
import time
import traceback
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import config
from generator import generate_answer
from ingest import ChromaVectorStore
from retriever import search

app = FastAPI()


@lru_cache(maxsize=1)
def get_store() -> ChromaVectorStore:
    # モジュール読み込み時に即初期化しない（spec_infra.md 4.3章 C-NEW-2）。
    # AWS構成ではLambdaハンドラーがS3からのダウンロード・展開を終えた後に
    # 初めて呼ばれる必要があるため、遅延初期化にしている。
    return ChromaVectorStore(config.CHROMA_DB_PATH)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    # CLAUDE.md: 使用するステータスコードは200/400/403/500に限定する（422は使用しない）
    return JSONResponse(status_code=400, content={"detail": "リクエスト形式が不正です"})


class AskRequest(BaseModel):
    question: str = ""


class Source(BaseModel):
    page: int
    section: str
    title: str


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]


def _api_key_matches(x_api_key: Optional[str]) -> bool:
    if x_api_key is None:
        return False
    return hmac.compare_digest(x_api_key, config.API_KEY)


def _basic_auth_matches(authorization: Optional[str]) -> bool:
    if authorization is None or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization.removeprefix("Basic ")).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:
        return False
    return hmac.compare_digest(username, config.BASIC_AUTH_USERNAME) and hmac.compare_digest(
        password, config.BASIC_AUTH_PASSWORD
    )


def _is_authorized(x_api_key: Optional[str], authorization: Optional[str]) -> bool:
    # ngrok構成: APIキー認証、AWS構成: Basic認証（spec_infra.md 4章）。
    # どちらも未設定の場合はフェイルクローズ（全リクエスト拒否）とする
    # （spec_infra.md 4.3章 C-NEW-3。認証バイパスの脆弱性ゼロというCLAUDE.md 6章の品質ゲートに直結）。
    if config.API_KEY:
        return _api_key_matches(x_api_key)
    if config.BASIC_AUTH_USERNAME and config.BASIC_AUTH_PASSWORD:
        return _basic_auth_matches(authorization)
    return False


def _require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias=config.API_KEY_HEADER),
    authorization: Optional[str] = Header(default=None),
) -> None:
    if not _is_authorized(x_api_key, authorization):
        raise HTTPException(status_code=403, detail="認証に失敗しました")


def _require_api_key_if_enabled(
    x_api_key: Optional[str] = Header(default=None, alias=config.API_KEY_HEADER),
    authorization: Optional[str] = Header(default=None),
) -> None:
    if config.HEALTH_STATS_AUTH_REQUIRED and not _is_authorized(x_api_key, authorization):
        raise HTTPException(status_code=403, detail="認証に失敗しました")


def _log_request(query: str, retrieved_chunks: list, answer: Optional[str], latency_ms: int, error: Optional[str] = None) -> None:
    entry = {
        "query": query,
        "retrieved_chunks": retrieved_chunks,
        "answer": answer,
        "latency_ms": latency_ms,
    }
    if error:
        entry["error"] = error
    if config.LOG_PATH:
        # ngrok構成: ファイル書き込み
        os.makedirs(os.path.dirname(config.LOG_PATH), exist_ok=True)
        with open(config.LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    else:
        # AWS構成: 標準出力（Lambdaの標準機能でCloudWatch Logsに自動収集される。spec_infra.md 8.5章）
        print(json.dumps(entry, ensure_ascii=False))


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, _: None = Depends(_require_api_key)):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question は必須です")

    start = time.monotonic()
    try:
        chunks = search(request.question, store=get_store())
        answer = generate_answer(request.question, chunks)
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        _log_request(request.question, [], None, latency_ms, error=traceback.format_exc())
        raise HTTPException(status_code=500, detail="内部エラーが発生しました") from exc

    latency_ms = int((time.monotonic() - start) * 1000)
    _log_request(request.question, chunks, answer, latency_ms)

    sources = [
        {"page": c["page_number"], "section": c["section_number"], "title": c["title"]}
        for c in chunks
    ]
    return {"answer": answer, "sources": sources}


@app.get("/health")
def health(_: None = Depends(_require_api_key_if_enabled)):
    return {"status": "ok"}


@app.get("/stats")
def stats(_: None = Depends(_require_api_key_if_enabled)):
    try:
        chunk_count = get_store().count()
        db_file = os.path.join(config.CHROMA_DB_PATH, "chroma.sqlite3")
        last_updated = (
            datetime.fromtimestamp(os.path.getmtime(db_file), tz=timezone.utc).strftime(config.LAST_UPDATED_FORMAT)
            if os.path.exists(db_file)
            else None
        )
        return {"chunk_count": chunk_count, "last_updated": last_updated}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="内部エラーが発生しました") from exc


@app.get("/", response_class=HTMLResponse)
def index():
    with open("templates/index.html", encoding="utf-8") as f:
        html = f.read()
    return html.replace("__API_KEY_JSON__", json.dumps(config.API_KEY))
