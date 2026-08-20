#!/usr/bin/env python3
"""CDKアプリエントリーポイント（spec_infra.md 8.1章・9章）。"""
import aws_cdk as cdk

from stacks.main_stack import MainStack

app = cdk.App()
MainStack(app, "FdeRagAwsStack")
app.synth()
