# AWS Lambda Container Image（spec_infra.md 2.6章）。
#
# ZIP/レイヤー方式はtorch+sentence-transformers+transformersの合計サイズが
# Lambdaの250MB上限(非圧縮)を超過するため採用しない（spec_infra.md 1章 R-1）。
# embeddingモデルの重みはビルド時に事前ダウンロードしてイメージへ同梱し、
# 実行時のHugging Faceへのネットワーク依存を排除する（spec_infra.md 2.6章 L-2・E-NEW-1）。
# Python 3.11イメージはAmazon Linux 2ベースでEOL済み（サポート終了2026-06-30）、
# glibcが古く多数のパッケージのプリビルドwheelと非互換のためビルド時に発覚し、
# Python 3.12（Amazon Linux 2023ベース、サポート終了2029-06-30）に変更した
# （spec_infra.md 2.4章、ユーザー確認済み）。
FROM public.ecr.aws/lambda/python:3.12

# requirements.txt はngrok構成・reingestワークフローとの単一ソース(Simplicity First)だが、
# pymupdf(fitz)はPDF取り込み専用（Lambda実行時は使わない。ingest.pyでは遅延importにしてある）で
# Cコンパイラなしではソースビルドに失敗するため、pyngrok(ngrok専用)と合わせてLambdaイメージからは除外する。
# torchはデフォルトのCUDA同梱版だとnvidia系パッケージ込みで4GB超になりLambdaの10GB上限を圧迫するため
# （実装時に発覚。10.1GBでイメージビルドが上限超過した）、CPU専用ビルドを別途明示的にインストールする。
COPY requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN grep -v -E "^(pymupdf|pyngrok|torch)==" ${LAMBDA_TASK_ROOT}/requirements.txt > ${LAMBDA_TASK_ROOT}/requirements-lambda.txt \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.2.2 \
    && pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt

# embeddingモデルの重みをビルド時に事前ダウンロードしてイメージに同梱する
# （config.EMBEDDING_MODEL の既定値。PENDING、config.py参照）
ARG EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

COPY src/ ${LAMBDA_TASK_ROOT}/
COPY templates/ ${LAMBDA_TASK_ROOT}/templates/

CMD ["lambda_handler.handler"]
