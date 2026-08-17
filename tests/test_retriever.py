"""AC-2: 検索精度の受け入れ基準を検証する（spec.md 5章）。"""
import pytest

import config
from ingest import ChromaVectorStore, ingest
from retriever import search


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("chroma_db")
    vector_store = ChromaVectorStore(str(path))
    ingest(pdf_path=config.PDF_PATH, store=vector_store)
    return vector_store


def test_5本柱の質問でSection1が上位3件に含まれること(store):
    results = search("ハーネス設計の5本柱とは？", store=store)

    assert any(r["section_number"] == "Section 1" for r in results)  # AC-2-1


def test_コンフォーマンス監査の質問でSection6が上位3件に含まれること(store):
    results = search("コンフォーマンス監査とは？", store=store)

    assert any(r["section_number"] == "Section 6" for r in results)  # AC-2-2


def test_rippable_harnessの質問でSection7が上位3件に含まれること(store):
    results = search("rippable harnessとは？", store=store)

    assert any(r["section_number"] == "Section 7" for r in results)  # AC-2-3
