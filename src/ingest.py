"""PDF取り込み・チャンキング・ベクトルDB格納。

セクション境界検出（spec.md [要確認]#5, PENDING）は、本講座PDFのスライド見出し
（「S E C T I O N N」区切りページ、「Section N …」本文見出し、
「SECTION N — まとめ」まとめページ、「Capstone」表記）をページ単位で走査する
方式で実装する。
"""
import re
from typing import Protocol, TypedDict

import chromadb
from sentence_transformers import SentenceTransformer

import config

_SECTION_AFTER = re.compile(r"SECTION([0-7])", re.IGNORECASE)
_SECTION_BEFORE = re.compile(r"(\d)SECTION", re.IGNORECASE)


class Chunk(TypedDict):
    content: str
    section_number: str
    page_number: int
    title: str


class VectorStoreProtocol(Protocol):
    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...
    def count(self) -> int: ...
    def query(self, query_embedding: list[float], top_k: int) -> list[Chunk]: ...


class ChromaVectorStore:
    """VectorStoreProtocol の ChromaDB 実装（NFR-4: 差し替え可能）。"""

    def __init__(self, persist_path: str, collection_name: str = "course_chunks"):
        client = chromadb.PersistentClient(path=persist_path)
        self._collection = client.get_or_create_collection(
            collection_name,
            metadata={"hnsw:space": config.DISTANCE_FUNCTION},
        )

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        ids = [f"chunk-{i:05d}" for i in range(len(chunks))]
        self._collection.upsert(
            ids=ids,
            documents=[c["content"] for c in chunks],
            embeddings=embeddings,
            metadatas=[
                {
                    "section_number": c["section_number"],
                    "page_number": c["page_number"],
                    "title": c["title"],
                }
                for c in chunks
            ],
        )

    def count(self) -> int:
        return self._collection.count()

    def query(self, query_embedding: list[float], top_k: int) -> list[Chunk]:
        result = self._collection.query(query_embeddings=[query_embedding], n_results=top_k)
        documents = result["documents"][0] if result["documents"] else []
        metadatas = result["metadatas"][0] if result["metadatas"] else []
        return [
            {
                "content": doc,
                "section_number": meta["section_number"],
                "page_number": meta["page_number"],
                "title": meta["title"],
            }
            for doc, meta in zip(documents, metadatas)
        ]


def _detect_section(lines: list[str], current: str) -> str:
    header_lines = [line.replace(" ", "") for line in lines[:3]]
    if any(hl.lower().startswith("capstone") for hl in header_lines):
        return "Capstone"
    header = "".join(header_lines)
    m = _SECTION_AFTER.search(header)
    if m:
        return f"Section {m.group(1)}"
    m = _SECTION_BEFORE.search(header)
    if m:
        return f"Section {m.group(1)}"
    return current


def _extract_title(lines: list[str]) -> str:
    if len(lines) > 2 and lines[1].replace(" ", "").upper() == "SECTION":
        return lines[2]
    if len(lines) > 1:
        return lines[1]
    return lines[0] if lines else ""


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    pieces = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        pieces.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return pieces


def extract_chunks(pdf_path: str) -> list[Chunk]:
    # fitz(PyMuPDF)はPDF取り込み（オフライン・reingest時のみ）でしか使わないため遅延importにする。
    # Lambda Container Image（spec_infra.md 2.6章）ではPDF解析を行わないため同梱しない
    # （C拡張のビルドにコンパイラが必要でイメージサイズも大きいため除外している）。
    import fitz

    doc = fitz.open(pdf_path)
    chunks: list[Chunk] = []
    current_section = "Section 0"
    for i in range(doc.page_count):
        text = doc[i].get_text()
        lines = [line for line in text.split("\n") if line.strip()]
        if not lines:
            continue
        current_section = _detect_section(lines, current_section)
        title = _extract_title(lines)
        page_number = i + 1
        for piece in _split_text(text.strip(), config.CHUNK_SIZE, config.CHUNK_OVERLAP):
            chunks.append(
                {
                    "content": piece,
                    "section_number": current_section,
                    "page_number": page_number,
                    "title": title,
                }
            )
    doc.close()
    return chunks


def ingest(pdf_path: str | None = None, store: VectorStoreProtocol | None = None) -> int:
    pdf_path = pdf_path or config.PDF_PATH
    store = store or ChromaVectorStore(config.CHROMA_DB_PATH)
    chunks = extract_chunks(pdf_path)
    model = SentenceTransformer(config.EMBEDDING_MODEL)
    embeddings = model.encode([c["content"] for c in chunks]).tolist()
    store.add_chunks(chunks, embeddings)
    return store.count()


if __name__ == "__main__":
    total = ingest()
    print(f"取り込み完了: {total} チャンク")
