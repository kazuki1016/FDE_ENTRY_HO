"""LLM回答生成（spec.md 4.3）。Amazon Bedrock経由でClaudeを呼び出す。"""
from typing import Protocol

from anthropic import AnthropicBedrock

import config
from ingest import Chunk

SYSTEM_PROMPT = (
    "あなたは「ハーネスエンジニアリング入門」講座の質問応答アシスタントです。"
    "提供されたコンテキストのみを使用して、日本語で回答してください。"
    "コンテキストに含まれない知識で回答してはいけません。"
    "コンテキストに質問へ回答するための情報が含まれていない場合は、"
    "「講座内容に該当する情報がありません」という文言を含む文で回答してください。"
    "回答には参照元のページ番号を付記してください。"
)


class LLMBackendProtocol(Protocol):
    def generate(self, question: str, chunks: list[Chunk]) -> str: ...


class BedrockLLMBackend:
    """LLMBackendProtocol の Amazon Bedrock実装（NFR-4: 差し替え可能）。"""

    def __init__(self):
        self._client = AnthropicBedrock(
            api_key=config.AWS_BEARER_TOKEN_BEDROCK,
            aws_region=config.AWS_REGION,
            timeout=config.TIMEOUT_SEC,
        )

    def generate(self, question: str, chunks: list[Chunk]) -> str:
        context = "\n\n".join(
            f"[Section {c['section_number']}, p.{c['page_number']}] {c['content']}"
            for c in chunks
        )
        message = self._client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"コンテキスト:\n{context}\n\n質問: {question}",
                }
            ],
        )
        return "".join(block.text for block in message.content if block.type == "text")


def generate_answer(
    question: str,
    chunks: list[Chunk],
    backend: LLMBackendProtocol | None = None,
) -> str:
    backend = backend or BedrockLLMBackend()
    return backend.generate(question, chunks)
