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
