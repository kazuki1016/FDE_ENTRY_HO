# AWS Lambda Container Image（spec_infra.md 2.6章）。
#
# Python 3.11イメージはAmazon Linux 2ベースでEOL済み（サポート終了2026-06-30）、
# glibcが古く多数のパッケージのプリビルドwheelと非互換のためビルド時に発覚し、
# Python 3.12（Amazon Linux 2023ベース、サポート終了2029-06-30）に変更した
# （spec_infra.md 2.4章、ユーザー確認済み）。
FROM public.ecr.aws/lambda/python:3.12

# requirements.txt はngrok構成・reingestワークフローとの単一ソース(Simplicity First)だが、
# pymupdf(fitz)はPDF取り込み専用（Lambda実行時は使わない。ingest.pyでは遅延importにしてある）で
# Cコンパイラなしではソースビルドに失敗するため、pyngrok(ngrok専用)と合わせてLambdaイメージからは除外する。
COPY requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN grep -v -E "^(pymupdf|pyngrok)==" ${LAMBDA_TASK_ROOT}/requirements.txt > ${LAMBDA_TASK_ROOT}/requirements-lambda.txt \
    && pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt

COPY src/ ${LAMBDA_TASK_ROOT}/
COPY templates/ ${LAMBDA_TASK_ROOT}/templates/

CMD ["lambda_handler.handler"]
