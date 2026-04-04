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

---

## 2026-03 スキル分割・デプロイScripting

### 実施内容
- **AWS スキルの分割**: `aws-ops` → `aws/SKILL.md` (CDK関連) + `aws-operations/SKILL.md` (運用関連)
  - `aws/SKILL.md`: AWS CDK（Infrastructure as Code）・Lambda・Layer管理
  - `aws-operations/SKILL.md`: 環境戦略・命名規則・コスト最適化・セキュリティ・IAM・モニタリング
- **デプロイスクリプト実装**: フルデプロイメント自動化
  - `scripts/deploy.ps1`: PowerShell版（Windows推奨）
  - `scripts/deploy.py`: Python版（クロスプラットフォーム）
  - 実行内容: 環境確認 → バックエンド構築・テスト → フロントエンド構築 → CDK初期化・Synth・Diff → デプロイ
- **ドキュメント更新**:
  - `.github/copilot-instructions.md`: スキル分割の反映、デプロイスクリプト説明追加
  - `README.md`: デプロイスクリプト実行方法を追加

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| AWS スキルが CDK・運用・セキュリティを混在 | スキル数が多すぎてユースケースが不明確 | ドメインで明確に分割（CDK機能vs運用ガバナンス） |

### 改善策・再発防止
- スキル数が多い場合は「機能別」「責務別」で明確に分割する
- スキルは実装時に参照しやすい粒度（3-5ページ程度）を目指す
- デプロイ自動化によって运用効率が大幅向上（dev環境は秒単位）

### 改善策・再発防止
- Debian trixie 以降では `libgl1-mesa-glx` の代わりに `libgl1` を使用する

---

## 2026-03 GLTFロード CORS エラー修正

### 発生した問題
3Dビューアでプレビュー GLTF ファイルのロードが失敗し、`THREE.WebGLRenderer: Context Lost.` が発生。

### 根本原因

| 問題 | 原因 |
|------|------|
| `Error: Could not load ... preview.gltf: Failed to fetch` | `previews_bucket` に CORS 設定がなく、`Origin: https://d3azdxpj50obab.cloudfront.net` からのクロスオリジン GET リクエストがブラウザにブロックされた |
| HDR ファイル 301 リダイレクト | `Stage environment="city"` が `raw.githack.com/pmndrs/drei-assets/...` から外部 HDR を取得していた。外部 CDN への依存と 301 リダイレクトが問題 |

### 対処

| 対処 | ファイル |
|------|----------|
| `previews_bucket` に `GET` メソッドの CORS ルールを追加 | `cdk/lib/stacks/network_stack.py` |
| `Stage environment="city"` を除去し、`ambientLight` + `directionalLight` による組み込みライティングに置換（外部 HDR 取得を廃止） | `frontend/src/components/Viewer3D.tsx` |

### 再発防止
- クロスオリジンで読み込む S3 バケット（previews等）は必ず `cors` ルールを設定する
- `@react-three/drei` の `Stage` / `Environment` は外部 CDN へのフェッチが発生する。外部依存は避け、組み込みライティングか自己ホスト HDR を使用する
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

---

## 2026-04-01 CadQueryStep ExitCode 1 バグ修正

### 発生した問題
Step Functions の `CadQueryStep` で ECS Fargate タスクが ExitCode 1 で終了。

### 根本原因

| 問題 | 原因 |
|------|------|
| `NameError: name 'Exception' is not defined` | `runner.py` の `execute_cadquery` が `exec()` に渡す制限 namespace に `Exception` など例外クラスが含まれていなかった。AIが生成した CadQuery スクリプトが `try-except Exception:` で OCC エラーをキャッチしようとして `NameError` で落ちた |
| `StdFail_NotDone: BRep_API: command not done` | chamfer 操作で OpenCASCADE が形状処理を完了できなかった（スクリプト側のエラー）。上記 `NameError` によって except ブロックが動作しなかったため、エラーがそのまま上位に伝搬した |

### 対処
`runner.py` の `execute_cadquery` namespace `__builtins__` に以下の例外クラスを追加：
`Exception`, `BaseException`, `ValueError`, `TypeError`, `RuntimeError`, `IndexError`, `KeyError`, `AttributeError`, `NotImplementedError`, `StopIteration`, `OverflowError`

