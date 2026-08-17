"""クエリembedding生成 → ベクトル類似度検索（spec.md 4.2）。

チャンクの格納は ingest.py の責務（spec.md 4.1）。ここではクエリを embedding に変換し、
VectorStoreProtocol（ingest.py）経由で上位k件を検索する。
"""
from functools import lru_cache

from sentence_transformers import SentenceTransformer

import config
from ingest import ChromaVectorStore, Chunk, VectorStoreProtocol


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    return SentenceTransformer(config.EMBEDDING_MODEL)


def search(
    query: str,
    top_k: int = config.TOP_K,
    store: VectorStoreProtocol | None = None,
) -> list[Chunk]:
    store = store or ChromaVectorStore(config.CHROMA_DB_PATH)
    query_embedding = _load_model().encode(query).tolist()
    return store.query(query_embedding, top_k)
