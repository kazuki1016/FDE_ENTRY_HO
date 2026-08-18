"""FastAPI サーバー（spec.md 2章）。POST /ask, GET /health, GET /stats を実装する。

LLMバックエンド（generator.py）とベクトルDB（ingest.py・retriever.py）への直接依存は
持たず、それぞれの公開関数（generate_answer, search）を介して利用する（NFR-4）。
"""
import json
import os
import time
import traceback
from datetime import datetime, timezone
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
_store = ChromaVectorStore(config.CHROMA_DB_PATH)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
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


def _require_api_key(x_api_key: Optional[str] = Header(default=None, alias=config.API_KEY_HEADER)) -> None:
    if x_api_key != config.API_KEY:
        raise HTTPException(status_code=403, detail="認証に失敗しました")


def _require_api_key_if_enabled(x_api_key: Optional[str] = Header(default=None, alias=config.API_KEY_HEADER)) -> None:
    if config.HEALTH_STATS_AUTH_REQUIRED and x_api_key != config.API_KEY:
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
    os.makedirs(os.path.dirname(config.LOG_PATH), exist_ok=True)
    with open(config.LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, _: None = Depends(_require_api_key)):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question は必須です")

    start = time.monotonic()
    try:
        chunks = search(request.question, store=_store)
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
        chunk_count = _store.count()
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