### 再発防止
- `exec()` に渡す制限 namespace を構築する際は、スクリプトが使用する可能性のある組み込みを網羅する。特に `try-except` ブロックに必要な例外クラスを忘れずに含める
- 新しい組み込みが必要になった場合は namespace を拡張し、セキュリティ上問題ないか確認する（`os`, `subprocess` 等の危険モジュールは引き続き除外）

---

## 2026-03 DynamoDB float 型エラー修正

### 実施内容
- Step2 (ai_analyze_handler) が正常にBedrockを呼び出してCadQueryスクリプト生成に成功した後、DynamoDBへの書き込みで TypeError に遭遇
- 原因調査・修正・Lambda関数更新

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| `TypeError: Float types are not supported. Use Decimal types instead.` | `ai_analyze_handler` が `confidence_map` (例: `0.95`、`0.80`) と `questions` 内の `confidence` フィールド (例: `0.45`) を `float` のまま DynamoDB に `put_item`/`update_item` していた。DynamoDB は float 非対応で、Decimal型への変換が必須 | `_to_decimal()` ヘルパー関数を追加し、DynamoDB書き込み前にすべてのfloat値を `Decimal(str(value))` に変換。`confidence_map` と `questions` に対して関数を適用 |

### 修正の詳細
```python
from decimal import Decimal

def _to_decimal(obj):
    """再帰的に float → Decimal に変換（DynamoDB非対応のため）"""
    if isinstance(obj, float):
        return Decimal(str(obj))  # float str化後 Decimal化（精度損失防止）
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj

# DynamoDB update_item 呼び出し時に使用
nodes_table.update_item(
    Key={"node_id": node_id},
    UpdateExpression="SET cadquery_script = :script, confidence_map = :conf, ai_questions = :q",
    ExpressionAttributeValues={
        ":script": cadquery_script,
        ":conf": _to_decimal(confidence_map),     # float → Decimal変換
        ":q": _to_decimal(questions),              # float → Decimal変換
    },
)
```

### 改善策・再発防止
- **DynamoDB はnative型として float をサポートしない**ため、Python boto3 で数値を格納する際は常に `Decimal` 型を使用する
- AI/機械学習処理で確度スコア (0.0～1.0) を扱う場合は、**JSON解析直後に再帰的にDecimal変換する** ジェネリック処理を用意しておく
- DynamoDB アイテム更新時は ExpressionAttributeValues の値についても型チェックを習慣付ける

---

## 2026-03 進捗0%スタック バグ修正（第2弾）

### 実施内容
- CDKデプロイ後も0%のまま進まない問題を継続調査・修正

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| dev環境でも進捗0%が続く | `pipeline_stack.py` に `enableFargate` 分岐がなく、dev環境でも常にECS Fargate（CadQuery Docker コンテナ）が実行されていた。コンテナ起動・実行失敗でパイプラインがサイレントにクラッシュし、notifyハンドラーまで到達しないため進捗通知ゼロ | `enable_fargate: bool` パラメータを `PipelineStack` に追加。`enable_fargate=False`（dev）の場合はDockerビルド不要の `mock_cadquery` Lambdaを使用するよう分岐 |
| パイプラインエラーがフロントエンドに届かない | Step Functions エラー時に全てサイレントで終了し、WebSocket経由での通知が一切なかった | `pipeline_error_handler` Lambdaを新規作成し、全ステップに `add_catch(errors=["States.ALL"])` を設定。エラー時はセッションをFAILEDに更新してフロントにPROCESSING_FAILEDを送信 |
| cdk.json に enableFargate の記載がなかった | 要件定義には記載があったが実装に反映されていなかった | `cdk.json` に `"enableFargate": false` を追加 |

### 改善策・再発防止
- CDK の `from_context` フラグは **必ず `cdk.json` に明示的に記載**する。requirements.md にあっても実装に反映されないと意味がない
- Step Functions のステートマシンには必ず **エラーキャッチ+WebSocket通知** を設ける。サイレント失敗はデバッグが極めて困難
- dev環境で重量コンテナ（ECS Fargate + CadQuery）を使うと毎回数分かかりコスト高・デバッグ困難。`enableFargate=false` でモックLambdaを使うパターンを標準化する
- `boto3.client("s3")` は明示的に `region_name` と `config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"})` を設定する（特に署名付きURL生成時）
- React Three Fiber では `useGLTF` フックを含む `@react-three/drei` コンポーネントは `<Suspense>` の内側に配置する必要がある
- CDK でパイプラインのLambdaに渡す環境変数（APIのIDなど）は、依存スタックのエクスポート値を `extra_env` で明示的に渡し、実装コードではすべて環境変数から読み取る

