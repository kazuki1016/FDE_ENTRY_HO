# ハーネスエンジニアリング入門 講座PDF RAGシステム

「ハーネスエンジニアリング入門」講座PDFに対する質問応答RAGシステム。詳細な仕様は `spec.md`、制約は `CLAUDE.md` を参照。

## セットアップ

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`.env` に以下を設定する（`.env.example` は用意していないため、`src/config.py` を参照して作成する）:

- `APP_API_KEY`: `POST /ask` 用のクライアント認証キー
- `AWS_BEARER_TOKEN_BEDROCK`: Amazon Bedrock APIキー（ベアラートークン）
- `AWS_REGION`: 例 `ap-northeast-1`
- `LLM_MODEL`: 例 `jp.anthropic.claude-sonnet-4-6`
- `PDF_PATH` / `CHROMA_DB_PATH` / `LOG_PATH`: 未設定時は `config.py` の既定値を使用

PDF取り込み（`data/chroma_db/` にベクトルDBを構築。テスト・eval実行前に必須）:

```bash
PYTHONPATH=src .venv/bin/python src/ingest.py
```

## テスト実行

```bash
.venv/bin/python -m pytest tests/ -v
```

`tests/test_retriever.py` はテスト内で独立したChromaDBに再取り込みするため、本番`data/chroma_db/`が未構築でも実行可能。`test_generator.py` / `test_server.py` はAmazon Bedrockへの実APIコールを行う（モックなし）。

## eval実行

```bash
.venv/bin/python evals/run_eval.py
```

`evals/eval_set.json` の10問を実行し、期待セクション・期待キーワードの一致で採点する。スコア80%以上（8問以上正解）が合格基準（CLAUDE.md 5.3）。未達の場合はngrok公開しない。

## サーバー起動

```bash
PYTHONPATH=src .venv/bin/uvicorn server:app --port 8000
```

`http://localhost:8000/health` でヘルスチェック、`http://localhost:8000/` でWeb UIを確認できる。
