"""eval実行スクリプト（spec.md 5章 / CLAUDE.md 5.3）。

evals/eval_set.json の全10問を実行し、期待セクション・期待キーワードの一致で採点する。
スコア80%以上（8問以上正解）を合格基準とする。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from generator import generate_answer  # noqa: E402
from ingest import ChromaVectorStore  # noqa: E402
from retriever import search  # noqa: E402
import config  # noqa: E402

EVAL_SET_PATH = os.path.join(os.path.dirname(__file__), "eval_set.json")
PASS_THRESHOLD = 0.8


def run_eval() -> tuple[int, int]:
    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        eval_set = json.load(f)

    store = ChromaVectorStore(config.CHROMA_DB_PATH)
    passed = 0

    for i, item in enumerate(eval_set, start=1):
        question = item["question"]
        expected_section = item["expected_section"]
        expected_keywords = item["expected_keywords"]

        chunks = search(question, store=store)
        answer = generate_answer(question, chunks)

        section_ok = expected_section is None or any(
            c["section_number"] == expected_section for c in chunks
        )
        keyword_ok = any(kw in answer for kw in expected_keywords)
        ok = section_ok and keyword_ok

        if ok:
            passed += 1

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] #{i}: {question}")
        if not ok:
            print(f"       expected_section={expected_section} (matched={section_ok})")
            print(f"       expected_keywords={expected_keywords} (matched={keyword_ok})")
            print(f"       answer: {answer[:200]}")

    return passed, len(eval_set)


if __name__ == "__main__":
    passed, total = run_eval()
    score = passed / total
    print(f"\nスコア: {passed}/{total} ({score:.0%})")

    if score >= PASS_THRESHOLD:
        print("合格基準（80%以上）を満たしました。")
        sys.exit(0)
    else:
        print("合格基準（80%以上）未達です。ngrok公開は行わないでください。")
        sys.exit(1)