---

## 2026-03 Runtime.ImportModuleError 修正

### 実施内容
- パイプライン処理の全Lambda関数で `Runtime.ImportModuleError: No module named 'common'` が発生
- Lambda Layer の構造が誤っており修正した

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| 全Lambda関数で `No module named 'common'` | `lambda_stack.py`・`pipeline_stack.py` の CommonLayer が `Code.from_asset("../backend", exclude=[...])` でパッケージされており、zip内のモジュールが `common/` のルート直下に配置されていた。PythonのLambda Layerは `/opt/python/` 以下にモジュールを配置する必要があるため、`python/` サブディレクトリがなければランタイムが見つけられない | `cdk/lib/constructs/python_layer.py` に `prepare_common_layer_dir()` を作成。CDK synthesisの前に `backend/.layer_build/python/common/` を動的生成し、そのディレクトリを `Code.from_asset` のソースとして使用 |

### 改善策・再発防止
- Python Lambda Layer の zip 構造は **`python/<module_name>/`** でなければならない。`Code.from_asset` でソースディレクトリを直接指定すると `python/` プレフィックスが付かないため、必ず中間ディレクトリを用意するか bundling を使うこと
- CDK の `BundlingOptions.local` に渡すクラスは `@jsii.implements(ILocalBundling)` JSII デコレータが必要。JSII 非対応クラスを渡すと `AttributeError: __jsii_type__` で失敗する。Dockerなしの代替手段として CDK synth 前に Python で中間ディレクトリを生成するシンプルな関数を使う方が安全
- Lambda Layer 開発時は `cdk synth` 後に `cdk.out/` の asset zip を展開してディレクトリ構造を確認する習慣をつける
---

## 2026-03 Bedrock ValidationException（推論プロファイルID）修正

### 実施内容
- `ai_analyze_handler`（Step2）で ValidationException が連続発生
- Bedrock モデルID の誤りを2段階で修正

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| `ValidationException: The provided model identifier is invalid` | モデルIDが `anthropic.claude-sonnet-4-6-20250514`（ap-northeast-1に存在しないID）だった | `anthropic.claude-sonnet-4-6` に変更 |
| `ValidationException: Invocation of model ID anthropic.claude-sonnet-4-6 with on-demand throughput isn't supported. Retry your request with the ID or ARN of an inference profile` | Claude Sonnet 4.6はオンデマンドスループットに非対応。クロスリージョン推論プロファイル経由でのみ呼び出し可能 | `jp.anthropic.claude-sonnet-4-6`（ap-northeast-1向けJPプロファイルID）に変更 |

### 改善策・再発防止
- Amazon Bedrock の新しい（Claude 4系以降）モデルは`on-demand`スループットに非対応のものが多く、**推論プロファイルID**（`jp.`, `us.`, `global.` プレフィックス）を使う必要がある
- モデルIDは `aws bedrock list-foundation-models` ではなく **`aws bedrock list-inference-profiles`** で確認する（リージョン別プロファイルと基盤モデルIDは別物）
- ap-northeast-1 の場合: `jp.anthropic.claude-sonnet-4-6`（JP profile）または `global.anthropic.claude-sonnet-4-6`
- `list-foundation-models` に表示される `anthropic.claude-sonnet-4-6` は基盤モデルIDで、直接 `InvokeModel` には使えない

---

## 2026-03 Bedrock IAM権限不足エラー修正

### 実施内容
- Step2 (ai_analyze_handler) で Bedrock モデル呼び出しが AccessDeniedException で失敗
- Lambda 実行ロールに AWS Marketplace 権限が不足していたことが原因

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| `AccessDeniedException: Model access is denied due to IAM user or service role is not authorized to perform the required AWS Marketplace actions (aws-marketplace:ViewSubscriptions, aws-marketplace:Subscribe)` | CDK の bedrock IAM ポリシーが `bedrock:InvokeModel` のみを含んでおり、AWS Marketplace サブスクリプション関連権限が不足していた | `pipeline_stack.py` と `lambda_stack.py` の bedrock_policy に `aws-marketplace:ViewSubscriptions` と `aws-marketplace:Subscribe` を追加。両方のスタックを再デプロイ |

