# ECS コンテナデプロイ戦略：Docker 不要な方式への転換

**バージョン:** 1.0.0  
**作成日:** 2026-03-31  
**対象:** AWS CDK + ECS Fargate パイプライン  
**効果:** ローカル Docker インストール不要 → どの環境からでも `cdk deploy` 実行可能

---

## 目次

1. [概要](#概要)
2. [従来方式の問題点](#従来方式の問題点)
3. [新方式：CodeBuild + ECR 参照](#新方式codebuild--ecr-参照)
4. [変更手順](#変更手順)
5. [IAM 権限設定](#iam-権限設定)
6. [トラブルシューティング](#トラブルシューティング)
7. [まとめ・改善策](#まとめ改善策)

---

## 概要

### 背景

ECS Fargate（CadQuery コンテナ）を使用するパイプラインで、`cdk deploy` 実行時に以下の問題が発生していました：

- ❌ ローカル Docker インストールが必須
- ❌ Docker 未インストール環境では `Failed to find and execute 'docker'` エラーで失敗
- ❌ Windows 環境では Docker Desktop インストール時の交渉・リソース確保が困難
- ❌ `runner.py` の `__import__` 修正を含む新コンテナイメージが結果としてデプロイできず

### 解決策

**CDK の `ContainerImage.from_asset()` を `ContainerImage.from_registry()` に変更し、コンテナイメージのビルドを AWS CodeBuild に委譲する。**

**メリット：**
- ✅ ローカル Docker 不要 → どの環境からでも `cdk deploy` 実行可能
- ✅ コンテナイメージのライフサイクルが明示的（CodeBuild で管理）
- ✅ CI/CD パイプライン統合が容易
- ✅ 複数環境（dev / prod）での イメージ管理が一元化可能

---

## 従来方式の問題点

### from_asset() の仕組みと制限

#### `from_asset()` が実行すること

```python
# cdk/lib/stacks/pipeline_stack.py（現在）
image=ecs.ContainerImage.from_asset("../backend/functions/cadquery_runner"),
```

CDK が `cdk deploy` 実行時に以下を**自動的に**実行する：

1. **ローカルで `docker build` を実行**
   - `../backend/functions/cadquery_runner/Dockerfile` をビルド
   - 結果として新イメージ ID を生成

2. **生成したイメージを ECR にプッシュ**
   - 自動的に ECR リポジトリを作成・管理
   - タグ付けして push

3. **CloudFormation に新イメージ URI を記録**
   - ECS タスク定義で自動参照

#### 問題：Docker が環境に存在しなければ失敗

```bash
# Windows + Docker なし環境で実行
$ cdk deploy --context environment=dev

❌ Failed to find and execute 'docker' 
cdk cannot continue without docker.
```

### 実際の影響

| 課題 | 結果 |
|------|------|
| Docker インストール環境の構築 | リソース・権限の都合で不可 |
| GitHub Actions で `cdk deploy` | SSO 一時認証情報使用不可で失敗 |
| `runner.py` の修正（`__import__` 追加） | コンテナイメージ未更新のため反映されない |

---

## 新方式：CodeBuild + ECR 参照

### アーキテクチャ図

```
┌──────────────────────────────────────────────────────────────┐
│ このステップは AWS コンソール（ブラウザ）で実施             │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ 1. CodeBuild Project 作成                                   │
│    ├─ Source: このリポジトリ                                │
│    ├─ Environment: Ubuntu Standard + Privileged             │
│    └─ buildspec.yml: docker build & ECR push              │
│                                                              │
│ 2. CodeBuild 実行                                           │
│    ├─ backend/functions/cadquery_runner/Dockerfile ビルド  │
│    └─ 結果を ECR にプッシュ                                 │
│       (590184009554.dkr.ecr.ap-northeast-1.amazonaws.com... │
│        /2dto3d-dev-cadquery:latest)                        │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ このステップはローカルで実施（Docker 不要）              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ 3. pipeline_stack.py を更新                                 │
│    from_registry("590184009554.dkr.ecr.ap-northeast-1...") │
│                                                              │
│ 4. cdk deploy 実行                                         │
│    ✅ Docker なしで成功                                    │
│    ✅ ECS はすでに ECR に存在するイメージを参照する        │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### メリット

| 項目 | 従来方式 | 新方式 |
|------|---------|--------|
| Docker 環境 | ✅ 必須 | ❌ 不要 |
| ローカル `cdk deploy` | ❌ 失敗（if Docker なし） | ✅ 成功 |
| イメージ管理の可視性 | △ CDK により自動生成 | ✅ CodeBuild で明示的に管理 |
| CI/CD 統合 | △ GitHub Actions では使えない | ✅ ECR へのプッシュが中心 |
| 複数環境管理 | △ ビルド毎回実施 | ✅ ECR で tag（:dev, :latest）管理 |

---

## 変更手順

### Step 1：ECR リポジトリ確認（AWS コンソール）

ECR（Elastic Container Registry）にリポジトリが存在するか確認します。

#### 確認方法：AWS CLI

```bash
aws ecr describe-repositories \
  --region ap-northeast-1 \
  --repository-names 2dto3d-dev-cadquery
```

**出力例（リポジトリ存在）:**
```json
{
  "repositories": [
    {
      "repositoryArn": "arn:aws:ecr:ap-northeast-1:590184009554:repository/2dto3d-dev-cadquery",
      "repositoryUri": "590184009554.dkr.ecr.ap-northeast-1.amazonaws.com/2dto3d-dev-cadquery",
      "repositoryName": "2dto3d-dev-cadquery"
    }
  ]
}
```

#### リポジトリが存在しない場合：作成

```bash
aws ecr create-repository \
  --repository-name 2dto3d-dev-cadquery \
  --region ap-northeast-1
```

### Step 2：CodeBuild プロジェクト作成（AWS コンソール）

CodeBuild で「リポジトリをビルド → ECR に push」するプロジェクトを作成します。

#### 基本設定

| 項目 | 値 |
|------|-----|
| **Project name** | `2dto3d-dev-cadquery-build` |
| **Source** | GitHub (このリポジトリ) |
| **Source version** | `develop` (または main) |
| **Primary source webhook events** | (Optional) `PUSH` イベントで自動実行したい場合は Yes |

#### Environment 設定

| 項目 | 値 |
|------|-----|
| **OS** | Ubuntu |
| **Runtime** | Standard |
| **Image** | `aws/codebuild/standard:7.0` |
| **Image version** | Always use the latest image for this runtime version |
| **Privileged** | ✅ **チェック必須**（Docker ビルドのため） |
| **Service role** | 新規作成 / 既存選択（IAM 権限後述） |

#### Buildspec 設定

```yaml
version: 0.2

phases:
  pre_build:
    commands:
      - echo "Logging in to Amazon ECR..."
      - aws ecr get-login-password --region ap-northeast-1 | docker login --username AWS --password-stdin 590184009554.dkr.ecr.ap-northeast-1.amazonaws.com
      - REPOSITORY_URI=590184009554.dkr.ecr.ap-northeast-1.amazonaws.com/2dto3d-dev-cadquery
      - COMMIT_HASH=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c 1-7)
      - IMAGE_TAG=${COMMIT_HASH:=latest}

  build:
    commands:
      - echo "Building the Docker image on $(date)"
      - docker build -t $REPOSITORY_URI:$IMAGE_TAG backend/functions/cadquery_runner/
      - docker tag $REPOSITORY_URI:$IMAGE_TAG $REPOSITORY_URI:latest

  post_build:
    commands:
      - echo "Pushing the Docker images on $(date)"
      - docker push $REPOSITORY_URI:$IMAGE_TAG
      - docker push $REPOSITORY_URI:latest
      - echo "Writing image definitions file..."
      - printf '[{"name":"cadquery-runner","imageUri":"%s"}]' $REPOSITORY_URI:$IMAGE_TAG > imagedefinitions.json

artifacts:
  files: imagedefinitions.json
```

#### ビルド実行

CodeBuild コンソールで「Start build」をクリック → ビルド完了を待機 → ECR にイメージが push されたことを確認

**確認コマンド:**
```bash
aws ecr describe-images \
  --repository-name 2dto3d-dev-cadquery \
  --region ap-northeast-1
```

### Step 3：pipeline_stack.py を変更（ローカル）

[cdk/lib/stacks/pipeline_stack.py](../cdk/lib/stacks/pipeline_stack.py) の **Line 207** を以下のように変更します。

**変更前:**
```python
image=ecs.ContainerImage.from_asset("../backend/functions/cadquery_runner"),
```

**変更後:**
```python
image=ecs.ContainerImage.from_registry(
    "590184009554.dkr.ecr.ap-northeast-1.amazonaws.com/2dto3d-dev-cadquery:latest"
),
```

**補足：** `from_registry()` は ECR URI をそのまま参照するだけで、ビルドは実行しません。

### Step 4：cdk deploy 実行（ローカル）

Docker 不要で`cdk deploy` を実行できます：

```bash
cd cdk

# 差分確認
cdk diff --context environment=dev

# デプロイ実行
cdk deploy Cad2d3d-dev-pipeline --context environment=dev --require-approval never
```

**期待される結果:**
- ✅ `docker` コマンドが実行されない
- ✅ ECS タスク定義が ECR イメージを参照するように更新される
- ✅ パイプライン再デプロイ後、新しいコンテナイメージ（`__import__` 修正版）が使用される

---

## IAM 権限設定

### CodeBuild サービスロール権限

CodeBuild が以下を実行するために必要な権限：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "arn:aws:ecr:ap-northeast-1:590184009554:repository/2dto3d-dev-cadquery"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:ap-northeast-1:590184009554:log-group:/aws/codebuild/*"
    }
  ]
}
```

### AWS CDK スタック内での権限付与（参考）

CDK で CodeBuild ロールを定義する場合：

```python
from aws_cdk import aws_iam as iam

codebuild_role = iam.Role(
    self, "CodeBuildRole",
    assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com")
)

# ECR push 権限
codebuild_role.add_to_policy(iam.PolicyStatement(
    effect=iam.Effect.ALLOW,
    actions=[
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
    ],
    resources=[
        f"arn:aws:ecr:{self.region}:{self.account}:repository/2dto3d-dev-cadquery"
    ]
))

# CloudWatch Logs 権限
codebuild_role.add_to_policy(iam.PolicyStatement(
    effect=iam.Effect.ALLOW,
    actions=[
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
    ],
    resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/codebuild/*"]
))
```

---

## トラブルシューティング

### 問題1：CodeBuild ビルド失敗 → "credentials not found"

**原因:** CodeBuild ロールに ECR push 権限がない

**対処:**
```bash
# IAM ロードを確認
aws iam get-role --role-name <CodeBuildServiceRole>
aws iam list-attached-role-policies --role-name <CodeBuildServiceRole>

# ポリシーが不足している場合、上の「IAM権限設定」セクションを参照して追加
```

### 問題2：cdk deploy 時 "ImageUri is not a valid ECR reference"

**原因:** `from_registry()` に渡した ECR URI が不正

**対処:**
- リージョン・アカウント ID・リポジトリ名を再確認
- 形式: `<account-id>.dkr.ecr.<region>.amazonaws.com/<repository-name>:<tag>`

```bash
# 正しい URI を確認
aws ecr describe-repositories \
  --repository-names 2dto3d-dev-cadquery \
  --region ap-northeast-1 \
  --query 'repositories[0].repositoryUri'
```

### 問題3：ECS タスク起動失敗 → "CannotPullContainerImage"

**原因:**
- ECR イメージが存在しない（CodeBuild ビルドが実行されていない）
- ECS タスクロールに ECR read 権限がない

**対処:**

```bash
# ECR にイメージが push されているか確認
aws ecr describe-images \
  --repository-name 2dto3d-dev-cadquery \
  --region ap-northeast-1

# ECS タスクロールに ECR read 権限があるか確認
aws iam get-role --role-name <EcsTaskExecutionRole>
```

### 問題4：GitHub Actions 環境で codecommit / CodeBuild トリガーしたい

**推奨:** GitHub secrets に AWS Access Key を保存し、AWS CLI で CodeBuild をトリガー：

```yaml
# .github/workflows/build.yml
name: Build CadQuery Container

on:
  push:
    paths:
      - backend/functions/cadquery_runner/**

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ap-northeast-1

      - name: Start CodeBuild
        run: |
          aws codebuild start-build \
            --project-name 2dto3d-dev-cadquery-build \
            --region ap-northeast-1
```

---

## まとめ・改善策

### 今回の変更が解決したこと

| 課題 | 解決 |
|------|------|
| ローカル Docker インストール不要 | ✅ CodeBuild がビルドを担当 |
| Docker なし環境から `cdk deploy` 実行可能 | ✅ ECR 参照のみで OK |
| `runner.py` 修正のデプロイ | ✅ 新イメージが ECR に push → ECS 参照 |
| 複数環境でのイメージ管理 | ✅ ECR tag でバージョン分離可能（:dev, :latest） |

### 今後の改善策（推奨）

1. **CodeBuild のトリガー自動化**
   - GitHub Actions から CodeBuild をトリガーし、`backend/functions/cadquery_runner/` の変更を検知したら自動ビルド

2. **マルチステージ Dockerfile 最適化**
   - ビルドステージ（dependencies）とランタイムステージを分離して、イメージサイズ削減

3. **イメージレジストリのスキャン**
   - CodeBuild の post_build で `aws ecr start-image-scan` を実行、脆弱性チェック

4. **dev / prod 環境の tag 分離**
   - CodeBuild で `git branch` を検知し、develop → `:dev`, main → `:latest` など tag を分別

5. **AWS CDK で CodeBuild プロジェクトも定義**
   - 現在は手動で CoedBuild を作成していますが、CDK スタック内で完全定義すればコード化可能

### セキュリティ考慮

- CodeBuild ロールは **最小限の権限**を付与（特定リポジトリへの push のみ）
- ECR プライベートリポジトリを使用（本番環境）
- CodeBuild ビルドログは CloudWatch Logs に記録・監査可能
- GitHub Secrets は一時的だが、OIDC 認証（SSO 環境では推奨）を検討

---

## 参考

- [AWS CDK - ContainerImage (from_registry)](https://docs.aws.amazon.com/cdk/api/latest/python/aws_ecs/ContainerImage.html)
- [AWS CodeBuild - Getting started](https://docs.aws.amazon.com/codebuild/latest/userguide/getting-started.html)
- [Amazon ECR - Private registry](https://docs.aws.amazon.com/AmazonECR/latest/userguide/Registries.html)
- [.github/skills/aws-cdk/SKILL.md](../.github/skills/aws-cdk/SKILL.md) - CDK デプロイ戦略
