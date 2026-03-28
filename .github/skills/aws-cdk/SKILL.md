---
name: aws-cdk
description: AWS CDK（Python）によるインフラ構築・デプロイ（Infrastructure as Code）
---

## 0. 目的

本スキルは、AWS CDK を使用したインフラストラクチャの宣言的定義・デプロイを安全かつ効率的に実行するためのベストプラクティスを定義する。

- **IaC 一元管理**: CDK（Python）でクラウドリソースを定義
- **環境分離**: dev / prod の厳密な分離制御
- **差分デプロイ**: `cdk diff` による安全な段階的デプロイ
- **自動化**: Lambda パッケージング・Layer 管理の自動化

---

## 1. CDK プロジェクト構成

### 5.1 CDK + Lambda 統合戦略

- CDKスタック（Python）でインフラを宣言的に定義
- Lambda関数コードも同じリポジトリで管理
- CDK Deployで自動的にZipパッケージング・デプロイ

### 5.2 プロジェクトディレクトリ構造

```
project_root/
├── cdk/
│   ├── app.py                    # CDKアプリケーション エントリーポイント
│   ├── requirements-cdk.txt      # CDK実行環境用（aws-cdk-lib等）
│   ├── cdk.json                  # CDK設定ファイル
│   └── lib/
│       ├── __init__.py
│       ├── stacks/
│       │   ├── __init__.py
│       │   ├── network_stack.py  # CloudFront + S3 stack
│       │   ├── auth_stack.py     # Cognito stack
│       │   ├── lambda_stack.py   # Lambda + API Gateway stack
│       │   └── database_stack.py # DynamoDB stack
│       └── constructs/
│           ├── __init__.py
│           ├── lambda_layer.py   # Layer定義
│           └── api_gateway.py    # Custom Construct
├── backend/
│   ├── common/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── utils.py
│   ├── functions/
│   │   ├── auth/
│   │   │   └── index.py
│   │   ├── departments/
│   │   │   └── index.py
│   │   └── ai_agent/
│   │       └── index.py
│   └── requirements.txt          # Lambda関数実行用
├── frontend/
│   ├── src/
│   ├── dist/
│   └── package.json
└── .gitignore
```

### 5.3 requirements ファイル分離（重要）

- **requirements-cdk.txt**: CDK開発環境（aws-cdk-lib、constructs等）

  ```
  aws-cdk-lib>=2.80.0
  constructs>=10.0.0
  ```

- **backend/requirements.txt**: Lambda関数実行時（boto3除外）
  ```
  requests>=2.28.0
  pydantic>=2.0.0
  ```

### 5.4 Lambda関数コード例

```python
# backend/functions/auth/index.py
from common.config import get_config

def lambda_handler(event, context):
    config = get_config()
    return {
        "statusCode": 200,
        "body": "{\"message\": \"OK\"}"
    }
```

---

## 6. Layer管理戦略（CDK統合）

### 6.1 CDKによる自動Layer管理

- **Layerに含めるもの**:
  - requirements.txt の標準外ライブラリのみ
  - 例: requests, pydantic, numpy など

- **Layerに含めないもの**:
  - boto3 / botocore（AWS Lambda ランタイムに含む）
  - Python標準ライブラリ

### 6.2 Layer定義（CDK Custom Construct）

```python
# cdk/lib/constructs/lambda_layer.py
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

class CommonLibrariesLayer(Construct):
    def __init__(self, scope: Construct, id: str, env_name: str):
        super().__init__(scope, id)

        self.layer = lambda_.LayerVersion(
            self, f"{env_name}-common-libraries",
            code=lambda_.Code.from_asset("../backend"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
        )

    @property
    def layer_version(self):
        return self.layer
```

### 6.3 Layer更新の自動化

- requirements.txt 変更時、CDK Deployで自動的に新Layer VERSIONを作成
- Lambda関数は自動的に最新Layerを参照

---

## 7. CDK デプロイ必須要件

### 7.1 共通ルール

- `-Environment` パラメータ必須（dev / prod）
- prod環境での自動デプロイ禁止（確認プロンプト必須）
- デプロイ前に差分確認（cdk diff）を実行

