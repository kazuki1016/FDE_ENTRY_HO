"""Secrets Manager → CloudFront KeyValueStore 同期用カスタムリソースLambda。

spec_infra.md 2.1章 C-4。CloudFront FunctionsのBasic認証（infra/cf_auth.js）が参照する
認証情報を、Secrets Manager（一元管理元）からKeyValueStoreへ同期する。cdk deploy時に
CloudFormationのカスタムリソースとして1回だけ呼び出される（main_stack.py参照）。

当初案のCDK `AwsCustomResource`（単発SDK呼び出し）では、KeyValueStoreの`UpdateKeys` APIが
KVS自体のETagによる楽観ロックを要求するため表現できず、
「DescribeKeyValueStoreでETag取得 → UpdateKeys」の2段階呼び出しをこの専用Lambdaで行う。
"""
import base64
import json

import boto3


def handler(event, context):
    request_type = event["RequestType"]
    props = event["ResourceProperties"]
    kvs_arn = props["KvsArn"]
    secret_arn = props["SecretArn"]

    if request_type == "Delete":
        return {"PhysicalResourceId": "kvs-sync"}

    secrets_client = boto3.client("secretsmanager")
    secret_value = json.loads(
        secrets_client.get_secret_value(SecretId=secret_arn)["SecretString"]
    )
    username = secret_value["BASIC_AUTH_USERNAME"]
    password = secret_value["BASIC_AUTH_PASSWORD"]
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

    kvs_client = boto3.client("cloudfront-keyvaluestore")
    etag = kvs_client.describe_key_value_store(KvsARN=kvs_arn)["ETag"]
    kvs_client.update_keys(
        KvsARN=kvs_arn,
        IfMatch=etag,
        Puts=[{"Key": "credentials", "Value": credentials}],
    )
    return {"PhysicalResourceId": "kvs-sync"}
