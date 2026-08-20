#!/usr/bin/env python3
"""CDKアプリエントリーポイント（spec_infra.md 8.1章・9章）。

CDK_DEFAULT_ACCOUNT/CDK_DEFAULT_REGION（AWS CLIの認証情報から`cdk`コマンドが
自動設定する）を明示的にStackへ渡す。これによりS3バケット名にアカウントIDを
含めて固定でき（main_stack.py参照）、デプロイ前からバケット名が判明する
（GitHub ActionsのCHROMA_S3_BUCKET変数を事前に設定できるようにするため。
ユーザー確認済み）。
"""
import os

import aws_cdk as cdk

from stacks.main_stack import MainStack

app = cdk.App()
MainStack(
    app,
    "FdeRagAwsStack",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION", "ap-northeast-1"),
    ),
)
app.synth()