### 7.2 CDK初期化と環境構築

```bash
# プロジェクトルートで実行
cd cdk
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements-cdk.txt

# Bootstrap（初回のみ）
cdk bootstrap aws://ACCOUNT_ID/REGION
```

### 7.3 CDK Deploy（dev環境自動実行可）

```bash
# 差分確認
cdk diff --context environment=dev

# デプロイ実行
cdk deploy --context environment=dev --require-approval never
```

### 7.4 CDK Deploy（prod環境：実行禁止、説明のみ）

```bash
# 差分確認のみ
cdk diff --context environment=prod

# コマンド提示（実行しない）
# cdk deploy --context environment=prod
```

### 7.5 フロントエンドデプロイ

CDKスタック内で S3 Deployment を定義（自動化）:

```python
# cdk/lib/stacks/frontend_stack.py
from aws_cdk import (
    aws_s3_deployment as s3deploy,
)

s3deploy.BucketDeployment(
    self, "DeployWebsite\",
    sources=[s3deploy.Source.asset("../frontend/dist")],
    destination_bucket=self.bucket,
    distribution=self.cloudfront_dist,
    distribution_paths=["/*"],
)
```

### 7.6 API Gateway 自動反映

- CDK Deployで自動的に API Gateway をデプロイ
- テンプレート変更 → cdk deploy → 自動反映

### 7.7 Bedrock / モック制御

CDK環境変数で自動制御:

```python
# cdk/lib/stacks/lambda_stack.py
auth_function = lambda_python.PythonFunction(
    self, "AuthFunction",
    environment={
        "USE_MOCK_RAG": "true" if env_name == "dev" else "false",
        "AWS_REGION": self.region,
    },
    # ...
)
```

#### 7.7.1 モック応答デバッグ機能

`USE_MOCK_AI=true`時、Lambda関数のモック応答には実データフローが可視化されたデバッグ情報が含まれる：

**summarizer関数**（\_mock_summary）:

- DynamoDBから取得した現在の要約テキスト
- messageIdで取得したメッセージ内容
- Bedrockプロンプト用テンプレート形式で整形

**ai_support関数**（\_mock_response）:

- 各アクション（summarize/opinion/answer/next_action）の入力データ（要約・メッセージ・ユーザー入力）
- Bedrockに渡すべき全プロンプト要素

**メリット**: 本番Bedrock APIを用いず、DynamoDBｄもLambda処理フローのデータ取得が正しいか検証可能。

---

## 8. 実行前・実行中の思考プロセス

### 8.1 CDK Deploy前宣言

- 対象環境（dev / prod）を明示
- 変更内容の概要を提示（cdk diff の結果）
- prodの場合は実行しないことを明言

### 8.2 実行サマリー

- 作成/更新/削除対象リソースを明示
- 変更の影響範囲を説明

### 8.3 CDK Diff確認手順

```bash
# dev環境の差分確認
cdk diff --context environment=dev

# prod環境の差分確認（デプロイ前必ず実行）
cdk diff --context environment=prod
```

### 8.4 エラー時対応

- CDKエラーメッセージ全文を表示
- CloudFormation スタック詳細情報を提示
- 人間が取るべき次アクション（ロールバック・手動修正等）を提案

---

## 9. システム更新後の必須手順

1. CDKスタック（cdk/lib/stacks/_.py）またはLambda関数（backend/functions/_）を変更
2. 差分確認: `cdk diff --context environment=dev`
3. dev環境へデプロイ: `cdk deploy --context environment=dev --require-approval never`
4. デプロイ完了後、Git対応（commit / branch / PR等）を行う指示を出す
   - ※ Git運用の詳細は **別Skills定義** を参照

---

## 10. CDK 実装テンプレ

### 10.1 app.py（CDKアプリケーション エントリーポイント）

