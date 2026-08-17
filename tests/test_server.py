"""AC-4: API動作の受け入れ基準を検証する（spec.md 5章）。実APIを呼び出す。"""
from fastapi.testclient import TestClient

import config
from server import app

client = TestClient(app)


def test_ヘルスチェックが200でokを返すこと():
    response = client.get("/health")

    assert response.status_code == 200  # AC-4-2
    assert response.json() == {"status": "ok"}


def test_認証ヘッダーなしでPOST_askを呼ぶと403が返ること():
    response = client.post("/ask", json={"question": "test"})

    assert response.status_code == 403  # AC-4-3


def test_質問が空文字だと400が返ること():
    response = client.post(
        "/ask",
        json={"question": ""},
        headers={config.API_KEY_HEADER: config.API_KEY},
    )

    assert response.status_code == 400


def test_認証済みでPOST_askを呼ぶと回答とsourcesが返ること():
    response = client.post(
        "/ask",
        json={"question": "FDEとは何ですか？"},
        headers={config.API_KEY_HEADER: config.API_KEY},
    )

    assert response.status_code == 200  # AC-4-1
    body = response.json()
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["sources"], list) and len(body["sources"]) >= 1
    assert isinstance(body["sources"][0]["page"], int)
