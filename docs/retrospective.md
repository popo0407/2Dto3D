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

---

## 2026-03 バグ修正（実機テスト後）

### 実施内容
- テストユーザーでのE2E通しテストにより3件の実行時バグを発見・修正
- コード総合レビューにより5件の実装欠如（ダミーコード）を修正

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| CloudFront `/api/*` で 403 | `VITE_API_BASE` 未設定時のフォールバックが `/api` で、CloudFront に `/api/*` ビヘイビアなし | `config.ts` に REST API URL をハードコードフォールバックとして設定 |
| S3 署名付きURLへの OPTIONS リクエストで 500 | `boto3.client("s3")` がグローバルエンドポイントを使用し SigV4 未適用 | `region_name`・`signature_version="s3v4"`・`addressing_style="virtual"` を明示 |
| 処理完了後も画面が「処理中」のまま | WebSocket 完了通知フローが未実装 | App.tsx でWebSocket接続 + `PROCESSING_COMPLETE` 受信処理を実装 |
| notify_handler が接続を発見できない | `user_id="anonymous"` で検索していたが WebSocket 接続に `user_id` は格納されていない | `session_id` で接続テーブルをスキャンするように変更 |
| notify_handler のメッセージ型不一致 | Lambda が `"pipeline_complete"` を送信し、フロントが `"PROCESSING_COMPLETE"` を期待 | Lambda 送信型を `"PROCESSING_COMPLETE"` に統一 |
| 処理完了後も 3D ビューアが空白 | `Viewer3D.tsx` が `gltfUrl` プロパティを `_gltfUrl` として受け取り完全に無視していた | `useGLTF` フックを使用した `GltfModel` コンポーネントを実装 |
| WebSocket `$default` ルートが存在しない | CDK で `default_route_options` を指定し忘れていた | `ws_default_fn` Lambda と `$default` ルートを lambda_stack.py に追加 |
| notify_fn に `WEBSOCKET_API_ID` が渡されない | pipeline_stack の `pipeline_lambda()` 呼び出しで `extra_env` を指定し忘れていた | `extra_env={"WEBSOCKET_API_ID": websocket_api.api_id}` を追加 |

### 改善策・再発防止
- WebSocket APIを使う場合は `$connect`・`$disconnect`・`$default` の3ルートすべてを必ず CDK で登録する
- SFn の最終ステップ (Notify) が送受信するメッセージ型・フィールド名はフロントエンドと事前に定義し、コード生成時に一致させる

---

## 2026-03 進捗0%スタック バグ修正

### 実施内容
- WebSocket接続後、進捗が0%から動かない問題を調査・修正

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| Step Functions Step2以降が全て失敗 | `pipeline_stack.py` の `LambdaInvoke` が `result_path="$.xxx_result"` を使用していたため、Lambda戻り値が `{Payload: {...}, StatusCode: 200}` でラップされて格納された。次ステップの `event["node_id"]` がトップレベルに存在せず KeyError で即失敗 | 全 LambdaInvoke に `payload_response_only=True` と `result_path="$"` を設定し、Lambda戻り値が状態全体を上書きするよう修正 |
| 初期PARSING(10%)通知を取りこぼす | `UploadPanel.tsx` が `/process` 呼び出し後にWebSocket接続を開く実装だったため、SQS処理が速い場合にWS接続前に通知が飛びDynamoDBに接続レコードが存在せず通知が捨てられた | `handleProcessingStart` が WebSocket 接続確立後に resolve する `Promise<void>` を返すよう変更し、UploadPanel で await してから `/process` を呼ぶよう修正 |

### 改善策・再発防止
- CDK Step Functions の `LambdaInvoke` は **必ず `payload_response_only=True`** を指定する。デフォルトでは `{Payload, StatusCode, ExecutedVersion}` のラッパーが付くため、次ステップの Lambda が直接フィールドを参照できなくなる
- 非同期処理の通知を受け取るWebSocket接続は、処理起動より**前**に確立・登録しておく（先にWSを開いてから処理をキックする順序を徹底する）
- `boto3.client("s3")` は明示的に `region_name` と `config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"})` を設定する（特に署名付きURL生成時）
- React Three Fiber では `useGLTF` フックを含む `@react-three/drei` コンポーネントは `<Suspense>` の内側に配置する必要がある
- CDK でパイプラインのLambdaに渡す環境変数（APIのIDなど）は、依存スタックのエクスポート値を `extra_env` で明示的に渡し、実装コードではすべて環境変数から読み取る