```python
#!/usr/bin/env python3
import aws_cdk as cdk
from lib.stacks.network_stack import NetworkStack
from lib.stacks.auth_stack import AuthStack
from lib.stacks.lambda_stack import LambdaStack
from lib.stacks.database_stack import DatabaseStack

app = cdk.App()

env_name = app.node.try_get_context("environment") or "dev"
project_name = "myapp"

# ネットワーク（CloudFront + S3）
network_stack = NetworkStack(
    app, f"{project_name}-{env_name}-network",
    env_name=env_name,
    project_name=project_name
)

# 認証（Cognito）
auth_stack = AuthStack(
    app, f"{project_name}-{env_name}-auth",
    env_name=env_name,
    project_name=project_name
)

# Lambda + API Gateway
lambda_stack = LambdaStack(
    app, f"{project_name}-{env_name}-lambda",
    env_name=env_name,
    project_name=project_name,
)
lambda_stack.add_dependency(auth_stack)

# データベース（DynamoDB）
database_stack = DatabaseStack(
    app, f"{project_name}-{env_name}-database",
    env_name=env_name,
    project_name=project_name
)

app.synth()
```

### 10.2 lambda_stack.py（Lambda + API Gateway スタック）

```python
# cdk/lib/stacks/lambda_stack.py
from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_lambda_python as lambda_python,
    aws_apigateway as apigw,
    aws_iam as iam,
    Duration,
    RemovalPolicy,
)
from constructs import Construct
import os

class LambdaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        env_name: str,
        project_name: str,
        **kwargs
    ):
        super().__init__(scope, id, **kwargs)

        self.env_name = env_name
        self.project_name = project_name

        # ========== Common Layer ==========
        common_layer = lambda_.LayerVersion(
            self, "CommonLayer",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "../../backend")
            ),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            removal_policy=RemovalPolicy.DESTROY,
            description=f"{project_name}-{env_name}-common-layer"
        )

        # ========== IAM Role for Lambda ==========
        lambda_role = iam.Role(
            self, "LambdaExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ]
        )

        # DynamoDB アクセス権限
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                ],
                resources=[f"arn:aws:dynamodb:{self.region}:{self.account}:table/{project_name}-{env_name}-*"]
            )
        )

        # Bedrock アクセス権限（本番環境のみ）
        if env_name == "prod":
            lambda_role.add_to_policy(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream",
                    ],
                    resources=[f"arn:aws:bedrock:{self.region}::foundation-model/*"]
                )
            )

        # ========== Auth Lambda Function ==========
        auth_function = lambda_python.PythonFunction(
            self, "AuthFunction",
            entry=os.path.join(os.path.dirname(__file__), "../../backend/functions/auth"),
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[common_layer],
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "USE_MOCK_RAG": "true" if env_name == "dev" else "false",
                "AWS_REGION": self.region,
                "ENVIRONMENT": env_name,
            },
            role=lambda_role,
        )

        # ========== Department Lambda Function ==========
        department_function = lambda_python.PythonFunction(
            self, "DepartmentFunction",
            entry=os.path.join(os.path.dirname(__file__), "../../backend/functions/departments"),
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[common_layer],
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "USE_MOCK_RAG": "true" if env_name == "dev" else "false",
                "AWS_REGION": self.region,
                "ENVIRONMENT": env_name,
            },
            role=lambda_role,
        )

        # ========== AI Agent Lambda Function ==========
        ai_agent_function = lambda_python.PythonFunction(
            self, "AiAgentFunction",
            entry=os.path.join(os.path.dirname(__file__), "../../backend/functions/ai_agent"),
            handler="index.lambda_handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[common_layer],
            timeout=Duration.seconds(60),
            memory_size=512,
            environment={
                "USE_MOCK_RAG": "true" if env_name == "dev" else "false",
                "AWS_REGION": self.region,
                "ENVIRONMENT": env_name,
            },
            role=lambda_role,
        )

        # ========== API Gateway ==========
        api = apigw.RestApi(
            self, "API",
            rest_api_name=f"{project_name}-{env_name}-api",
            description=f"Serverless API ({env_name})",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
            ),
        )

        # /auth リソース
        auth_resource = api.root.add_resource("auth")
        auth_resource.add_method(
            "POST",
            apigw.LambdaIntegration(auth_function)
        )

        # /departments リソース
        departments_resource = api.root.add_resource("departments")
        departments_resource.add_method(
            "GET",
            apigw.LambdaIntegration(department_function)
        )
        departments_resource.add_method(
            "POST",
            apigw.LambdaIntegration(department_function)
        )

        # /ai-agent リソース
        ai_agent_resource = api.root.add_resource("ai-agent")
        ai_agent_resource.add_method(
            "POST",
            apigw.LambdaIntegration(ai_agent_function)
        )

        # Output
        self.api_id = api.rest_api_id
```

