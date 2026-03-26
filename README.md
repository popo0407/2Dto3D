# 2D to 3D AI 変換パイプライン

2D図面（DXF/PDF/画像）をAI（Claude Sonnet 4.6）で解析し、CadQuery経由で3Dモデル（STEP/glTF）を自動生成するフルスタックWebアプリケーション。

## アーキテクチャ

```
Frontend (React 18 + Three.js)
  ↓ REST API / WebSocket
API Gateway → Lambda Handlers
  ↓ SQS
Step Functions Pipeline:
  Parse → AI Analyze (Bedrock) → CadQuery (ECS Fargate) → Optimize → Validate → Notify (WebSocket)
  ↓
DynamoDB (Sessions / Nodes / Connections)
S3 (Uploads / Artifacts / Previews / Frontend)
CloudFront CDN
```

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| フロントエンド | React 18, TypeScript, React Three Fiber, Tailwind CSS v4 |
| バックエンド | Python 3.12, AWS Lambda, ECS Fargate |
| AI | Amazon Bedrock (Claude Sonnet 4.6) |
| 3D生成 | CadQuery + OpenCASCADE → STEP → glTF |
| インフラ | AWS CDK (Python), Step Functions, DynamoDB, S3, CloudFront |

## プロジェクト構成

```
├── backend/
│   ├── common/           # 共通モジュール（config, models, bedrock_client, script_validator）
│   ├── functions/        # Lambda ハンドラー & Fargate ランナー
│   │   ├── upload_handler/     # セッション管理・ファイルアップロード
│   │   ├── history_handler/    # セッション・ノード履歴管理
│   │   ├── chat_handler/       # AIチャット（モデル修正指示）
│   │   ├── parse_handler/      # Step 1: ファイル解析
│   │   ├── ai_analyze_handler/ # Step 2: AI分析（Bedrock）
│   │   ├── optimize_handler/   # Step 4: 最適化
│   │   ├── validate_handler/   # Step 5: 検証
│   │   ├── notify_handler/     # Step 6: WebSocket通知
│   │   ├── ws_handler/         # WebSocket接続管理
│   │   └── cadquery_runner/    # Step 3: Fargate CadQuery実行
│   └── tests/            # pytest + moto テストスイート
├── cdk/
│   ├── app.py            # CDKエントリーポイント（6スタック）
│   └── lib/stacks/       # DatabaseStack, AuthStack, NetworkStack, LambdaStack, PipelineStack, MonitoringStack
├── frontend/
│   ├── src/
│   │   ├── App.tsx       # メインアプリ
│   │   └── components/   # Viewer3D, UploadPanel, ChatPanel, HistoryPanel
│   └── package.json
└── docs/
    └── requirements.md   # 要件定義書 v1.1.0
```

## 開発環境セットアップ

```bash
# バックエンド依存関係
pip install -r backend/requirements.txt -r backend/requirements-test.txt

# フロントエンド依存関係
cd frontend && npm install

# テスト実行
cd backend && PYTHONPATH=. pytest tests/ -v

# フロントエンドビルド
cd frontend && npm run build

# CDK synth（デプロイ確認）
cd cdk && cdk synth
```

## CDK デプロイ

```bash
cd cdk

# dev環境デプロイ
cdk deploy --all -c environment=dev -c useMockAI=true

# prod環境デプロイ
cdk deploy --all -c environment=prod -c useMockAI=false -c account=<ACCOUNT_ID> -c region=ap-northeast-1
```

## テスト

```bash
cd backend
PYTHONPATH=. pytest tests/ -v
# 33 tests passed (upload, history, parse, ws, models, script_validator)
```

## デプロイ済みエンドポイント（dev環境）

| リソース | URL |
|---------|-----|
| フロントエンド (CloudFront) | https://d3azdxpj50obab.cloudfront.net |
| REST API (API Gateway) | https://ussu5ebma6.execute-api.ap-northeast-1.amazonaws.com/dev/ |
| WebSocket API | wss://mwrah9ladf.execute-api.ap-northeast-1.amazonaws.com/dev |
| Cognito User Pool ID | ap-northeast-1_omw6GCY4N |
| Cognito Client ID | dp651lflea1qhav7eqpbhlijp |
| SQS Queue | https://sqs.ap-northeast-1.amazonaws.com/590184009554/2dto3d-dev-processing-queue |
| Step Functions | 2dto3d-dev-cad-pipeline |

> AWSアカウント: 590184009554 / リージョン: ap-northeast-1 / 環境: dev (useMockAI=true)