### 改善策・再発防止
- **Bedrock モデル（特に外部提供モデル）の呼び出しには、単なる `bedrock:InvokeModel` 権限では足りない**。以下の3つのアクションをセットで付与する必要がある：
  ```
  bedrock:InvokeModel
  aws-marketplace:ViewSubscriptions
  aws-marketplace:Subscribe
  ```
- Bedrock IAM ポリシードキュメント作成時は公式 AWS ドキュメント（Bedrock IAM permissions guide）を参照し、常に3つのアクションをセットで含める
- Lambda エラーログが `aws-marketplace:` を含む場合は、CDK で定義した IAM ポリシーの action リストを確認し、AWS Marketplace 権限が含まれているか確認する、直接 `InvokeModel` には使えない

---

## 2026-03 穴方向プロンプト改善・面選択強化・確度情報削除

### 実施内容
- AIが生成するCadQueryスクリプトで穴の向きが誤る問題をプロンプト改善で対処
- 3Dビューアの選択機能を面（face）/Feature単位に強化
- 不要になった確度情報（confidence_map）をシステム全体から完全削除

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| 穴の向きが正面図・側面図で逆方向に生成される | プロンプトに2D図面→3D軸方向のマッピングルールが不足 | `_build_image_prompt`・`_build_prompt`・chat promptに詳細な穴方向ルール（6方向×ワークプレーン選択）を追加 |
| 3Dビューアで面やFeature単位の選択ができない | SelectionInfoにmeshName/positionのみで、normal/featureIdがなかった | SelectionTypeを追加、face normalの抽出、featureId正規表現抽出、方向ラベル表示を実装 |
| confidence_mapが未使用のまま残存 | 初期設計で確度表示を想定していたが不要になった | backend（ai_analyze_handler, chat_handler, models.py）およびfrontend（Viewer3D, App.tsx）から完全削除 |

### 改善策・再発防止
- CadQueryスクリプト生成プロンプトには2D図面の投影方向→3D軸方向の明示的マッピングを必ず含める
- 不要になった機能（確度表示等）はコード・プロンプト・モデル定義から漏れなく削除し、技術的負債を溜めない
- 3Dインタラクションではface normalやfeatureIdを含むリッチな選択情報をチャットコンテキストに渡すことでAIの修正精度が向上する

---

## 2026-03 AI推論理由表示・面レベルハイライト実装

### 実施内容
- AIが図面を解析した推論理由（reasoning）をプロンプトで出力させ、DynamoDBに保存、WebSocket経由でフロントエンドに表示
- 3Dビューアの面選択をメッシュ全体から個別面（共面三角形群）のハイライトに変更

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| AIが図面を誤解釈しても理由が不明 | プロンプトがスクリプトのみ出力していた | reasoningフィールドをプロンプトに追加し、解析過程をstepごとに出力させる |
| 面クリックでモデル全体がハイライトされる | trimeshがGLBを単一メッシュとして出力するため、マテリアル全体が変更されていた | 共面三角形検出（同一法線+同一平面）でクリック面のみのオーバーレイメッシュを生成し表示 |

### 改善策・再発防止
- AI出力にはreasoning（推論過程）を必ず含めることで、誤解釈時のデバッグが容易になる

---

## 再帰的寸法検証システム実装

### 実施内容
- DynamoDB `drawing_elements` テーブル追加（PK: drawing_id, SK: element_seq, GSI: confidence）
- `dimension_extract_handler`: Bedrock マルチモーダルで図面から要素抽出・確度スコアリング
- `dimension_verify_handler`: 低確度要素の再帰的検証（最大5反復, 閾値0.85）、テンプレートベーススクリプト組み立て、最終AI組み立て
- Step Functions に検証ループ追加（Choice state による反復制御）
- `ws_handler` に `verifyComment` アクション追加（人間フィードバック）
- `VerificationPanel.tsx`: 確度バー・3Dプレビュー・コメント入力UI
- `App.tsx`: 検証タブ・WebSocket VERIFICATION_PROGRESS ハンドリング
- テスト7件追加（extract 2件 + verify 5件）、全40テスト合格

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| DynamoDB に float 値を直接格納できない | boto3 DynamoDB resource は Python float を受け付けず Decimal が必要 | `_float_to_decimal()` ヘルパーで再帰的に変換 |
| `position` が DynamoDB 予約語でUpdateItem失敗 | DynamoDB の予約キーワードをUpdateExpressionに直接使用 | `ExpressionAttributeNames` で `#pos` にエイリアス |
| `confidence_map` テストが既存モデル変更で失敗 | `NodeItem` から `confidence_map` を削除したがテスト未更新 | `test_models.py` のassertを更新 |