### 10.3 cdk.json（CDK設定）

```json
{
  "app": "python app.py",
  "context": {
    "environment": "dev"
  }
}
```

---

## 10.4 フロントエンド自動デプロイスタック（frontend_stack.py）

### 目的

- フロントエンド（Next.js）のビルド成果物を自動的にS3へデプロイ
- CloudFrontのキャッシュ自動無効化
- outputs.jsonからフロントエンド設定ファイルへの自動反映

### 実装例

```python
# cdk/lib/stacks/frontend_stack.py
from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    RemovalPolicy,
    CfnOutput,
)
from constructs import Construct
import os

class FrontendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        env_name: str,
        project_name: str,
        appsync_endpoint: str,
        user_pool_id: str,
        user_pool_client_id: str,
        **kwargs
    ):
        super().__init__(scope, id, **kwargs)

        # S3 Bucket for frontend
        frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            bucket_name=f"{project_name}-{env_name}-frontend",
            removal_policy=RemovalPolicy.DESTROY if env_name == "dev" else RemovalPolicy.RETAIN,
            auto_delete_objects=env_name == "dev",
            website_index_document="index.html",
            website_error_document="index.html",
        )

        # CloudFront Distribution
        distribution = cloudfront.Distribution(
            self, "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(frontend_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
        )

        # Auto deployment (if frontend/out exists)
        frontend_out_path = os.path.join(os.path.dirname(__file__), "../../../frontend/out")
        if os.path.exists(frontend_out_path):
            s3deploy.BucketDeployment(
                self, "DeployFrontend",
                sources=[s3deploy.Source.asset(frontend_out_path)],
                destination_bucket=frontend_bucket,
                distribution=distribution,
                distribution_paths=["/*"],
            )

        # Outputs
        CfnOutput(
            self, "FrontendURL",
            value=f"https://{distribution.distribution_domain_name}",
            description="Frontend CloudFront URL"
        )
        CfnOutput(
            self, "FrontendBucketName",
            value=frontend_bucket.bucket_name,
            description="Frontend S3 Bucket Name"
        )
```

### outputs.json 自動反映スクリプト

**scripts/update-frontend-env.ps1**:

```powershell
# CDK outputs.json から .env.local を自動生成
$outputsPath = "cdk/outputs.json"
$envPath = "frontend/.env.local"

if (!(Test-Path $outputsPath)) {
    Write-Error "outputs.json not found. Run 'cdk deploy' first."
    exit 1
}

$outputs = Get-Content $outputsPath | ConvertFrom-Json
$stackName = ($outputs.PSObject.Properties.Name | Where-Object { $_ -like "*appsync*" })[0]

if (!$stackName) {
    Write-Error "AppSync stack not found in outputs.json"
    exit 1
}

$appsyncEndpoint = $outputs.$stackName.AppSyncEndpoint
$userPoolId = $outputs.$stackName.UserPoolId
$userPoolClientId = $outputs.$stackName.UserPoolClientId

$envContent = @"
NEXT_PUBLIC_APPSYNC_ENDPOINT=$appsyncEndpoint
NEXT_PUBLIC_USER_POOL_ID=$userPoolId
NEXT_PUBLIC_USER_POOL_CLIENT_ID=$userPoolClientId
NEXT_PUBLIC_AWS_REGION=ap-northeast-1
"@

Set-Content -Path $envPath -Value $envContent
Write-Host "✅ $envPath updated successfully"
```

