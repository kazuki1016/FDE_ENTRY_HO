"""AWS本番エンドポイントに対する応答時間（コールドスタート含む）の評価スクリプト。

evals/run_eval.py（正解率の評価）とは異なり、ローカルの関数呼び出しではなく、
デプロイ済みのAWSエンドポイント（CloudFront経由）へ実際にHTTPSでPOSTし、
Lambdaのコールドスタートを含む実際のエンドツーエンドのレイテンシを計測する。
evals/eval_set.json の同じ10問を再利用する。

合格基準は req.md NFR-1（回答生成は60秒以内に完了する）に従い、全問が60秒以内であること。

CI/CDには含めない（run_eval.py と同様、AWS本番環境への接続とBedrock課金を伴うため。
mainマージ前・リリース後の動作確認として人間が手動実行する）。

実行前に必要な環境変数（.env等）:
  まず、aws login でAWS認証情報を取得しておくこと
  RAG_ENDPOINT_URL      デプロイ済みCloudFrontのURL（例: https://xxxx.cloudfront.net）
  AWS_SECRETS_NAME       Secrets Manager経由でBasic認証情報を取得する場合に設定
                          （config.pyの既存の遅延取得の仕組みをそのまま利用する）
                          未設定の場合は BASIC_AUTH_USERNAME・BASIC_AUTH_PASSWORD を
                          直接環境変数として設定する

実行例:
  RAG_ENDPOINT_URL=https://xxxx.cloudfront.net PYTHONPATH=src python3 evals/run_latency_eval.py
"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402

EVAL_SET_PATH = os.path.join(os.path.dirname(__file__), "eval_set.json")
SLA_SEC = 60  # req.md NFR-1: 回答生成は60秒以内に完了する
REQUEST_TIMEOUT_SEC = 90  # Lambda関数タイムアウト(90秒)に合わせ、正常応答を途中で切らない


def run_latency_eval() -> list[dict]:
    endpoint = os.environ.get("RAG_ENDPOINT_URL")
    if not endpoint:
        print("環境変数 RAG_ENDPOINT_URL が未設定です（例: https://xxxx.cloudfront.net）")
        sys.exit(1)

    if not config.BASIC_AUTH_USERNAME or not config.BASIC_AUTH_PASSWORD:
        print(
            "Basic認証情報が未設定です。環境変数 AWS_SECRETS_NAME=fde-rag/aws-secrets を設定するか"
            "（Secrets Managerから取得。ローカルのAWS認証情報が必要）、"
            "BASIC_AUTH_USERNAME・BASIC_AUTH_PASSWORD を直接設定してください。"
        )
        sys.exit(1)

    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        eval_set = json.load(f)

    auth = (config.BASIC_AUTH_USERNAME, config.BASIC_AUTH_PASSWORD)
    results = []

    for i, item in enumerate(eval_set, start=1):
        question = item["question"]
        start = time.monotonic()
        try:
            response = requests.post(
                f"{endpoint.rstrip('/')}/ask",
                json={"question": question},
                auth=auth,
                timeout=REQUEST_TIMEOUT_SEC,
            )
            latency_sec = time.monotonic() - start
            ok = response.status_code == 200 and latency_sec <= SLA_SEC
            status_code = response.status_code
        except requests.exceptions.RequestException as exc:
            latency_sec = time.monotonic() - start
            ok = False
            status_code = f"ERROR: {exc}"

        results.append(
            {
                "index": i,
                "question": question,
                "latency_sec": latency_sec,
                "status_code": status_code,
                "ok": ok,
            }
        )

        status = "PASS" if ok else "FAIL"
        cold_note = "（コールドスタートの可能性あり）" if i == 1 else ""
        print(f"[{status}] #{i}: {question} — {latency_sec:.2f}秒 (status={status_code}){cold_note}")

    return results


if __name__ == "__main__":
    results = run_latency_eval()
    latencies = [r["latency_sec"] for r in results]
    all_ok = all(r["ok"] for r in results)

    print(f"\n最小: {min(latencies):.2f}秒 / 平均: {sum(latencies) / len(latencies):.2f}秒 / 最大: {max(latencies):.2f}秒")
    print(f"1問目（コールドスタート想定）: {latencies[0]:.2f}秒")

    if all_ok:
        print(f"\n全問がSLA（{SLA_SEC}秒）以内に完了しました。")
        sys.exit(0)
    else:
        failed = [r["index"] for r in results if not r["ok"]]
        print(f"\nSLA（{SLA_SEC}秒）を超過、またはエラーになった質問: {failed}")
        sys.exit(1)
