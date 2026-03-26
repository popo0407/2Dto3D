# 振り返り（Retrospective）

## 2025-03 初期実装

### 実施内容
- 要件定義書作成 (docs/requirements.md v1.1.0)
- CDK インフラ全6スタック実装
- バックエンド Lambda ハンドラー9種 + Fargate CadQuery Runner
- フロントエンド React + Three.js スキャフォールド
- pytest + moto テストスイート (33テスト全パス)

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| CDK Stack名が `2dto3d-dev-*` で `^[A-Za-z]` に不適合 | Stack名は先頭がアルファベット必須 | `Cad2d3d-{env}-*` に変更 |
| `method_options` パラメータが存在しない | CDK v2 では `add_method()` に直接 `authorizer=` を渡す | 全12箇所を修正 |
| `payload_path` パラメータが存在しない | CDK v2 の `LambdaInvoke` で廃止済み | パラメータ削除（デフォルトの `$` 使用） |
| `cloudwatch.Duration` が存在しない | `Duration` は `aws_cdk` ルートからインポート | `from aws_cdk import Duration` に修正 |
| `S3Origin` が非推奨 | CloudFront OAI → OAC 移行 | `S3BucketOrigin.with_origin_access_control()` に変更 |
| React 19 + React Three Fiber v8 互換性なし | R3F v8 は `react@>=18 <19` を要求 | React 18.3 にダウングレード |

### 改善策・再発防止
- CDK Stack名は常にアルファベット先頭にする
- CDK API のパラメータは公式ドキュメントと `help()` で確認する
- React Three Fiber のサポートバージョンを確認してからReactバージョンを決定する

---

## 2026-03 デプロイ作業

### 実施内容
- AWS account 590184009554 / ap-northeast-1 へ dev 環境デプロイ
- 全6 CDK スタックのデプロイ成功
- フロントエンドビルド (dist/) → S3 アップロード → CloudFront キャッシュ無効化

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| `libgl1-mesa-glx` がインストール不可 | Debian trixie (`python:3.12-slim` 最新ベース) で `libgl1-mesa-glx` が廃止された | `libgl1` に差し替え（同等のOpenGL共有ライブラリ） |
| `Cad2d3d-dev-lambda/pipeline` で `ExpiredToken` | SSOセッションの一時認証情報が CDK デプロイ途中（database/auth/network 完了後）に有効期限切れ | 認証情報を再取得して残り2スタックのみ再デプロイ |

### デプロイ済みリソース（dev環境）
| リソース | 値 |
|---------|-----|
| CloudFront URL | https://d3azdxpj50obab.cloudfront.net |
| REST API URL | https://ussu5ebma6.execute-api.ap-northeast-1.amazonaws.com/dev/ |
| WebSocket URL | wss://mwrah9ladf.execute-api.ap-northeast-1.amazonaws.com/dev |
| Cognito User Pool | ap-northeast-1_omw6GCY4N |

### 改善策・再発防止
- Debian trixie 以降では `libgl1-mesa-glx` の代わりに `libgl1` を使用する
- 長時間の CDK デプロイ（複数スタック）では SSO トークンの有効期限（通常1〜8時間）に注意し、期限内に完了できるか事前確認する
- 認証情報が切れた場合は `cdk deploy <StackName>` で失敗したスタックのみ再デプロイ可能
