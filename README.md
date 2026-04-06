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

## 主な機能

- 2D図面（DXF/PDF/画像）のアップロードと3Dモデル自動生成
- AI寸法検証パネル（中間プレビュー + 反復検証）
- 要素リストクリックで3Dプレビュー上のハイライト連携
- 要素ダブルクリックでコメント欄に要素名を自動挿入
- AIコメント送信履歴の表示
- 最終3Dモデル生成中のリアルタイム進捗表示
- AIチャットによるモデル修正指示
- STEPファイルダウンロード
- **段階的構築モード（BuildPlan）**: AI がステップバイステップの構築計画を生成。各ステップのパラメータ編集・NL チャット修正に対応。複数ステップを選択して**一括修正**（パラメータ・自然言語・混在）が可能
- **ブラウザ内累積 CSG プレビュー**: 未実行ステップを選択した際、そのステップまでの全操作（穴・ポケット・スロット等）をブラウザ内 CSG（`three-bvh-csg`）でリアルタイム合成して即時 3D 表示

## 開発環境セットアップ

### 🚀 フルデプロイメント（推奨）

本プロジェクトは、バックエンド・フロントエンド・インフラストラクチャの完全自動デプロイをサポートしています。

**PowerShell（Windows）**:
```powershell
.\scripts\deploy.ps1 -Environment dev -Action deploy
```

**Python（クロスプラットフォーム）**:
```bash
python scripts/deploy.py --environment dev --action deploy
```

### 📋 スクリプトの実行内容

スクリプトは以下の処理を自動実行します：

1. ✓ 前提条件チェック（Python 3.12, Node.js, AWS CLI）
2. ✓ バックエンド環境構築（venv + 依存関係インストール）
3. ✓ バックエンドテスト実行（pytest）
4. ✓ フロントエンド構築（npm install + build）
5. ✓ CDK初期化（venv + aws-cdk-lib インストール）
6. ✓ CDK差分確認（cdk diff）
7. ✓ CDK デプロイ実行（cdk deploy）

### 個別実行

```bash
# バックエンド・フロントエンド環境構築のみ
python scripts/deploy.py --action setup

# テスト実行のみ
python scripts/deploy.py --action test

# CDK Synth確認のみ
python scripts/deploy.py --action synth

# スタック削除
python scripts/deploy.py --action destroy --environment dev
```

詳細は [.github/copilot-instructions.md](file://.github/copilot-instructions.md#L30) を参照。

---

## 開発ステータス

3Dモデル生成パイプライン稼働中。穴方向AI推論・面/Feature選択・チャット編集・再帰的寸法検証が利用可能。段階的構築モード（BuildPlan）を追加。

## アーキテクチャ

```
Frontend (React 18 + Three.js)
  ↓ REST API / WebSocket
API Gateway → Lambda Handlers
  ↓ SQS
Step Functions Pipeline (Auto mode):
  Parse → AI Analyze (Bedrock) → Extract Dimensions → [Verify Loop] → Final Assembly → CadQuery (ECS Fargate) → Optimize → Validate → Notify (WebSocket)

BuildPlan mode (Interactive):
  Create Plan (Bedrock) → Step List UI → [Modify Step ↔ AI Replan] → Execute → Checkpoint Previews → Final Output
  ↓
DynamoDB (Sessions / Nodes / Connections / DrawingElements / BuildPlans / BuildSteps)
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
│   │   ├── upload_handler/          # セッション管理・ファイルアップロード
│   │   ├── history_handler/         # セッション・ノード履歴管理
│   │   ├── chat_handler/            # AIチャット（モデル修正指示）
│   │   ├── parse_handler/           # Step 1: ファイル解析（DXF寸法抽出: ezdxf）
│   │   ├── ai_analyze_handler/      # Step 2: AI分析（Bedrock）
│   │   ├── dimension_extract_handler/ # Step 3: 寸法要素抽出・確度スコアリング
│   │   ├── dimension_verify_handler/  # Step 4: 再帰的寸法検証（確度閾値0.85）
│   │   ├── optimize_handler/        # Step 6: 最適化
│   │   ├── validate_handler/        # Step 7: 検証
│   │   ├── notify_handler/          # Step 8: WebSocket通知
│   │   ├── ws_handler/              # WebSocket接続管理 + verifyComment
│   │   ├── buildplan_create_handler/ # BuildPlan生成（AI構築計画）
│   │   ├── buildplan_step_handler/  # BuildPlanステップCRUD・修正・実行
│   │   └── cadquery_runner/         # Step 5: Fargate CadQuery実行
│   └── tests/            # pytest + moto テストスイート
├── cdk/
│   ├── app.py            # CDKエントリーポイント（6スタック）
│   └── lib/stacks/       # DatabaseStack, AuthStack, NetworkStack, LambdaStack, PipelineStack, MonitoringStack
├── frontend/
│   ├── src/
│   │   ├── App.tsx       # メインアプリ
│   │   └── components/   # Viewer3D, UploadPanel, ChatPanel, HistoryPanel, VerificationPanel, LoginPanel, BuildPlanPanel
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
# 34 tests passed (upload, history, parse, ws, models, script_validator)
# + 7 tests for dimension_extract/verify handlers
# parse_handler includes DXF DIMENSION extraction tests (ezdxf)
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

## 修正履歴

| 日付 | 修正内容 |
|------|---------|
| 2026-03 | CloudFront /api 403 → `config.ts` API URL ハードコードフォールバック |
| 2026-03 | S3 CORS OPTIONS 500 → `upload_handler` SigV4 + リージョン指定 |
| 2026-03 | 処理完了通知未着 → App.tsx WebSocket 接続 + `PROCESSING_COMPLETE` ハンドリング |
| 2026-03 | `ws_handler` セッション未紐付け → `session_id` 保存 + `default_handler` 追加 |
| 2026-03 | `notify_handler` メッセージ型不一致・`gltf_url` 欠如 → `PROCESSING_COMPLETE` + 署名付き URL |
| 2026-03 | WebSocket `$default` ルート欠如 → `ws_default_fn` Lambda + CDK ルート登録 |
| 2026-03 | `notify_fn` に `WEBSOCKET_API_ID` 未渡し → `pipeline_stack` の `extra_env` に追加 |
| 2026-03 | `Viewer3D.tsx` が glTF を描画しない → `useGLTF` による実 glTF ロード実装 |
| 2026-03 | glTF 読み込み「Failed to fetch」CORS エラー → previews_bucket に CORS (GET) 設定追加 |
| 2026-03 | `Stage environment="city"` による外部 HDR 301 リダイレクト → シンプルなライティング（ambientLight + directionalLight）に置換 |
| 2026-03 | `parse_handler` DXF解析を ezdxf に置換、DIMENSION エンティティを drawing_elements テーブルに保存 |