### 改善策・再発防止
- DynamoDB にJSON由来のデータを格納するときは常に `_float_to_decimal()` で変換する
- DynamoDB の UpdateExpression では予約語（`position`, `status`, `name` 等）を ExpressionAttributeNames でエイリアスする
- モデル変更時は関連テストの全文検索を行い、不整合を検出する

---

## DXF寸法抽出機能（ezdxf 導入）

### 実施日: 2026-03-31

### 概要
`parse_handler` の DXF 解析を手動文字列パースから `ezdxf` ライブラリに移行。DIMENSION エンティティを `drawing_elements` DynamoDB テーブルに保存する機能を追加。

### 変更内容
| ファイル | 変更内容 |
|---------|---------|
| `backend/requirements.txt` | `ezdxf>=1.0.0` 追加 |
| `cdk/lib/constructs/python_layer.py` | requirements.txt の pip install をレイヤービルドに統合 |
| `backend/functions/parse_handler/index.py` | `_parse_dxf()` を ezdxf ベースに書き換え、DIMENSION 抽出・DB保存 |
| `backend/tests/test_parse_handler.py` | ezdxf で DXF 生成するテストに書き換え + DIMENSION テスト追加 |

### 検出された問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| `ezdxf.write(BytesIO)` で TypeError | ezdxf は `StringIO`（テキストストリーム）に書き出す仕様 | テスト側で `StringIO` → `.encode()` に修正 |
| `ezdxf.read()` にバイトストリーム渡して失敗 | S3 から取得したバイトをそのまま渡していた | `decode()` → `StringIO` に変換してから `ezdxf.read()` に渡す |

### 改善策・再発防止
- `ezdxf` の I/O はテキストストリーム (`StringIO`) を使うこと（バイナリストリームは非対応）
- Lambda Layer に pip パッケージを含める場合は `python_layer.py` で `pip install -t` を使用する

---

## 2026-04 フロントエンド UX 改善（中間プレビュー体験向上）

