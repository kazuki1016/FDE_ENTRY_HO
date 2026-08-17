"""AC-1: PDF取り込みの受け入れ基準を検証する（spec.md 5章）。"""
import config
from ingest import ChromaVectorStore, extract_chunks, ingest


def test_チャンクにメタデータが揃っていること():
    chunks = extract_chunks(config.PDF_PATH)

    assert len(chunks) >= 10  # AC-1-1（抽出段階での事前確認）

    for chunk in chunks:  # AC-1-2
        assert chunk["section_number"]
        assert isinstance(chunk["page_number"], int) and chunk["page_number"] >= 1
        assert chunk["title"]
        assert chunk["content"]


def test_取り込んだチャンク数が10件以上であること(tmp_path):
    store = ChromaVectorStore(str(tmp_path / "chroma_db"))

    count = ingest(pdf_path=config.PDF_PATH, store=store)

    assert count >= 10  # AC-1-1
    assert store.count() >= 10
