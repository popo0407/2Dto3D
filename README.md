# 2Dto3D

2Dの図面データ（DXF・PDF・スキャン画像）をマルチモーダルAI（Amazon Bedrock / Claude Sonnet 4.6）が設計意図を反映して解釈し、編集可能な3D CADモデル（STEP AP214形式）をブラウザ経由で生成・修正・ダウンロードできる AI-First SaaS システム。

## ドキュメント

| ドキュメント | 概要 |
|---|---|
| [docs/requirements.md](docs/requirements.md) | システム要件定義書（アーキテクチャ・AI設計・UX要件を含む） |

## 技術スタック

| カテゴリ | 技術 |
|---|---|
| フロントエンド | React 19 / TypeScript / React Three Fiber / Tailwind CSS v4 |
| バックエンド | Python 3.12 / FastAPI / CadQuery / PythonOCC |
| AI | Amazon Bedrock（Claude Sonnet 4.6） |
| インフラ | AWS CDK / Lambda / ECS Fargate / Step Functions / DynamoDB / S3 |
| 認証 | Amazon Cognito |

## 開発ステータス

現在、要件定義フェーズ。Bedrock Agent採用是非の協議中（[docs/requirements.md §8.3](docs/requirements.md) 参照）。