### 実施内容
- 4件のフロントエンドUX問題を修正

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| 中間プレビュー検証後〜最終3D完成まで画面がフリーズしたように見える | 検証完了(`all_verified`)後に`isVerifying=false`になるが、`gltfUrl`がまだ空の間は静止した中間プレビューが表示されるだけで進行状況が不明 | `isBuildingFinal`状態を追加し、検証完了〜PROCESSING_COMPLETE間にオーバーレイ付きローディング表示を実装 |
| AIへのコメント送信後、コメントが消えて送信されたか不明 | `onSendComment`でテキストをクリアするだけでフィードバックなし | VerificationPanel内に`commentHistory`配列を追加し、送信済みコメントをタイムスタンプ付きで履歴表示 |
| 要素リストで要素をクリックしても3Dプレビュー上のどれか分からない | 要素リストと3Dプレビューに連携がなかった | 要素クリック時に`highlightedElement`状態を設定し、CSGPreview・HoleMarkersの色を紫(#818cf8)に変更してハイライト |
| 要素名をチャットに手入力する手間 | コメント欄に要素名を自分でタイプする必要があった | 要素ダブルクリックで`[要素名] `形式でコメント欄に自動挿入 |

### 改善策・再発防止
- 非同期処理の「間」（検証完了→最終生成）にはフロントエンドで状態遷移を明示する。サイレントな待機状態を作らない
- ユーザーアクションに対するフィードバックは即座に表示する（送信履歴・選択ハイライトなど）
- 単一メッシュのGLBで面レベル選択を行うには、BufferGeometryのfaceIndexから共面三角形を検出し、オーバーレイメッシュでハイライトするアプローチが有効

---

## 2026-04 Bedrock Lambda タイムアウト修正

### 実施日: 2026-04-01

### 概要
`2dto3d-dev-ai_analyze_handler` Lambda が Duration: 300000ms（5分）でタイムアウトする問題を修正。

### 根本原因
| 原因 | 詳細 |
|------|------|
| `invoke_model` の同期ブロッキング | boto3 の `invoke_model` は Bedrock がレスポンス全体を生成し終わるまで TCP コネクションを保持したまま待機する。8192 max_tokens + 大容量画像の組み合わせでは Claude の生成完了が 5 分超になる場合がある |
| Lambda タイムアウトが 300 秒（5 分）に設定されていた | Bedrock 推論時間が Lambda 上限に達してそのまま強制終了 |

### 対処

| 対処 | ファイル |
|------|----------|
| `invoke_model` → `invoke_model_with_response_stream` に変更。chunk イベントを順次受信するためコネクションがアクティブに維持され、Lambda がアイドル待機にならない | `backend/common/bedrock_client.py` |
| Bedrock 呼び出し Lambda のタイムアウトを 300 秒 → **900 秒（Lambda 上限）** に引き上げ | `cdk/lib/stacks/pipeline_stack.py` |
| 変更対象は Bedrock を呼ぶ全3関数: `ai_analyze_handler`・`dimension_extract_handler`・`dimension_verify_handler` | 同上 |

### 改善策・再発防止
- Bedrock の `invoke_model`（同期）は応答全体の生成を待つため、**長いプロンプト・多 max_tokens では Lambda タイムアウトの直接原因になる**。`invoke_model_with_response_stream` を標準として使用する
- streaming API のレスポンス組み立て: Claude の Messages API では `content_block_delta` / `text_delta` イベントのみテキストを含む。他のイベントタイプ（`message_start`, `message_stop` 等）は無視してよい
- Lambda から Bedrock を呼ぶ場合、タイムアウトは **900 秒（Lambda 最大値）** を設定する
- 中長期的には Step Functions native `BedrockInvokeModel` タスクへの移行が理想（Lambda 不要・タイムアウト制約な

---

## 2026-04 UI改修（中間プレビュー・トークン表示・スクロール・チャット統合）

### 実施日: 2026-04-02

### 実施内容
4件のUX課題を修正・実装。

### 発生した問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| チャット再実行後に中間プレビューが表示されない | `handleChatNodeCreated` が `gltfUrl` をクリアせず、古いモデルURLが残り `Viewer3D` が優先表示された | `handleChatNodeCreated` 冒頭で `setGltfUrl("")`・`setVerifyElements([])`・`setVerifyIterations([])` を追加 |
| 累計トークン使用量がフロントエンドで確認できない | `BedrockClient` がトークン数を取得・送信していなかった | `invoke_multimodal` の戻り値を `InvokeResult(text, input_tokens, output_tokens)` に変更。各Lambdaで `send_token_usage` を呼び出してWS通知。フロントでは `TOKEN_USAGE` メッセージを受信して累計表示 |
| 検証タブのコンテンツがスクロールできない | `VerificationPanel` の外側 `div` に `min-h-0` が不足しており flex コンテナが高さを超えてもスクロールが有効にならなかった | `flex flex-1 flex-col` → `flex min-h-0 flex-1 flex-col overflow-hidden` に修正 |
| 検証中用・検証後修正用チャットが別タブで不便 | 右サイドパネルがタブ切替式のため毎回手動切替が必要だった | タブを廃止。`ChatPanel` に `verifyMode` / `onVerifyComment` / `isBuildingFinal` プロパティを追加し、検証中はWS経由コメント送信・完了後はAPI経由モデル修正をシームレス切替。`VerificationPanel` から独立したコメント入力を削除 |

### 変更ファイル
| ファイル | 変更内容 |
|---------|---------|
| `backend/common/bedrock_client.py` | `InvokeResult` dataclass 追加、ストリームからトークン数を抽出 |
| `backend/common/ws_notify.py` | `send_token_usage()` 関数追加 |
| `backend/functions/ai_analyze_handler/index.py` | `send_token_usage` 呼び出し追加 |
| `backend/functions/dimension_extract_handler/index.py` | 同上 |
| `backend/functions/dimension_verify_handler/index.py` | `_verify_elements`・`_final_assembly` のreturnにトークン数を追加 |
| `backend/functions/chat_handler/index.py` | レスポンスに `input_tokens`・`output_tokens` を含める |
| `cdk/lib/stacks/lambda_stack.py` | `bedrock:InvokeModelWithResponseStream` 権限追加 |
| `cdk/lib/stacks/pipeline_stack.py` | 同上 |
| `frontend/src/App.tsx` | タブ廃止・token state追加・ヘッダー表示・統合レイアウト |
| `frontend/src/components/ChatPanel.tsx` | verifyMode対応・トークン通知callback追加 |
| `frontend/src/components/VerificationPanel.tsx` | コメント入力削除・スクロール修正 |

### 改善策・再発防止
- `flex-1` だけでは flex 子要素の高さは親を超えてスクロールを効かせられない。`min-h-0` を組み合わせることで flex コンテナの高さ制約が正しく伝播する
- 状態遷移時にリセットすべき状態を設計段階で洗い出す（今回は `gltfUrl`・`verifyElements`・`verifyIterations` のリセット漏れ）

---

## 2026-07 段階的構築モード（BuildPlan）実装

### 実施内容
- 既存の自動パイプラインと**別モード**として「段階的構築（BuildPlan）」機能を新規実装
- AI が2D図面からステップバイステップの構築計画を生成し、各ステップのパラメータ編集・NLチャット修正・バッチ操作に対応
- バックエンド: 2 Lambda ハンドラー（buildplan_create_handler, buildplan_step_handler）
- インフラ: 2 DynamoDB テーブル（build_plans, build_steps）、6 REST API ルート
- フロントエンド: BuildPlanPanel コンポーネント + App.tsx モード切替
- テスト: 7テスト追加（全49テスト通過）

### 変更ファイル一覧

| ファイル | 変更内容 |
|---------|---------|
| `backend/common/models.py` | `BuildPlanItem`, `BuildStepItem`, `StepParameter` Pydantic モデル追加 |
| `backend/common/config.py` | `build_plans_table`, `build_steps_table` 環境変数フィールド追加 |
| `backend/functions/buildplan_create_handler/index.py` | 新規 — AI BuildPlan 生成ハンドラー |
| `backend/functions/buildplan_step_handler/index.py` | 新規 — ステップ CRUD / 修正 / 実行 / プレビューハンドラー |
| `backend/tests/conftest.py` | `BUILD_PLANS_TABLE`, `BUILD_STEPS_TABLE` テーブル追加 |
| `backend/tests/test_buildplan_step_handler.py` | 新規 — 7テスト（list/get/execute/preview/invalid route） |
| `cdk/lib/stacks/database_stack.py` | `build_plans`, `build_steps` DynamoDB テーブル定義追加 |
| `cdk/lib/stacks/lambda_stack.py` | 2 Lambda 関数 + 6 API ルート + WebSocket 権限追加 |
| `cdk/app.py` | BuildPlan テーブルを LambdaStack に渡すよう更新 |
| `frontend/src/components/BuildPlanPanel.tsx` | 新規 — ステップリスト / パラメータ / NL修正 / 実行UI |
| `frontend/src/App.tsx` | BuildPlan モード切替 + state 管理統合 |
| `README.md` | BuildPlan 機能説明・アーキテクチャ図・構成更新 |

### 設計判断

| 判断 | 理由 |
|------|------|
| Step Functions ではなく REST API Lambda を採用 | 各ステップをインタラクティブに修正・再実行する必要があり、Step Functions のリニアなフローでは対応困難 |
| 既存パイプラインと完全に分離 | 要件として「別モード」が指定されており、既存機能への影響をゼロにするため |
| Dev 環境ではプレースホルダー GLTF を返却 | 既存の mock_cadquery パターンに合わせ、ECS Fargate なしで動作可能 |
| ステップ修正時に対象以降の全ステップをAI再計画 | CadQuery コードの依存関係（result 変数の引き継ぎ）があるため、部分修正では整合性が保てない |

### 改善策・再発防止
- 新テーブル追加時は `conftest.py` のフィクスチャにも同時に追加する
- WebSocket API ID・execute-api 権限は Lambda 作成より後に付与する（CDK コンストラクタの実行順序に注意）
- `ProcessingMode` のような未使用の型を残さないよう、TypeScript `--noEmit` チェックを習慣付ける
- ストリーミング API のメタデータ（トークン数）は `message_start` イベント (`input_tokens`) と `message_delta` イベント (`output_tokens`) から取得できるし・コスト削減）