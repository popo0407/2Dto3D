# 2D to 3D AI生成パイプライン：システム要件定義書

**バージョン:** 1.1.0  
**作成日:** 2026-03-26  
**ステータス:** ドラフト

---

## 目次

1. [システム目的・背景](#1-システム目的背景)
2. [ユーザーとユースケース](#2-ユーザーとユースケース)
3. [入力データ処理要件](#3-入力データ処理要件)
4. [AI推論・生成要件](#4-ai推論生成要件)
5. [修正UX要件（Interactive Refinement）](#5-修正ux要件interactive-refinement)
6. [出力・品質要件](#6-出力品質要件)
7. [非機能要件](#7-非機能要件)
8. [AWSアーキテクチャ設計](#8-awsアーキテクチャ設計)
9. [データモデル設計](#9-データモデル設計)
10. [API設計](#10-api設計)
11. [フロントエンド要件](#11-フロントエンド要件)
12. [開発・デプロイ戦略](#12-開発デプロイ戦略)
13. [コスト管理方針](#13-コスト管理方針)
14. [将来拡張候補](#14-将来拡張候補)

---

## 1. システム目的・背景

### 1.1 目的

2Dの図面データ（DXF・PDF・スキャン画像）をマルチモーダルAI（Amazon Bedrock / Claude Sonnet 4.6）が設計者レベルで解釈し、**単なる幾何変換**ではなく「設計意図」を反映した**編集可能な3D CADモデル（STEP AP214形式）**をブラウザ経由で生成・修正できる AI-First SaaS を構築する。

### 1.2 解決する課題

| 従来の課題 | 本システムの解決策 |
|---|---|
| CADオペレーターによる手動3D化に数時間～数日 | AI自動生成で数分以内に初稿を出力 |
| スキャン図面や汚れたPDFは手動では読み解きが困難 | Claude Sonnet 4.6のビジョン能力でノイズ込みで解釈 |
| 生成結果の検証に再度CADソフトが必要 | ブラウザ上での軽量3Dプレビュー＋再投影バリデーション |
| 修正のたびにゼロから再生成 | 中間コード（CadQuery）の該当フィーチャーのみ差分更新 |
| 三面図の対応関係を人が手動で定義 | AIが文脈を読み取り自動統合（フィーチャー整合チェック） |

---

## 2. ユーザーとユースケース

### 2.1 主要ユーザー

| ロール | ニーズ | 典型的な操作 |
|---|---|---|
| 機械設計者 | 旧来の2D図面を素早くSTEPへ変換したい | DXFアップロード→修正チャット→STEP DL |
| 製造業オペレーター | スキャンした紙図面を3D化したい | PDF/画像アップロード→確認→DL |
| CAD管理者 | プロジェクト単位で複数図面を管理したい | プロジェクト作成→履歴管理→チーム共有 |

### 2.2 主要ユースケース

```
UC-01: 新規図面アップロード → 3D自動生成
UC-02: 生成結果のブラウザ3Dプレビュー確認
UC-03: 自然言語チャットによる3D修正
UC-04: STEP / STL ファイルダウンロード
UC-05: 生成履歴の確認・巻き戻し
UC-06: AIによる不明箇所の質問受け取りと回答
UC-07: 図面間整合性チェックレポート確認
```

---

## 3. 入力データ処理要件

### 3.1 対応入力フォーマット

| フォーマット | 処理ライブラリ | データの扱い方 |
|---|---|---|
| **DXF** (.dxf) | `ezdxf` | 幾何要素（座標・線種・レイヤー）を**確定値**として抽出 |
| **PDF** (.pdf) | `PyMuPDF (fitz)` | ベクター要素抽出 + ラスタライズ画像生成 |
| **画像** (.png/.jpg/.tiff) | `OpenCV` / `Pillow` | CV前処理後、Claude Sonnet 4.6へ渡す |
| **複数ファイル** | 上記組み合わせ | 三面図を別ファイルで提供する場合にも対応 |

**ファイル制約（セキュリティ・パフォーマンス）:**
- 最大ファイルサイズ: 50 MB / ファイル
- 最大ファイル数（1リクエスト）: 10ファイル
- MIME型検証: Content-Type ヘッダーとマジックバイト両方で検証

### 3.2 ハイブリッド・データ・パース

#### 3.2.1 DXFパース

```
入力: DXFファイル
処理:
  1. ezdxfで全エンティティ（LINE, ARC, CIRCLE, SPLINE, TEXT等）を抽出
  2. レイヤー情報・線種を保持したJSON構造に変換
  3. テキストエンティティから寸法注記・引き出し線テキストを紐付け
出力: GeoJSON互換の幾何情報JSON + 注記マッピング辞書
```

#### 3.2.2 PDF/画像パース

```
入力: PDF / スキャン画像
処理:
  1. PyMuPDFで図面枠（タイトルブロック）を検知し余白トリミング
  2. OpenCVでコントラスト強化・傾き補正・ノイズ除去
  3. Claude Sonnet 4.6 Vision APIで三面図領域・寸法線・注記テキストを座標付きで抽出
  4. OCRチェックと幾何整合でテキスト確度スコアを付与
出力: 座標付き注記リスト + 三面図境界マッピング
```

#### 3.2.3 ビジュアル・レンダリング

- DXFデータを**背景白・線黒**の高コントラストPNG（最低 2000×2000px）へ自動変換
- AIが認識しやすいようにレイヤーを色分けしたカラー版も並行生成（デバッグ用）
- PNG生成はLambda上でヘッドレス `matplotlib` + `ezdxf` の描画機能で実行

#### 3.2.4 座標系正規化

- 三面図（正面・平面・側面）のスケール・原点を数理的にマッチング
- 単位検出（mm/inch/cm）を図面の注記またはDXFヘッダから自動抽出
- 矛盾検出時：AIが両図面を比較し、どちらが優先されるべきか理由付きでユーザーへ質問

### 3.3 幾何前処理・品質向上

| 処理 | 内容 |
|---|---|
| ノイズ除去 | GaussianBlur + 適応的二値化でスキャンノイズを除去 |
| 傾き補正 | Hough変換で図面の傾きを検出・自動補正 |
| 対称性検出 | 図面内の対称軸を検出し、片側省略された図面でも完全形状を推定 |
| 幾何拘束推定 | 線の垂直・平行・同心・接線関係を自動抽出してJSONに付加 |
| OCR専門最適化 | CAD図面特有フォント（Simplex, ISOCP等）の認識精度向上 |

---

## 4. AI推論・生成要件

### 4.1 使用AIモデル

| 用途 | モデル | API |
|---|---|---|
| マルチモーダル図面解析 | **Claude Sonnet 4.6** | Amazon Bedrock InvokeModel |
| 自然言語修正コマンド解析 | **Claude Sonnet 4.6** | Amazon Bedrock InvokeModel |
| 不明箇所質問生成 | **Claude Sonnet 4.6** | Amazon Bedrock InvokeModel |

> **注意:** 旧仕様書の「GPT-4o」は Claude Sonnet 4.6（Amazon Bedrock）に変更。  
> Bedrock リージョン: `ap-northeast-1`（東京）を優先。クロスリージョン推論をフォールバックに設定。

### 4.2 マルチモーダル・セマンティック解析

Claude Sonnet 4.6に以下を**同時入力**し、エンティティ・リゾリューションを実現する：

```
入力セット:
  - 画像: 正規化済みPNG（視覚情報）
  - JSON: DXF/PDF幾何情報（数値情報）
  - テキスト: 抽出済み注記・寸法テキスト（語義情報）

要求する解析タスク:
  1. 画像上の「円」とJSON内の「CIRCLE」の紐付け（エンティティ解決）
  2. 「M6」注記が示すネジ穴の同定
  3. 隠れ線・対称軸の推定
  4. 三面図間の矛盾点の抽出
  5. 読み取り確度スコアの算出（0.0〜1.0）
  6. 読み取り不能箇所の自動抽出と質問文生成
```

### 4.3 中間表現（Intermediate Representation）の設計

直接バイナリを生成せず、**実行可能なPython CadQueryスクリプト**を中間表現として保持する。

```python
# 中間表現スクリプト例（AIが生成するコード）
import cadquery as cq

# Feature-001: 基底矩形板
BASE_WIDTH = 100.0   # mm - 正面図から抽出
BASE_HEIGHT = 50.0   # mm - 側面図から抽出
BASE_DEPTH = 20.0    # mm - 平面図から抽出
base = cq.Workplane("XY").box(BASE_WIDTH, BASE_HEIGHT, BASE_DEPTH)

# Feature-002: 貫通穴（M6相当）
HOLE_DIAMETER = 5.0  # mm
HOLE_X = 25.0        # mm
HOLE_Y = 0.0         # mm
result = base.faces(">Z").workplane().center(HOLE_X, HOLE_Y).hole(HOLE_DIAMETER)

# Feature-003: フィレット
result = result.edges("|Z").fillet(2.0)
```

**中間表現の設計原則:**
- 各フィーチャーは独立したコードブロック（`# Feature-NNN`）として識別可能に記述
- 全数値は意味のある定数として抽出（マジックナンバー禁止）
- コメントで出典図面・座標を記録（トレーサビリティ）
- 修正は定数書き換えのみで対応可能な構造

### 4.4 設計意図の推論

AIへのシステムプロンプトで以下を指示する：

```
[設計意図推論の指示]
1. 対称性の利用: 記載されていない半分は対称と扱う
2. 標準フィーチャー認識: ネジ穴は規格寸法（JIS/ISO）に補正
3. 製造制約の考慮: ドリル穴の底面は118°コーン底として処理
4. Water-tight保証: 全面が閉じたソリッドになるよう補完
5. 隠れ線処理: 点線は内部形状として解釈
6. 寸法の優先順位: 記入寸法 > 計算寸法（スケールから算出）
```

### 4.5 AIへの工夫されたプロンプト設計

#### システムプロンプト（固定部）

```
あなたは機械設計の専門家であり、CADオペレーターです。
提供された図面を以下の優先順位で解釈してください：

【解釈の優先順位】
1. 明示的な数値寸法（記入された数字）
2. 図面の幾何要素から計算できる寸法
3. 標準規格（JIS/ISO）に基づく推定
4. 図面の対称性・繰り返しパターン

【出力形式】
- CadQueryスクリプト（実行可能Python）
- 確度スコア（Feature単位）
- 不明箇所の質問リスト（最大5件、優先度付き）

【禁止事項】
- 図面に記載のない形状の付加
- 寸法の独断的な丸め（±0.5mm超）
- 閉じていないソリッド（Water-tightでない形状）
```

#### 不明箇所自己抽出プロンプト

```
図面を解析した結果、以下の箇所で情報が不足または矛盾しています：

[矛盾・不明箇所の報告形式]
- 箇所ID: [Feature番号またはエリア座標]
- 問題の種別: [寸法不明 / 矛盾 / 判読不能 / 標準規格待ち]
- 確度スコア: [0.0〜1.0]
- 仮の解釈: [現時点でAIが採用した仮定]
- 確認のための質問文: [ユーザーへの具体的な質問]
```

---

## 5. 修正UX要件（Interactive Refinement）

### 5.1 3Dプレビュー & ピッキング同期

- `React Three Fiber` を用いたブラウザビューワーを実装
- 生成された3Dモデルの全Face・Edge・Holeに **固有ID** を付与（例: `face_001`, `hole_003`）
- ユーザーがクリックした部位のIDをチャット入力欄へ自動挿入: `[Face-001を選択中]`
- 選択中のパーツはハイライト表示（輪郭光彩エフェクト）

### 5.2 自然言語コマンド・インターフェース

修正コマンドの解析とコードマッピング例：

| ユーザー入力 | AIが解析する操作 | コード変更 |
|---|---|---|
| 「ここの穴を貫通させて」 | Face-001の穴 → through: True | `blind_depth=10` → `.hole(diam)` |
| 「この面の厚みを+5mm」 | Feature-002のextrude distance +5 | `BASE_DEPTH = 20.0` → `25.0` |
| 「右側の穴を3個に増やして」 | Feature-003のパターン count=3 | `count=1` → `count=3` |
| 「フィレットを全部R3に」 | 全fillet半径を3mmに統一 | `fillet(2.0)` → `fillet(3.0)` |

### 5.3 インクリメンタル更新（履歴ツリー）

```
履歴ノード構造:
  Session
    └─ Node-001: 初回生成 [ベースライン]
          └─ Node-002: 穴を貫通に変更
                └─ Node-003: 厚み+5mm
                      └─ Node-004: フィレット変更
                              └─ Node-005: [現在]

操作:
  - 巻き戻し: 任意のNodeへ戻る（それ以降のNodeは非表示化・保持）
  - ブランチ: Node-003から別ルートで編集開始
  - 削除: Node以降の全ノードを削除（確認ダイアログあり）
```

**更新戦略:**  
全体再生成は行わず、変更されたFeatureのみを再計算。  
DynamoDB に中間コードの差分を保持し、任意の時点に戻れるようにする。

### 5.4 AIの確度可視化

- 生成時にFeature単位の確度スコアが付与される（§4.2参照）
- 確度に応じてモデル表面を色分け表示：

| 確度 | 表示色 | 意味 |
|---|---|---|
| 0.9〜1.0 | 通常（マテリアルカラー） | 確信度高 |
| 0.7〜0.9 | 黄色（薄いオーバーレイ） | 推測あり、要確認 |
| < 0.7 | オレンジ〜赤（点滅） | 図面から判断困難 |

---

## 6. 出力・品質要件

### 6.1 3Dモデル出力フォーマット

| フォーマット | 用途 | 生成方法 |
|---|---|---|
| **STEP AP214** | 主要CAD交換フォーマット、ダウンロード用 | CadQuery / PythonOCC |
| **GLTF/GLB** | ブラウザプレビュー用（軽量） | CadQuery → tessellate → GLTF変換 |
| **STL** | 3Dプリント用（オプション） | CadQuery export |

### 6.2 軽量GLTFの生成要件（ブラウザパフォーマンス最重要）

```
品質目標:
  - ファイルサイズ: 10MB以下（通常の機械部品）
  - ポリゴン数: 50,000面以下（LOD最低レベル）
  - Triangle数: 100,000以下
  - マテリアル数: 1〜3（必要最小限）

最適化パイプライン:
  1. CadQuery のテッセレーション精度を制御（deviation=0.1, angularTolerance=0.1）
  2. 平面は細分化しない（冗長なポリゴン排除）
  3. open3d / trimesh でメッシュ最適化（重複頂点削除・法線再計算）
  4. Draco圧縮で最終GLBサイズを最小化
  5. LOD生成: High（50k面）/ Low（5k面）の2段階を生成
```

### 6.3 再投影バリデーション

```
処理フロー:
  1. 生成したSTEPモデルから正面・平面・側面の正投影ビューを生成
  2. 入力2D図面（グレースケール化）と重ね合わせ
  3. ピクセル差分をヒートマップとして表示
  4. 形状漏れ・寸法誤差を定量評価（Hausdorff距離）

品質ゲート:
  - 寸法誤差 ≤ ±1.0mm（設計寸法に対して）
  - ポリゴン一致率 ≥ 95%
  - 未対応形状 = 0（全エッジが3Dモデルに反映）
```

### 6.4 図面間整合性チェック

- 三面図の各寸法を自動クロスチェック（正面図の高さ ↔ 側面図の高さ 等）
- 矛盾箇所をレポートとして出力し、ユーザーへ確認を求める
- チェックレポートはJSON＋PDF形式でダウンロード可能

---

## 7. 非機能要件

### 7.1 パフォーマンス要件

| 処理フェーズ | 目標時間 | 計測条件 |
|---|---|---|
| ファイルアップロード完了 | ≤ 5秒 | 10MB DXFファイル, 100Mbps回線 |
| 図面解析・AI推論 | ≤ 60秒 | 三面図3枚 |
| CadQuery実行・STEP生成 | ≤ 120秒 | 中程度複雑の機械部品 |
| GLTF軽量化完了 | ≤ 30秒 | 50kポリゴン以下のモデル |
| ブラウザへの初期プレビュー表示 | ≤ 3秒 | GLBファイル転送後 |
| 修正指示からプレビュー更新 | ≤ 30秒 | 単一フィーチャー変更 |

### 7.2 セキュリティ要件（OWASP Top 10対応）

| リスク | 対策 |
|---|---|
| A01: アクセス制御の欠陥 | Cognito JWT必須、Lambda AuthorizerでAPI保護 |
| A02: 暗号化の失敗 | S3スタティックファイルはSSE-S3暗号化、転送はTLS 1.2以上 |
| A03: インジェクション | CadQueryコードはAI生成後に静的解析（ast.parse）でコードインジェクション検証 |
| A04: 安全でない設計 | IAMロール最小権限原則、Lambda間はRole経由のみ |
| A05: セキュリティ設定ミス | CDKのSecurity Hub自動チェック統合 |
| A06: 脆弱なコンポーネント | Dependabot自動アップデート、Lambda Layerの定期更新 |
| A08: データ整合性の誤り | AI生成コードはサンドボックス環境（制限付きLambda）で実行、危険モジュールimport禁止 |
| A10: SSRF | Lambda外部ネットワークアクセスを制限（必要なサービスのみVPCエンドポイント） |

**追加セキュリティ対応:**
- ファイルアップロードのMIMEタイプとマジックバイト二重検証
- 生成されたCadQueryコードの実行前AST検証（`import os`, `subprocess`等の禁止パターン検出）
- S3へのアップロードはPresigned URL経由（直接アクセス不可）

### 7.3 可用性・信頼性

- 目標SLA: 99.5%（prod環境）
- ファイル保存: S3（デュアルゾーン自動レプリケーション）
- DynamoDB: オンデマンドキャパシティ（トラフィックに応じた自動スケール）
- Lambdaリトライ: Step Functions での自動リトライ（最大3回、指数バックオフ）
- エラー通知: CloudWatch Alarms → SNS → 開発チームSlack通知

### 7.4 スケーラビリティ

- 想定同時処理ジョブ: 開発初期 10件 / 将来目標 100件
- ECS Fargate（CAD処理）: Auto Scaling（CPU使用率70%でスケールアウト）
- Lambda: 同時実行数制限の設定（デフォルト無制限を適切に制御）

---

## 8. AWSアーキテクチャ設計

### 8.1 全体アーキテクチャ図

```
[ユーザー]
   │
   ▼
[CloudFront]
   │
   ├──► [S3: Frontend (React SPA)]
   │
   └──► [API Gateway (REST)]
              │
              ├── Cognito Authorizer
              │
              ├── [Lambda: upload-handler]
              │         └─► S3 (upload) → SQS (processing queue)
              │
              ├── [Lambda: history-handler]
              │         └─► DynamoDB (session/node CRUD)
              │
              ├── [Lambda: chat-handler]
              │         └─► Bedrock InvokeModel (Claude Sonnet 4.6)
              │             └─► DynamoDB (conversation history)
              │
              └── [API Gateway WebSocket]
                        └─► [Lambda: ws-handler]
                                └─► DynamoDB (connection管理)

[SQS → Step Functions (CAD生成パイプライン)]
  ├── Step1: Lambda (parse-handler) ← DXF/PDF前処理
  ├── Step2: Lambda (ai-analyze-handler) ← Bedrock Claude Sonnet 4.6
  ├── Step3: ECS Fargate (cadquery-runner) ← CadQuery実行
  ├── Step4: Lambda (optimize-handler) ← GLTF軽量化
  ├── Step5: Lambda (validate-handler) ← 再投影バリデーション
  └── Step6: Lambda (notify-handler) ← WebSocket経由で完了通知

[S3バケット構造]  ※ バケット名はグローバル一意のためアカウントIDを付与
  ├── {AccountId}-2dto3d-{env}-uploads/    ← 入力図面ファイル
  ├── {AccountId}-2dto3d-{env}-artifacts/  ← 生成STEP/GLTF/STL
  ├── {AccountId}-2dto3d-{env}-previews/   ← AI解析用正規化PNG
  └── {AccountId}-2dto3d-{env}-frontend/   ← React SPA静的ファイル

[DynamoDB テーブル]
  ├── 2dto3d-{env}-sessions     ← プロジェクト・セッション管理
  ├── 2dto3d-{env}-nodes        ← 履歴ノード（中間コード差分）
  ├── 2dto3d-{env}-connections  ← WebSocket接続管理
  └── 2dto3d-{env}-users        ← (Cognitoと同期したユーザーメタデータ)
```

### 8.2 サービス選定理由

| AWSサービス | 役割 | 選定理由 |
|---|---|---|
| **CloudFront + S3** | フロントエンド配信 | グローバルCDN、静的SPA、低コスト |
| **Cognito** | 認証・認可 | マネージドJWT、GoogleSSOオプション対応 |
| **API Gateway REST** | 同期API | CRUD操作・短命リクエスト |
| **API Gateway WebSocket** | リアルタイム通知 | CAD処理の進捗をプッシュ通知 |
| **Lambda (Python 3.12)** | 軽量処理 | 前処理・AI呼び出し・通知など短命処理 |
| **ECS Fargate** | 重量処理 | CadQuery+OpenCASCADE は1GB+RAM必要、Lambda制限超過のため |
| **Step Functions** | パイプライン制御 | 多段処理のリトライ・並列・状態管理 |
| **SQS** | 非同期キュー | Lambdaへの負荷平準化・デカップリング |
| **Amazon Bedrock** | AI推論 | Claude Sonnet 4.6へのマネージドアクセス |
| **DynamoDB** | NoSQLデータストア | サーバーレス・オンデマンドスケール |
| **S3** | ファイルストレージ | 大容量ファイル保存・ライフサイクル管理 |
| **CloudWatch** | 監視・ログ | X-Ray分散トレーシング統合 |

### 8.3 CDKスタック分割設計

```
cdk/lib/stacks/
├── network_stack.py    # CloudFront + S3 (frontend/uploads/artifacts)
├── auth_stack.py       # Cognito User Pool + App Client
├── database_stack.py   # DynamoDB テーブル群
├── lambda_stack.py     # Lambda群 + API Gateway
├── pipeline_stack.py   # Step Functions + SQS + ECS Fargate
└── monitoring_stack.py # CloudWatch / X-Ray / SNS Alarms
```

**コンテキスト制御（cdk.json）:**

```json
{
  "app": "python app.py",
  "context": {
    "environment": "dev",
    "useMockAI": true,
    "enableFargate": false,
    "bedrockRegion": "ap-northeast-1"
  }
}
```

**デプロイコマンド例:**

```bash
# dev環境（モックAI、Fargate無効）
cdk deploy --all --context environment=dev

# dev環境（実Bedrock使用）
cdk deploy --all --context environment=dev --context useMockAI=false

# prod環境（全機能有効）
cdk deploy --all --context environment=prod --context useMockAI=false --context enableFargate=true
```

### 8.4 命名規則（強制）

```
# Lambda / DynamoDB / Step Functions / ECS 等（アカウントスコープ内で一意）
{ProjectName}-{Environment}-{ResourceType}

# S3バケット（グローバル一意のためAWSアカウントIDを先頭に付与）
{AWSAccountId}-{ProjectName}-{Environment}-{Type}

例:
  2dto3d-dev-lambda
  2dto3d-dev-dynamodb-sessions
  2dto3d-prod-stepfunctions-pipeline
  2dto3d-prod-fargate-cadrunner

  123456789012-2dto3d-dev-uploads
  123456789012-2dto3d-dev-artifacts
  123456789012-2dto3d-dev-previews
  123456789012-2dto3d-prod-frontend
```

---

## 9. データモデル設計

### 9.1 DynamoDB テーブル設計

#### sessions テーブル（`2dto3d-{env}-sessions`）

| 属性 | 型 | 説明 |
|---|---|---|
| `session_id` (PK) | String | UUID |
| `user_id` (GSI) | String | Cognito sub |
| `project_name` | String | ユーザー定義のプロジェクト名 |
| `status` | String | `UPLOADING / PROCESSING / COMPLETED / FAILED` |
| `current_node_id` | String | 現在参照中のノードID |
| `input_files` | List | S3キー一覧 |
| `created_at` | Number | UnixTimestamp |
| `updated_at` | Number | UnixTimestamp |
| `ttl` | Number | DynamoDB TTL（90日） |

#### nodes テーブル（`2dto3d-{env}-nodes`）

| 属性 | 型 | 説明 |
|---|---|---|
| `node_id` (PK) | String | UUID |
| `session_id` (GSI) | String | 親セッションID |
| `parent_node_id` | String | 直前ノードID（ブランチ対応） |
| `type` | String | `INITIAL / MODIFICATION / BRANCH` |
| `cadquery_script` | String | 中間表現Pythonスクリプト（フルバージョン） |
| `diff_patch` | String | 前ノードからの差分（unified diff形式） |
| `step_s3_key` | String | S3上のSTEPファイルキー |
| `gltf_s3_key` | String | S3上のGLTFファイルキー |
| `confidence_map` | Map | Feature単位の確度スコア |
| `user_message` | String | ユーザーの修正指示テキスト |
| `ai_questions` | List | AIが生成した質問リスト |
| `created_at` | Number | UnixTimestamp |

#### connections テーブル（`2dto3d-{env}-connections`）

| 属性 | 型 | 説明 |
|---|---|---|
| `connection_id` (PK) | String | WebSocket接続ID |
| `session_id` | String | 関連セッションID |
| `user_id` | String | Cognito sub |
| `ttl` | Number | TTL（接続切れ後自動削除） |

---

## 10. API設計

### 10.1 REST API エンドポイント

```
POST   /sessions                 # セッション（プロジェクト）作成
GET    /sessions                 # セッション一覧取得
GET    /sessions/{id}            # セッション詳細取得
DELETE /sessions/{id}            # セッション削除

POST   /sessions/{id}/upload     # 図面ファイルアップロード（Presigned URL発行）
POST   /sessions/{id}/process    # CAD生成パイプライン起動
GET    /sessions/{id}/status     # 処理状態取得

GET    /sessions/{id}/nodes      # 履歴ノード一覧
GET    /sessions/{id}/nodes/{nid}           # ノード詳細
POST   /sessions/{id}/nodes/{nid}/revert    # このノードへ巻き戻し
POST   /sessions/{id}/nodes/{nid}/chat      # 修正チャット送信

GET    /sessions/{id}/nodes/{nid}/download?format=step|stl|gltf  # 成果物DL
GET    /sessions/{id}/nodes/{nid}/validate  # 再投影バリデーション結果
```

### 10.2 WebSocket メッセージ形式

```json
// サーバー → クライアント（進捗通知）
{
  "type": "PROGRESS",
  "session_id": "sess-xxx",
  "step": "AI_ANALYZING",
  "progress": 40,
  "message": "三面図を統合解析中..."
}

// サーバー → クライアント（AI質問）
{
  "type": "AI_QUESTION",
  "session_id": "sess-xxx",
  "questions": [
    {
      "id": "q-001",
      "feature_id": "Feature-003",
      "text": "正面図と側面図で穴の深さが矛盾しています。正面図の10mmと側面図の15mm、どちらが正しいですか？",
      "confidence": 0.45
    }
  ]
}

// サーバー → クライアント（完了）
{
  "type": "COMPLETED",
  "session_id": "sess-xxx",
  "node_id": "node-yyy",
  "gltf_url": "https://cdn.example.com/...",
  "validation_score": 0.97
}
```

---

## 11. フロントエンド要件

### 11.1 技術スタック

| カテゴリ | 技術 | バージョン目標 |
|---|---|---|
| フレームワーク | React | 19+ |
| 言語 | TypeScript | 5+ |
| 3Dレンダリング | React Three Fiber + Three.js | R3F v8+ |
| スタイリング | Tailwind CSS v4 | - |
| 状態管理 | Zustand | v5+ |
| 通信 | TanStack Query + axios | - |
| ルーティング | React Router v7 | - |
| アニメーション | Framer Motion | v12+ |
| UIコンポーネント | Serendie Design System思想に準拠 | - |

### 11.2 主要画面構成

#### ダッシュボード（`/`）
- ドラッグ＆ドロップ大型ゾーン（画面中央60%）
- 最近のプロジェクト一覧（カード形式）
- 処理中ジョブのプログレスカード

#### 3Dビューワー（`/session/:id`）

```
┌─────────────────────────────────────────────────────────┐
│  [ヘッダー: プロジェクト名 / ブレッドクラム / DLボタン]   │
├──────────────────────────┬──────────────────────────────┤
│                          │                              │
│   2D図面ビュー            │   3D プレビュー              │
│   (AIオーバーレイ表示)    │   (React Three Fiber)        │
│                          │                              │
│   ← 元図面 + 認識結果表示 │   ← ターンテーブル・ズーム    │
│                          │                              │
├──────────────────────────┤   [断面カット スライダー]      │
│   [確度ヒートマップ凡例]   │   [確度表示 ON/OFF]          │
└──────────────────────────┴──────────────────────────────┘
│  [チャット欄: AI質問・修正指示入力 / 履歴バブル]           │
│  [履歴ツリー: タイムライン表示 / 巻き戻しボタン]           │
└─────────────────────────────────────────────────────────┘
```

### 11.3 3Dプレビュー軽量化 (Three.js実装)

```typescript
// LOD（Level of Detail）実装
const lod = new THREE.LOD();
lod.addLevel(highResModel, 0);   // 近距離: 50k面
lod.addLevel(lowResModel, 100);  // 遠距離: 5k面

// Draco圧縮済みGLBローダー
const loader = new GLTFLoader();
loader.setDRACOLoader(dracoLoader);

// Progressive Loading: まず低解像度を即表示、高解像度をバックグラウンドロード
```

### 11.4 プログレスバー（処理ステータス可視化）

```
ステータス遷移:
  ① ファイル解析中        [████░░░░░░] 20%
  ② AI図面解釈中          [████████░░] 55%
  ③ 3Dモデル構築中        [████████░░] 70%
  ④ 形状最適化中          [█████████░] 90%
  ⑤ 完了                 [██████████] 100%

UI演出:
  - Serendieコンセプト「データが編み上げられているアニメーション」で待機演出
  - ステップが進むたびに軽快なマイクロアニメーション
```

### 11.5 アクセシビリティ（WCAG 2.2 AA）

- 全インタラクティブ要素にキーボード操作対応（Tab/Enter/Escape）
- 3DビューワーにはARIA live regionで状態をスクリーンリーダーへ通知
- ダークモード: Tailwindの `dark:` クラス + `prefers-color-scheme` 自動切替
- コントラスト比: テキスト 4.5:1以上、大テキスト 3:1以上

### 11.6 レスポンシブ対応

| ブレークポイント | レイアウト変化 |
|---|---|
| Mobile (< 768px) | 2D/3D並列→タブ切替、チャットを底面ドロワーへ |
| Tablet (768〜1280px) | 2D/3D並列（縦向き）、チャット折りたたみ |
| Desktop (> 1280px) | フル3ペインレイアウト |

---

## 12. 開発・デプロイ戦略

### 12.1 プロジェクト構造

```
2Dto3D/
├── cdk/
│   ├── app.py
│   ├── cdk.json
│   ├── requirements-cdk.txt
│   └── lib/stacks/
│       ├── network_stack.py
│       ├── auth_stack.py
│       ├── database_stack.py
│       ├── lambda_stack.py
│       ├── pipeline_stack.py
│       └── monitoring_stack.py
├── backend/
│   ├── common/
│   │   ├── config.py
│   │   ├── bedrock_client.py    # Claude Sonnet 4.6 呼び出し
│   │   └── cad_utils.py
│   ├── functions/
│   │   ├── upload_handler/
│   │   ├── parse_handler/
│   │   ├── ai_analyze_handler/
│   │   ├── cadquery_runner/     # ECS Fargate（CadQuery + OpenCASCADE 実行コンテナ）
│   │   ├── optimize_handler/
│   │   ├── validate_handler/
│   │   ├── chat_handler/
│   │   ├── history_handler/
│   │   └── ws_handler/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── viewer3d/       # React Three Fiber コンポーネント
│   │   │   ├── chat/
│   │   │   └── history/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── store/              # Zustand ストア
│   │   └── api/               # API クライアント
│   └── package.json
├── docs/
│   ├── requirements.md         # 本ドキュメント
│   └── retrospective.md
└── README.md
```

### 12.2 環境戦略

| 環境 | 説明 | AI | Fargate |
|---|---|---|---|
| `dev` | 開発・テスト | `useMockAI=true` (デフォルト) | 無効（ローカルCadQueryで代替） |
| `dev` + `useMockAI=false` | Bedrock統合テスト | Claude Sonnet 4.6実機 | 無効 |
| `prod` | 本番 | Claude Sonnet 4.6実機 | 有効 |

### 12.3 CI/CDパイプライン（概要）

```
GitHub main branch push
  → GitHub Actions
      ├── lint + typecheck (frontend)
      ├── pytest (backend)
      ├── cdk diff (インフラ差分出力)
      └── cdk deploy dev (自動) / prod (承認後)
```

---

## 13. コスト管理方針

### 13.1 主要コスト要因

| サービス | 課金形態 | コスト最適化策 |
|---|---|---|
| Amazon Bedrock (Claude Sonnet 4.6) | 入力/出力Tokenあたり | プロンプトキャッシュ活用、無駄なトークン削減 |
| ECS Fargate | CPU・メモリ時間 | 処理完了後即コンテナ終了、スポット利用検討 |
| Step Functions | 状態遷移あたり | Express Workflowを使用（Standard比で最大10倍安価） |
| DynamoDB | リクエスト・ストレージ | TTL設定で古データ自動削除（90日） |
| S3 | ストレージ・転送 | Intelligent-Tiering + 不要ファイルのLifecycle削除 |

### 13.2 開発環境コスト抑制

- dev環境では `useMockAI=true` をデフォルト設定（§12.2参照）
- Fargate はdev環境で無効化（Lambda + ローカル実行で代替）
- CloudFrontは開発時はオリジナルS3直アクセスも許可（デバッグ容易化）

---

## 14. 将来拡張候補

以下は現在のスコープ外だがGitHub Issueとして登録し管理する：

| 機能 | 概要 | Priority |
|---|---|---|
| チーム共有機能 | プロジェクトを複数ユーザーで共有・コメント | Medium |
| バッチ変換 | 複数DXFファイルの一括3D化 | High |
| CADソフトプラグイン | SolidWorks / Fusion360 からの直接連携 | Low |
| BIM対応 | 建築図面のIFC形式出力 | Medium |
| オンプレミス/VPC対応 | セキュリティ要件の高い製造業向け | Medium |
| Bedrock Agent化 | 対話修正フェーズのBedrock Agent移行（セッション管理の委任） | Low |
| WAF導入 | CloudFront + API GatewayへのSQLi/XSS対策・レートリミット | Medium |
| ウイルススキャン | S3アップロード時のClamAV等によるファイルスキャン | Low |
| Lambda コンテナ化 | ECS FargateをLambdaコンテナイメージへ一本化（管理コスト削減） | Medium |
| AR/VRプレビュー | WebXR経由でのAR確認 | Low |

---

## 付録 A: Bedrock Claude Sonnet 4.6 API呼び出し設計

```python
# backend/common/bedrock_client.py
import boto3
import json
import base64
from typing import Optional

bedrock = boto3.client("bedrock-runtime", region_name="ap-northeast-1")

MODEL_ID = "anthropic.claude-sonnet-4-6"

def invoke_multimodal(
    prompt: str,
    image_bytes: Optional[bytes] = None,
    context_json: Optional[dict] = None,
    system_prompt: str = "",
    max_tokens: int = 4096,
) -> dict:
    """
    Claude Sonnet 4.6 のマルチモーダル呼び出し
    画像（PNG bytes）と構造化JSON（幾何情報）を同時に入力する
    """
    content = []

    if image_bytes:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(image_bytes).decode(),
            }
        })

    if context_json:
        content.append({
            "type": "text",
            "text": f"【図面の幾何情報（JSON）】\n{json.dumps(context_json, ensure_ascii=False, indent=2)}"
        })

    content.append({"type": "text", "text": prompt})

    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": content}],
        }),
        contentType="application/json",
        accept="application/json",
    )

    result = json.loads(response["body"].read())
    return result["content"][0]["text"]
```

---

## 付録 B: CadQuery実行環境設計（ECS Fargate コンテナ）

```dockerfile
# backend/functions/cadquery_runner/Dockerfile
FROM python:3.12-slim

# OpenCASCADE + CadQuery依存ライブラリ
RUN apt-get update && apt-get install -y \
    libglu1-mesa libxi6 libxmu6 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    cadquery==2.4.0 \
    open3d==0.18.0 \
    trimesh==4.4.0 \
    numpy \
    boto3

COPY runner.py /app/runner.py
WORKDIR /app

CMD ["python", "runner.py"]
```

**セキュリティ要件 (CadQuery実行前AST検証):**

```python
import ast

BLOCKED_PATTERNS = ["import os", "import subprocess", "import sys", "__import__", "eval(", "exec("]

def validate_cadquery_script(script: str) -> bool:
    """AIが生成したCadQueryコードの安全性を検証"""
    for pattern in BLOCKED_PATTERNS:
        if pattern in script:
            raise ValueError(f"ブロックされたパターンが含まれています: {pattern}")
    try:
        ast.parse(script)
    except SyntaxError as e:
        raise ValueError(f"構文エラー: {e}")
    return True
```

---

*本ドキュメントは初期要件定義草案です。*
