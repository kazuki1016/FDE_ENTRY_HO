"""AC-4: API動作の受け入れ基準を検証する（spec.md 5章）。実APIを呼び出す。

AWS構成向けのBasic認証テスト（spec_infra.md 4章・4.3章）は、config.API_KEY を
monkeypatch で無効化し、config.BASIC_AUTH_USERNAME/PASSWORD を設定した状態で検証する。
"""
import base64

from fastapi.testclient import TestClient

import config
from server import app

client = TestClient(app)


def _basic_auth_header(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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


def test_Basic認証ヘッダーなしでPOST_askを呼ぶと403が返ること(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    monkeypatch.setattr(config, "BASIC_AUTH_USERNAME", "aws-user")
    monkeypatch.setattr(config, "BASIC_AUTH_PASSWORD", "aws-pass")

    response = client.post("/ask", json={"question": "test"})

    assert response.status_code == 403  # spec_infra.md AC-INFRA-2-1


def test_誤ったBasic認証でPOST_askを呼ぶと403が返ること(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    monkeypatch.setattr(config, "BASIC_AUTH_USERNAME", "aws-user")
    monkeypatch.setattr(config, "BASIC_AUTH_PASSWORD", "aws-pass")

    response = client.post(
        "/ask",
        json={"question": "test"},
        headers=_basic_auth_header("aws-user", "wrong-pass"),
    )

    assert response.status_code == 403  # spec_infra.md AC-INFRA-2-2


def test_正しいBasic認証でPOST_askが200を返すこと(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", None)
    monkeypatch.setattr(config, "BASIC_AUTH_USERNAME", "aws-user")
    monkeypatch.setattr(config, "BASIC_AUTH_PASSWORD", "aws-pass")

    response = client.post(
        "/ask",
        json={"question": "FDEとは何ですか？"},
        headers=_basic_auth_header("aws-user", "aws-pass"),
    )

    assert response.status_code == 200  # spec_infra.md AC-INFRA-2-3
    body = response.json()
    assert isinstance(body["answer"], str) and body["answer"]


def test_認証方式が両方未設定の場合にPOST_askが403を返すこと(monkeypatch):
    # フェイルクローズ: APIキー・Basic認証のどちらも未設定なら全リクエスト拒否する
    # （spec_infra.md 4.3章 C-NEW-3。認証バイパスの脆弱性ゼロという品質ゲートに直結）
    monkeypatch.setattr(config, "API_KEY", None)
    monkeypatch.setattr(config, "BASIC_AUTH_USERNAME", None)
    monkeypatch.setattr(config, "BASIC_AUTH_PASSWORD", None)

    response = client.post("/ask", json={"question": "test"})

    assert response.status_code == 403
