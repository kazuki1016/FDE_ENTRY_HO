"""クエリembedding生成 → ベクトル類似度検索（spec.md 4.2）。

チャンクの格納は ingest.py の責務（spec.md 4.1）。ここではクエリを embedding に変換し、
VectorStoreProtocol（ingest.py）経由で上位k件を検索する。
"""
import config
from ingest import ChromaVectorStore, Chunk, VectorStoreProtocol, embed_text


def search(
    query: str,
    top_k: int = config.TOP_K,
    store: VectorStoreProtocol | None = None,
) -> list[Chunk]:
    store = store or ChromaVectorStore(config.CHROMA_DB_PATH)
    query_embedding = embed_text(query)
    return store.query(query_embedding, top_k)
