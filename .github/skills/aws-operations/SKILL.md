---
name: aws-operations
description: AWS環境の運用・コスト最適化・セキュリティ規約
---

## 0. 目的

本スキルは、AWS サーバーレスシステムの**運用・セキュリティ・コスト最適化**に関する規約・ベストプラクティスを定義する。

- 環境（dev / prod）の厳密な自律実行境界
- コスト最適化（特に Bedrock / Fargate）
- セキュリティ・IAM最小権限の原則
- モニタリング・アラート戦略

---

## 1. エンジニアとしての役割と倫理規定

あなたは **AWSサーバーレスに精通したシニアDevOps / フルスタックエンジニア** として振る舞う。

### 1.1 自律実行の境界線（絶対遵守）

| 環境 | 許可される行為                                                                   |
| ---- | -------------------------------------------------------------------------------- |
| dev  | CloudFormation deploy / Lambda更新 / API Gateway deploy / テスト実行を自律実行可 |
| prod | 一切の実行禁止。スクリプト生成・実行コマンド提示・影響範囲説明まで               |

---

## 2. システム構成（概要）

- **Frontend**: CloudFront + S3（React / SPA）
- **Backend**: API Gateway + Lambda（Python 3.12）
- **Auth**: Amazon Cognito User Pool
- **Database**: DynamoDB
- **AI Service**: Amazon Bedrock（Claude Sonnet 4.6）
- **Compute**: ECS Fargate（CadQuery など重計算用）
- **Security**: WAF（CloudFront 適用）

---

## 3. 環境戦略・命名規則

### 3.1 環境定義

| 環境 | 用途 | AI モード | Fargate | コスト |
|------|------|----------|---------|--------|
| **dev** | 開発・検証 | モック（デフォルト） | 無効 | 最小 |
| **prod** | 本番運用 | 本番 AI（有料） | 有効 | 最大 |

### 3.2 命名規則（強制）

```
${ProjectName}-${Environment}-${ResourceType}
```

**例**:

```
2dto3d-dev-lambda
2dto3d-dev-network
2dto3d-prod-lambda
2dto3d-prod-network
```

### 3.3 リソース ID（スタック内）

CDK リソース ID も同じ規則に従う:

```python
resource_id = f"{project_name}-{env_name}-{resource_type}"
```

---

## 4. コスト絶対遵守ルール

### 4.1 Bedrock Knowledge Base・API 呼び出し

**原則**:
- dev 環境では原則 **モック AI** を使用
- 本番 AI テスト時のみ本番 API を呼び出す

**Lambda 環境変数による制御**:

```python
# dev環境
USE_MOCK_AI=true   # モック応答使用（無料）
USE_MOCK_RAG=true  # モック RAG 使用（無料）

# prod環境
USE_MOCK_AI=false  # 本番 AI API 呼び出し（有料）
USE_MOCK_RAG=false # 本番 Knowledge Base 連携（有料）
```

### 4.2 ECS Fargate コスト削減

**dev 環境での Fargate 無効化**:

```python
# cdk/lib/stacks/lambda_stack.py
enable_fargate = (env_name == "prod")

if enable_fargate:
    # Fargate タスク定義
    fargate_task = ecs.TaskDefinition(...)
else:
    # Lambda 内で軽量処理のみ実行
    pass
```

**prod では Fargate スケーリング設定**:

```python
# タスク数: 最小 1、最大 3
# CPU: 2048, Memory: 4096
scaling = fargate_service.auto_scale_task_count(
    min_capacity=1,
    max_capacity=3
)
scaling.scale_on_cpu_utilization(...)
```

### 4.3 DynamoDB オンデマンド

テーブル構成時オンデマンド料金モデルを採用:

```python
# cdk/lib/stacks/database_stack.py
table = dynamodb.Table(
    self, "SessionTable",
    billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # オンデマンド
    # ...
)
```

### 4.4 CloudWatch Logs 保存期間

```python
log_group = logs.LogGroup(
    self, "LambdaLogs",
    retention=logs.RetentionDays.ONE_WEEK,  # 7日で削除
    removal_policy=RemovalPolicy.DESTROY,
)
```

---

## 5. セキュリティ・IAM 最小権限

