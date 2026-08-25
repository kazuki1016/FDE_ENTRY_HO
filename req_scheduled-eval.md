# GitHub Actionsを用いた定期的なeval実施要件

## 要件概要
- evals/配下の評価をGitHub Actionsで1日1回午前9時（日本時間）に定期的に実行する
- BASIC_AUTH_USERNAME・BASIC_AUTH_PASSWORD・BedrockのAPIキーは新しいIAMロールをOIDC連携で作成してsecretsmanager:GetSecretValueをfde-rag/aws-secretsを付与する
  - BASIC_AUTH_USERNAME・BASIC_AUTH_PASSWORD・BedrockのAPIキーがGitHub Secretsに設定されている場合は削除
- evals/配下の評価結果をSlackに合否にかかわらず送信する様にしたい