### CI/CD統合例（GitHub Actions）

```yaml
# .github/workflows/deploy.yml
name: Deploy to AWS

on:
  push:
    branches: [main, develop]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: 18
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: 3.12

      # CDK Deploy
      - name: CDK Deploy
        run: |
          cd cdk
          pip install -r requirements-cdk.txt
          cdk deploy --all --outputs-file outputs.json --require-approval never

      # Frontend Build & Deploy
      - name: Update Frontend Config
        run: |
          pwsh scripts/update-frontend-env.ps1
      - name: Build Frontend
        run: |
          cd frontend
          npm ci
          npm run build
      - name: Deploy Frontend to S3
        run: |
          aws s3 sync frontend/out s3://$(jq -r '."2dto3d-dev-frontend".FrontendBucketName' cdk/outputs.json)
```

---

## 参考: AWS 運用・コスト最適化

AWS 環境の運用・セキュリティ・コスト最適化に関する詳細は、別スキル定義 **aws-operations/SKILL.md** を参照してください。

- 環境戦略・命名規則
- コスト絶対遵守ルール（Bedrock KB 、ECS Fargate）
- セキュリティ・IAM 最小権限の原則
- モニタリング・アラート戦略

---

## 10. Bedrock Knowledge Base（RAG）デプロイ戦略 - Tokyo リージョン対応

### 最新状態

✅ **東京リージョン（ap-northeast-1）で Knowledge Base のS3 Vectors 構成が対応**

### CloudFormation デプロイフロー

### S3_VECTORS Knowledge Base CDK構築（完全管理）

**✅ CDK/CloudFormationで完全実装可能**

S3 Vectors（VectorBucket + Index）も CDK で管理できます。  
CloudFormation リソース（`AWS::S3Vectors::VectorBucket`, `AWS::S3Vectors::Index`）を L1 Construct 経由で作成。

#### Python CDK 実装例

```python
from aws_cdk import CfnResource, RemovalPolicy

# VectorBucket
vector_bucket = CfnResource(
    self, "VectorBucket",
    type="AWS::S3Vectors::VectorBucket",
    properties={"VectorBucketName": f"{app}-{env}-vectors"}
)
vector_bucket.apply_removal_policy(RemovalPolicy.RETAIN)

# Vector Index
vector_index = CfnResource(
    self, "VectorIndex",
    type="AWS::S3Vectors::Index",
    properties={
        "IndexName": f"{app}-{env}-kb-index",
        "VectorBucketArn": vector_bucket.get_att("VectorBucketArn").to_string(),
        "Dimension": 1024,          # 埋め込みモデルに合わせる
        "DataType": "float32",       # 小文字必須
        "DistanceMetric": "cosine"   # 小文字必須
    }
)
vector_index.apply_removal_policy(RemovalPolicy.RETAIN)
vector_index.add_dependency(vector_bucket)  # 依存関係明示
```

#### IAM権限（最小特権）

```python
iam.PolicyStatement(
    effect=iam.Effect.ALLOW,
    actions=[
        "s3vectors:PutVectors",
        "s3vectors:QueryVectors",
        "s3vectors:GetVectors",      # Knowledge Base 作成時必須
        "s3vectors:GetIndex",
        "s3vectors:GetVectorBucket",
    ],
    resources=["arn:aws:s3vectors:region:account:bucket/*"]
)
```

#### ベストプラクティス

1. **RemovalPolicy.RETAIN 必須** - データ保護
2. **dimension は埋め込みモデルと一致必須**（Titan v2 = 1024）
3. **小文字パラメータ**：`dataType: "float32"`, `distanceMetric: "cosine"`
4. **依存関係明示**：`vector_index.add_dependency(vector_bucket)`
5. **IAM権限**: `GetVectors` も含める（`s3vectors:*` は避ける）

#### エラー対処

- "AlreadyExists" → 既存リソース削除後に再デプロイ
- "unable to assume role" → IAM に `GetVectors` 追加
- "constraint" → パラメータを小文字に修正

**検証結果**: Tokyo（ap-northeast-1）で動作確認済み