### 5.1 IAM ポリシーの設計

**原則**: 各 Lambda 関数に必要な権限のみ付与

```python
# 例: DynamoDB Read のみ
lambda_role.add_to_policy(
    iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        actions=[
            "dynamodb:GetItem",    # 読み取りのみ
            "dynamodb:Query",      # クエリのみ
        ],
        resources=[table.table_arn]  # 特定テーブルのみ
    )
)
```

### 5.2 Bedrock アクセス権限（prod のみ）

```python
if env_name == "prod":
    lambda_role.add_to_policy(
        iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-*"
            ]
        )
    )
```

### 5.3 S3 アクセス権限

**アップロードバケット**:

```python
# アップロードファイル検証用
s3_role.add_to_policy(
    iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        actions=["s3:GetObject"],
        resources=[f"{upload_bucket.bucket_arn}/uploads/*"]
    )
)
```

**出力バケット**:

```python
# 生成結果の保存
s3_role.add_to_policy(
    iam.PolicyStatement(
        effect=iam.Effect.ALLOW,
        actions=["s3:PutObject"],
        resources=[f"{output_bucket.bucket_arn}/results/*"]
    )
)
```

### 5.4 Cognito 統合

```python
# API Gateway 認可
api.add_cognito_user_pool_auth(
    user_pool=user_pool,
    user_pool_client=user_pool_client
)
```

---

## 6. Lambda AI/モック切り替え（柔軟性）

### 6.1 Context による制御

```bash
# dev環境でモックAI（デフォルト）
cdk deploy --context environment=dev

# dev環境で本番AI（検証時）
cdk deploy --context environment=dev --context useMockAI=false

# prod環境で本番AI
cdk deploy --context environment=prod
```

### 6.2 app.py での取得

```python
env_name = app.node.try_get_context("environment") or "dev"
use_mock_ai = app.node.try_get_context("useMockAI")
if use_mock_ai is None:
    use_mock_ai = (env_name == "dev")  # デフォルト: dev ならモック
```

### 6.3 Lambda 環境変数設定

```python
common_env = {
    "USE_MOCK_AI": "true" if use_mock_ai else "false",
    "ENVIRONMENT": env_name,
    "AWS_REGION": self.region,
}

lambda_function.add_environment_key_value(**common_env)
```

---

## 7. モニタリング・アラート

### 7.1 CloudWatch メトリクス

```python
# Lambda 実行エラー率
lambda_function.metric_errors(
    statistic="Sum",
    period=Duration.minutes(5),
)

# DynamoDB スロットリング
table.metric_consumed_write_capacity_units(
    statistic="Sum",
)
```

### 7.2 CloudWatch アラーム設定

```python
# Lambda エラー数 > 5 (5分間)
error_alarm = cloudwatch.Alarm(
    self, "LambdaErrorAlarm",
    metric=lambda_function.metric_errors(),
    threshold=5,
    evaluation_periods=1,
)

# Bedrock API レート制限アラーム
bedrock_throttle_alarm = cloudwatch.Alarm(
    self, "BedrockThrottleAlarm",
    metric=cloudwatch.Metric(
        namespace="AWS/Bedrock",
        metric_name="ThrottledRequests",
    ),
    threshold=10,
)
```

### 7.3 テンポラルなログ集約

```bash
# CloudWatch Logs Insights クエリ例
fields @timestamp, @message, @duration
| filter @message like /ERROR/
| stats count() by bin(5m)
```

---

## 8. 実行前・実行中の思考プロセス

### 8.1 Deploy 前宣言

- 対象環境（dev / prod）を明示
- 変更内容の概要を提示
- prod の場合は実行しないことを明言

### 8.2 実行サマリー

- 作成・更新・削除対象リソースを明示
- 変更の影響範囲を説明

### 8.3 エラー時対応

- AWS エラーメッセージ全文を表示
- CloudFormation スタック詳細情報を提示
- ロールバック手順を提案

---

## 9. システム更新後の必須手順

1. 変更（CDK / Lambda / 設定）を実施
2. 差分確認（`cdk diff`）
3. dev 環境へデプロイ
4. Git 対応（commit / branch / PR）を実施（詳細は別スキル参照）
