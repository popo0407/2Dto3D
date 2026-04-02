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
   - 5.1 [3Dプレビュー & ピッキング同期](#51-3dプレビュー--ピッキング同期)
   - 5.2 [自然言語コマンド・インターフェース](#52-自然言語コマンドインターフェース)
   - 5.3 [インクリメンタル更新（履歴ツリー）](#53-インクリメンタル更新履歴ツリー)
   - 5.4 [AIの確度可視化](#54-aiの確度可視化)
   - 5.5 [Interactive BuildPlan（段階的CAD構築）](#55-interactive-buildplan段階的cad構築とインタラクティブ修正) ← **新機能**
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

### 5.5 Interactive BuildPlan（段階的CAD構築とインタラクティブ修正）

本機能により、ユーザーは2D図面から3Dモデルが**ステップごとに構築される過程を確認**し、各段階で修正・再計画できます。

#### 5.5.1 概要

従来の「一括AI生成 → 全体修正」から、以下のフローへ転換します：

```
┌─ AI が図面を分析し BuildPlan を生成
│   例: [Box 作成, 穴#1 あけ, 穴#2 あけ, M6 タップ, C面取り, ...]
│
├─ 各 Step を順序実行し、チェックポイント保存
│   Step 1: 円柱作成 → Step 1 確認
│   Step 2: M6 穴あけ → Step 2 確認
│   Step 3: C 面取り → Step 3 確認
│
├─ ユーザーが任意のステップで修正指示
│   例: 「Step 2 を直径 8mm に変更」
│
└─ AI がステップを再計画し、差分実行
    修正後のステップ以降を再実行 + プレビュー更新
```

#### 5.5.2 BuildPlan のデータモデル

```json
{
  "plan_id": "plan-20260402-001",
  "session_id": "sess-001",
  "plan_status": "active" | "archived",
  "created_at": 1738598400,
  "steps": [
    {
      "step_seq": "0001",
      "step_type": "base_body",
      "step_name": "基本直方体",
      "parameters": {
        "width": {"value": 100.0, "unit": "mm", "source": "extracted"},
        "height": {"value": 60.0, "unit": "mm", "source": "extracted"},
        "depth": {"value": 20.0, "unit": "mm", "source": "extracted"}
      },
      "cq_code": "result = cq.Workplane('XY').box(100, 60, 20)",
      "dependencies": [],
      "confidence": 0.95,
      "status": "completed",
      "checkpoint": {
        "step_file": "s3://bucket/checkpoints/plan-001/step-0001.step",
        "preview_glb": "s3://bucket/previews/plan-001/step-0001.glb",
        "executed_at": 1738598500
      }
    },
    {
      "step_seq": "0002",
      "step_type": "tapped_hole",
      "step_name": "M6 タップ穴 #1",
      "parameters": {
        "designation": {"value": "M6", "source": "extracted", "confidence": 0.92},
        "drill_diameter": {"value": 5.0, "source": "standard", "confidence": 1.0},
        "tap_depth": {"value": 12.0, "source": "extracted", "confidence": 0.85},
        "position_x": {"value": 25.0, "source": "extracted"},
        "position_y": {"value": 15.0, "source": "extracted"}
      },
      "cq_code": "result = result.faces('>Z').workplane().pushPoints([(25,15)]).hole(5.0, 12.0)",
      "dependencies": ["0001"],
      "confidence": 0.85,
      "status": "completed",
      "checkpoint": {...}
    }
  ],
  "current_step": "0002",
  "total_steps": 5
}
```

**フィールド定義:**
- `step_seq`: このステップの連番（ソートキー）
- `step_type`: `base_body`, `hole_through`, `tapped_hole`, `fillet`, `chamfer`, `pocket`, etc.
- `step_name`: UI 表示用の日本語ラベル
- `parameters`: 各パラメータと**その出典（extracted/standard/calculated）**及び信頼度
- `cq_code`: このステップの CadQuery コード（実行可能な形式）
- `dependencies`: このステップが依存する前段のステップ連番
- `status`: `pending`, `completed`, `failed`, `modified`
- `checkpoint`: 実行結果の STEP ファイルと GLB プレビューの S3 ロケーション

#### 5.5.3 修正ワークフロー

##### フロー例：「M6 穴の直径を 8mm に変更」

**Step 1: ユーザーが修正対象を指定**
```
UI:
  [BuildPlan ステップリスト]
    □ Step 1: 基本直方体 ✓
    □ Step 2: M6 タップ穴 #1 ← ユーザーがクリック選択
    □ Step 3: M6 タップ穴 #2
    □ Step 4: C 面取り
```

**Step 2: 修正内容を指指定（2 つの方法）**

方法A: **パラメータ UI で直接編集**
```
┌─ Step 2: M6 タップ穴 #1
├─ designation: [M6] ← ドロップダウン
├─ drill_diameter: [8.0 mm] ← 直接入力＆値提案
├─ tap_depth: [12.0 mm]
└─ [確認] ボタン
```

方法B: **自然言語で指示**
```
チャット入力欄:
  「Step 2 をこうしたい: 直径 8mm に変更」
  
AI が解析:
  - 対象: Step 2 (M6 穴 #1)
  - パラメータ: drill_diameter = 8.0 に変更
```

**Step 3: AI が修正後の BuildPlan を再計画**
```
AI:「Step 2 で直径を 8mm に変更すると...
  ⚠️  注意: Step 3 も同じ M6 ですが、此方も同じ直径に変更しますか？

  修正案:
    Step 2: drill_diameter 8.0 に変更 ✓
    Step 3: 同じパラメータセットで自動更新 ✓

  Step 4 (C 面取り) も同じ穴を対象なので、関連なし。」
```

**Step 4: 差分実行**
```
処理フロー:
  1. Step 1 (基本直方体) → チェックポイントをロード [S3 から]
  2. Step 2 (修正済) → 新しいパラメータで再実行
  3. Step 3 (依存) → Step 2 の結果をベースに再実行
  4. Step 4 以降 → 自動実行
  5. 全ステップの最終結果を STEP/GLB で出力
```

**Step 5: UI 更新**
```
ステップリスト:
  □ Step 1: 基本直方体 ✓
  ⚠️  Step 2: M6 タップ穴 #1 [修正中] 60%... → [修正完了] ✓
  ⚠️  Step 3: M6 タップ穴 #2 [再実行中] 30%... → [完了] ✓
  □ Step 4: C 面取り [再実行中] → [完了] ✓

プレビュー画面:
  3D モデルがステップごとに更新
  「Step 3 を再実行中...」→「完了 ✓」
```

#### 5.5.4 一括修正（同じ特性を持つ要素）

同じ径・深さを持つ穴が複数ある場合、一括で修正可能：

```
UI: ステップリスト上で複数選択
  ☑ Step 2: M6 タップ穴 #1
  ☑ Step 3: M6 タップ穴 #2
  
修正:「これら両方の直径を 8mm に」

AI が認識:
  - 対象: Step 2, 3（同じ designation "M6"）
  - 修正: drill_diameter = 8.0 に統一
  - 実行: 両ステップを同時に立ち上げ実行（高速化）
```

#### 5.5.5 形状推定の失敗に対応（楕円 vs 円）

AI が円と判定したが、実際は楕円だった場合：

```
チャット:
  「実は楕円なんです。長軸 30mm、短軸 20mm です」
  
AI 応答:
  「わかりました。基本形状の再計画が必要です。
   Step 1: 基本直方体 [そのまま]
   Step 2: 穴の位置・形状を再定義
   
   以下の方法が考えられます:
   ① ツール口 (Pocket) として穴を彫る
   ② 複雑なスケッチを使用
   
   どちらをお勧めしますか？」
```

**ユーザーが方法を選択すると、AI が BuildPlan を再生成**

#### 5.5.6 AI の思考プロセス可視化（UX）

修正実行中は「AI が何をしているか」をステップバイステップで表示：

```
実行ステータスパネル:
┌──────────────────────────────────
│ 修正実行中... Step 2-4 を再計画
├──────────────────────────────────
│
│ Step 1: 基本直方体 → ロード中... ✓
│ Step 2: 新しい穴径を CadQuery で計算中... (45%)
│   └─ 「drill_diameter = 8.0 で計算」
│ Step 3: 後続ステップの依存解析中... ✓
│   └─ 「Step 2 の結果から自動更新」
│ Step 4: 全要素の整合チェック中... (100%)
│   └─ 「問題なし」
│
│ プレビュー更新中... (50%)
│ 最終 STEP 出力中...
│
└──────────────────────────────────
         完了 ✓ (3.2 秒)
```

#### 5.5.7 API エンドポイント（新規追加）

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/sessions/{id}/build-plans` | POST | 図面から BuildPlan を生成（AI 呼び出し） |
| `/api/build-plans/{id}/steps` | GET | BuildPlan のステップ一覧を取得 |
| `/api/build-plans/{id}/steps/{seq}` | GET | 指定ステップの詳細取得 |
| `/api/build-plans/{id}/steps/{seq}/modification` | POST | ステップの修正を指示（パラメータ or 自然言語） |
| `/api/build-plans/{id}/preview/{seq}` | GET | ステップの GLB プレビューを取得（S3 署名付き URL） |
| `/api/build-plans/{id}/apply-modifications` | POST | 修正内容を確定し、差分実行を開始 |
| `/api/build-plans/{id}/execute-from-step` | POST | 指定ステップから再実行 |
| `/api/build-plans/{id}/rollback/{seq}` | POST | 指定ステップに巻き戻し |

#### 5.5.8 ステップ実行エンジンの実装戦略

**差分実行の高速化:**
- 修正されたステップの前まで S3 のチェックポイント（STEP ファイル）をロード
- 修正されたステップ以降を Python exec() で動的実行
- 各ステップの実行結果をメモリに保持（DynamoDB 書き込み前）
- 最終結果だけを STEP/GLB で保存

**例：Step 2 を修正した場合**
```
1. S3 から Step-0001.step をロード（基本直方体）
2. Step 0002' を実行（修正済みコード）メモリ内で中間形状を保持
3. Step 0003 を実行（中間形状を入力とする）
4. Step 0004, 05... を順序実行
5. 最終結果を STEP ファイルで出力
```

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

#### drawing_elements テーブル（`2dto3d-{env}-drawing-elements`）

各図面を個々の設計要素（フィーチャー）単位に分解して保存する。  
AIによる再検証ループおよびユーザー検証の対象単位となる。

| 属性 | 型 | 説明 |
|---|---|---|
| `drawing_id` (PK) | String | 対象セッションID |
| `element_seq` (SK) | String | 同一図面内の順序番号（例: "0001"） |
| `element_type` | String | フィーチャー種別（下記参照） |
| `feature_label` | String | AIが付与した識別名（例: "Hole-M6-01"） |
| `feature_spec` | Map | **element_type ごとの詳細パラメータ**（下記スキーマ参照） |
| `dimensions` | Map | 後方互換・概要寸法（width/height/depth/diameter/radius） |
| `position` | Map | 3D空間での位置座標 `{x, y, z}` |
| `orientation` | String | フィーチャーの向き（例: "+Z", "-Y"） |
| `cq_fragment` | String | この要素を生成する CadQuery コード断片 |
| `confidence` | Number | AI 推論の信頼度スコア (0.0〜1.0)、GSI ソートキー |
| `is_verified` | Boolean | 信頼度が閾値（0.85）以上かどうか |
| `ai_reasoning` | String | AI がこの要素を推定した根拠テキスト |
| `verification_count` | Number | 人間による再検証回数 |
| `node_id` | String | この要素が属するノードID |
| `ttl` | Number | DynamoDB TTL（90日） |

**GSI**: `drawing_id-confidence-index`（drawing_id で絞り込み、confidence 昇順で低確度を最優先に取得）

##### element_type の有効値

| 値 | 説明 |
|---|---|
| `box` | 基本直方体（ベース形状） |
| `hole_through` | 貫通穴 |
| `hole_blind` | 止め穴（ブラインドホール） |
| `tapped_hole` | ネジ穴（タップ穴） |
| `fillet` | R 面取り |
| `chamfer` | C 面取り |
| `slot` | 長穴 |
| `pocket` | ポケット加工 |
| `boss` | ボス（突起） |
| `rib` | リブ |
| `other` | 上記以外 |

##### feature_spec スキーマ（element_type ごと）

```json
// hole_through（貫通穴）
{ "hole_type": "through", "diameter": 6.0 }

// hole_blind（止め穴）
{ "hole_type": "blind", "diameter": 6.0, "depth": 10.0 }

// tapped_hole（ネジ穴・タップ穴）
{
  "hole_type": "tapped",
  "designation": "M6",        // JIS/ISO ネジ呼び径
  "pitch": 1.0,               // ネジピッチ (mm)
  "tap_depth": 15.0,          // タップ深さ (mm)
  "drill_diameter": 5.0,      // 下穴径 (mm)
  "through": false,           // 貫通タップの場合 true
  "standard": "JIS"           // "JIS" | "ISO" | "UNC" | "UNF" | "other"
}

// fillet（R 面取り）
{ "radius": 2.0, "edge_selector": "|Z", "quantity": 4 }

// chamfer（C 面取り）
{ "distance": 1.0, "angle": 45.0, "edge_selector": "|Z", "quantity": 2 }

// slot（長穴）
{ "width": 6.0, "length": 20.0, "depth": null, "orientation": "+Z" }

// pocket（ポケット）
{ "width": 30.0, "height": 20.0, "depth": 5.0 }
```

#### build_plans テーブル（`2dto3d-{env}-build-plans`）

Interactive BuildPlan 機能用。図面ごとの構築計画（段階的ステップ）を保存します。

| 属性 | 型 | 説明 |
|---|---|---|
| `plan_id` (PK) | String | 構築計画ID（例: `plan-20260402-001`） |
| `session_id` (GSI-PK) | String | 属するセッションID |
| `plan_status` | String | `active` / `archived` / `failed` |
| `plan_name` | String | 計画名（例: "Block A - 穴加工版"） |
| `extracted_drawing_id` | String | 参照元の図面ID（drawing_elements のグループ） |
| `total_steps` | Number | ステップ総数 |
| `current_step` | String | 現在実行中のステップ番号 |
| `completion_percentage` | Number | 全体進捗（0〜100） |
| `created_at` | Number | 作成UNIX時刻 |
| `updated_at` | Number | 最終更新UNIX時刻 |
| `ai_reasoning` | String | このプラン生成時のAI根拠説明 |
| `ttl` | Number | DynamoDB TTL（90日） |

**GSI**: `session_id-updated_at-index`（同じセッションの複数プラン管理用）

#### build_steps テーブル（`2dto3d-{env}-build-steps`）

各 BuildPlan 内のステップごとの詳細情報。修正履歴・チェックポイント情報を保持。

| 属性 | 型 | 説明 |
|---|---|---|
| `plan_id` (PK) | String | 属するプランID |
| `step_seq` (SK) | String | 同一プラン内のステップ番号（例: `0001`, `0002`） |
| `step_type` | String | ステップタイプ（`base_body`, `hole_through`, `tapped_hole`, `fillet`, `chamfer` など） |
| `step_name` | String | 日本語ラベル（例: `「M6タップ穴#1」`） |
| `parameters` | Map | パラメータ群（例：`{width: {value: 100, unit: "mm", source: "extracted"}, ...}`） |
| `cq_code` | String | このステップの CadQuery コード（実行可能な Python） |
| `cq_code_hash` | String | cq_code のハッシュ値（修正検出用） |
| `dependencies` | List | 依存する前段ステップの step_seq 配列 |
| `confidence` | Number | このステップの推論信頼度（0.0〜1.0） |
| `confidence_breakdown` | Map | パラメータごとの信頼度（トレーサビリティ用） |
| `status` | String | `pending` / `completed` / `failed` / `modified` |
| `execution_log` | String | 実行ログ（エラー時の詳細など） |
| `checkpoint_step` | String | チェックポイント STEP ファイルの S3 ロケーション |
| `checkpoint_glb` | String | チェックポイント GLB プレビューの S3 ロケーション |
| `executed_at` | Number | このステップの最終実行時刻 |
| `modification_count` | Number | 修正（再実行）回数 |
| `ai_reasoning` | String | AI がこのステップを生成した根拠 |
| `ttl` | Number | DynamoDB TTL（90日） |

**GSI**: `plan_id-confidence-index`（低確度ステップを優先取得）

#### step_modifications テーブル（`2dto3d-{env}-step-modifications`）

ユーザーが行ったステップ修正の履歴。トレーサビリティ・ロールバック用。

| 属性 | 型 | 説明 |
|---|---|---|
| `modification_id` (PK) | String | 修正ID（例: `mod-20260402-001`） |
| `plan_id` (GSI-PK) | String | 対象プランID |
| `target_step_seq` | String | 修正対象のステップ |
| `modification_type` | String | `parameter_edit` / `parameter_batch` / `shape_replan` / `rollback` |
| `original_parameters` | Map | 修正前のパラメータ（復元用） |
| `modified_parameters` | Map | 修正後のパラメータ |
| `modification_comment` | String | ユーザーが入力した修正指示（自然言語） |
| `affected_steps` | List | この修正で影響を受けるステップ番号 |
| `ai_replan_result` | Map | AI が行った再計画の結果（which steps to re-execute） |
| `status` | String | `pending` / `executing` / `completed` / `failed` |
| `created_at` | Number | 修正申請時刻 |
| `executed_at` | Number | 実行完了時刻 |
| `ttl` | Number | DynamoDB TTL（90日） |

**GSI**: `plan_id-created_at-index`（修正履歴の時系列表示用）

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

# --- BuildPlan（段階的CAD構築） ---
POST   /sessions/{id}/build-plans              # 図面から BuildPlan を生成
GET    /sessions/{id}/build-plans              # BuildPlan 一覧
GET    /sessions/{id}/build-plans/{planId}     # BuildPlan 詳細

GET    /build-plans/{planId}/steps             # ステップ一覧
GET    /build-plans/{planId}/steps/{seq}       # ステップ詳細
GET    /build-plans/{planId}/steps/{seq}/preview  # ステップの GLB プレビュー取得

POST   /build-plans/{planId}/steps/{seq}/modification   # ステップ修正指示（パラメータ or 自然言語）
POST   /build-plans/{planId}/apply-modifications        # 修正を確定・実行
POST   /build-plans/{planId}/execute-from-step?step_seq=0003  # 指定ステップから再実行
POST   /build-plans/{planId}/rollback?step_seq=0002     # 指定ステップに巻き戻し

GET    /build-plans/{planId}/modifications    # 修正履歴一覧
GET    /build-plans/{planId}/modifications/{modId}  # 修正詳細

# --- 従来のノード・チャット（互換性維持） ---
GET    /sessions/{id}/nodes      # 履歴ノード一覧
GET    /sessions/{id}/nodes/{nid}           # ノード詳細
POST   /sessions/{id}/nodes/{nid}/revert    # このノードへ巻き戻し
POST   /sessions/{id}/nodes/{nid}/chat      # 修正チャット送信

GET    /sessions/{id}/nodes/{nid}/download?format=step|stl|gltf  # 成果物DL
GET    /sessions/{id}/nodes/{nid}/validate  # 再投影バリデーション結果
```

### 10.2 BuildPlan API 詳細（Interactive BuildPlan）

#### 例1: BuildPlan の生成

**リクエスト:** `POST /sessions/{id}/build-plans`
```json
{
  "drawing_id": "drawing-2024-0402-001",
  "plan_name": "初期計画"
}
```

**レスポンス:** (202 Accepted - 非同期処理)
```json
{
  "plan_id": "plan-20260402-001",
  "session_id": "sess-001",
  "status": "generating",
  "message": "BuildPlan 生成中。完了するとWebSocket経由で通知します"
}
```

**WebSocket 通知**（生成完了時）:
```json
{
  "type": "BUILD_PLAN_READY",
  "plan_id": "plan-20260402-001",
  "total_steps": 5,
  "message": "BuildPlan 生成完了。5ステップの構築計画が準備できました"
}
```

#### 例2: ステップ詳細の取得

**リクエスト:** `GET /build-plans/{planId}/steps/0002`

**レスポンス:**
```json
{
  "plan_id": "plan-20260402-001",
  "step_seq": "0002",
  "step_type": "tapped_hole",
  "step_name": "M6 タップ穴 #1",
  "parameters": {
    "designation": {
      "value": "M6",
      "unit": null,
      "source": "extracted",
      "confidence": 0.92
    },
    "drill_diameter": {
      "value": 5.0,
      "unit": "mm",
      "source": "standard_table",
      "confidence": 1.0
    },
    "tap_depth": {
      "value": 12.0,
      "unit": "mm",
      "source": "extracted",
      "confidence": 0.85
    },
    "position_x": {
      "value": 25.0,
      "unit": "mm",
      "source": "extracted",
      "confidence": 0.88
    },
    "position_y": {
      "value": 15.0,
      "unit": "mm",
      "source": "extracted",
      "confidence": 0.88
    }
  },
  "cq_code": "result = result.faces('>Z').workplane().pushPoints([(25,15)]).hole(5.0, 12.0)",
  "dependencies": ["0001"],
  "confidence": 0.85,
  "status": "completed",
  "checkpoint_step": "s3://bucket/checkpoints/plan-001/step-0002.step",
  "checkpoint_glb": "s3://bucket/previews/plan-001/step-0002.glb",
  "executed_at": 1738598500,
  "modification_count": 0,
  "ai_reasoning": "M6 規格（JIS B 0205）に基づき、下穴径 5.0mm、ピッチ 1.0mm。タップ深さは板厚の 60% で推定"
}
```

#### 例3: ステップの修正（パラメータ編集）

**リクエスト:** `POST /build-plans/{planId}/steps/0002/modification`
```json
{
  "modification_type": "parameter_edit",
  "parameters": {
    "drill_diameter": {
      "value": 8.0,
      "reason": "実際には 8mm の穴が必要でした"
    }
  }
}
```

**レスポンス:**
```json
{
  "modification_id": "mod-20260402-001",
  "plan_id": "plan-20260402-001",
  "target_step_seq": "0002",
  "status": "validating",
  "ai_response": {
    "analysis": "Step 2 の直径を 8mm に変更。後続ステップの検証中...",
    "affected_steps": ["0003", "0004"],
    "warnings": [
      {
        "step": "0003",
        "message": "Step 3 も同じ M6 タップです。同様に直径 8mm に変更しますか？",
        "suggestion": "両方同時に修正することをお勧めします"
      }
    ],
    "next_steps": ["0002", "0003", "0004", "0005"]
  }
}
```

#### 例4: ステップの修正（自然言語）

**リクエスト:** `POST /build-plans/{planId}/steps/0002/modification`
```json
{
  "modification_type": "parameter_edit",
  "modification_comment": "この穴を大きくしたいです。貫通穴にすることはできますか？"
}
```

**レスポンス:**
```json
{
  "modification_id": "mod-20260402-002",
  "plan_id": "plan-20260402-001",
  "target_step_seq": "0002",
  "status": "awaiting_confirmation",
  "ai_analysis": {
    "interpretations": [
      {
        "interpretation": "タップ穴から 通常の貫通穴に変更（M6 ネジ機能を削除）",
        "required_changes": {
          "step_type": "hole_through",
          "drill_diameter": 8.0
        },
        "impact": "Step 2 のみを変更。Step 3 以降は影響なし"
      },
      {
        "interpretation": "M6 タップはそのまま、貫通タップに変更（深さを板厚相当に）",
        "required_changes": {
          "through": true,
          "tap_depth": 20.0
        },
        "impact": "M6 ネジ機能は保持。深いタップになります"
      }
    ],
    "recommendation": "用途次第ですが、通常の貫通穴への変更をお勧めします"
  }
}
```

#### 例5: 修正の確定・実行

**リクエスト:** `POST /build-plans/{planId}/apply-modifications`
```json
{
  "modification_id": "mod-20260402-001",
  "choices": {
    "step_0002_diameter": 8.0,
    "step_0003_apply_same": true
  }
}
```

**レスポンス:** (202 Accepted)
```json
{
  "modification_id": "mod-20260402-001",
  "status": "executing",
  "message": "修正を実行中... Step 2, 3, 4, 5 を再実行します"
}
```

**WebSocket 進捗通知**:
```json
{
  "type": "BUILD_STEP_PROGRESS",
  "plan_id": "plan-20260402-001",
  "current_step": "0002",
  "progress": 25,
  "message": "Step 2: 新しいパラメータで実行中..."
}

{
  "type": "BUILD_STEP_PROGRESS",
  "plan_id": "plan-20260402-001",
  "current_step": "0003",
  "progress": 50,
  "message": "Step 3: 依存ステップを再実行中..."
}

{
  "type": "BUILD_PLAN_UPDATE",
  "plan_id": "plan-20260402-001",
  "current_step": "0005",
  "completion_percentage": 100,
  "message": "修正が完了しました。新しい 3D モデルを確認してください",
  "updated_glb_preview": "s3://bucket/previews/plan-001/final.glb"
}
```

### 10.3 WebSocket メッセージ形式

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

#### BuildPlan ビューワー（`/session/:id/build-plans/:planId`）

**新機能：段階的CAD構築を可視化**

```
┌─────────────────────────────────────────────────────────┐
│  BuildPlan: 「Block A - 穴加工版」 | ステップ 2/5        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [ステップ一覧パネル左側]   │   [3D プレビュー右側]       │
│  ┌─────────────────────┐   │  ┌────────────────────┐  │
│  │ Step 1: 基本直方体  │   │  │                    │  │
│  │  ✓ 完了             │   │  │  (Three.js GLB)   │  │
│  │ —────────────────   │   │  │ [現在: Step 2]    │  │
│  │ Step 2: M6穴 #1    │ ← │  │                    │  │
│  │  ⓞ 実行中 (45%)     │   │  │                    │  │
│  │ —────────────────   │   │  │                    │  │
│  │ Step 3: M6穴 #2    │   │  │ [次のステップを待機中...]  │
│  │  ○ 待機中           │   │  │                    │  │
│  │ —────────────────   │   │  │                    │  │
│  │ Step 4: C面取り    │   │  │ [フロー: 修正前→実行中→…]  │
│  │  ○ 待機中           │   │  │                    │  │
│  │ —────────────────   │   │  │                    │  │
│  │ Step 5: 検証       │   │  │ [選択時: パラメータ表示]  │
│  │  ○ 待機中           │   │  │                    │  │
│  └─────────────────────┘   │  └────────────────────┘  │
│                             │  [確度インジケータ]      │
│  [ステップダブルクリック    │  Step 2: 85/100         │
│   で修正パネル表示]         │  (黄色 ⚠ 推測あり)      │
│                             │                         │
└─────────────────────────────────────────────────────────┘
│ [修正パネル（Step選択時に表示）]                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ Step 2: M6 タップ穴 #1 - 修正          [✕ 閉じる]   ││
│ │ ──────────────────────────────────────────────────  ││
│ │ 【パラメータUI編集モード】                              ││
│ │ designation: [M6 ▼]  drill_diameter: [5.0 mm]      ││
│ │ tap_depth:   [12.0 mm]  position: (25.0, 15.0) mm ││
│ │                                          [確認] [キャンセル]  ││
│ │ ───────────────────────────────────────────────────  ││
│ │ 又は 【自然言語修正モード】                              ││
│ │ チャット入力: 「この穴を直径8mmに変更」 [送信]        ││
│ │                                                    ││
│ │ 😊 AI 応答:                                         ││
│ │ 「Step 2 の直径を 8mm に変更しました。               ││
│ │  Step 3 も同じ M6 です。こちらも同様に変更しますか？」  ││
│ │  [Yes - 両方変更] [No - Step 2だけ]  [修正キャンセル]  ││
│ └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

**UI コンポーネント:**
- `<BuildPlanStepper>`: ステップ一覧表示・進捗インジケータ
- `<StepParameterEditor>`: パラメータ UI 編集インターフェース
- `<StepModificationChat>`: 自然言語修正チャット
- `<BuildPlanProgressOverlay>`: 3D プレビュー上の実行進捗表示（ステップバイステップ）
- `<ConfidenceIndicator>`: 信頼度表示（参数ごと）
- `<ModificationSummary>`: 修正確認（AI が提案した変更内容）

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
