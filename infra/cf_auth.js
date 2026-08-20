// CloudFront Functions によるBasic認証（spec_infra.md 4.1章）。
// KeyValueStore の "credentials" キーに base64("username:password") を格納しておき、
// Authorization ヘッダーと比較する。値はSecrets Managerを一元管理元とし、
// デプロイ時にCDKカスタムリソースが同期する（main_stack.py参照）。
import cf from "cloudfront";

const kvsHandle = cf.kvs();

async function handler(event) {
    var request = event.request;
    var headers = request.headers;
    var authHeader = headers.authorization ? headers.authorization.value : null;

    var expectedCredentials;
    try {
        expectedCredentials = await kvsHandle.get("credentials");
    } catch (err) {
        return {
            statusCode: 500,
            statusDescription: "Internal Server Error"
        };
    }

    var expected = "Basic " + expectedCredentials;
    if (!authHeader || authHeader !== expected) {
        return {
            statusCode: 401,
            statusDescription: "Unauthorized",
            headers: {
                "www-authenticate": { value: 'Basic realm="FDE RAG System"' }
            }
        };
    }

    return request;
}
