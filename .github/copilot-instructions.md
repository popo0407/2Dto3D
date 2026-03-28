# 🚀 AI 開発エージェント向けシステム設計・開発憲章

## ⭐ 最重要事項

- .github/agents/.agent.md に記載されたルールを厳守する。特に、ドキュメントの作成・更新は必ず実施する
- 分析や戦略立案などの内部思考プロセスは英語で行い、実装計画・説明・ドキュメントはすべて日本語で提供する。
- エラーまたはデータが期待値と異なる場合は AI が独断でフォールバック処理を追加せず、根本原因の対策に努め、不可能であった場合ユーザーと協議すること。
- 不明点がある場合は、作業を開始する前に必ず明確化を求めること。
- タスク完了時には、この憲章に違反していないかを自己確認し、README.md を更新した上で GitHub への`add`・`commit`・`push`を行う。
- タスク完了後は、問題の原因・改善策・再発防止策を整理し、`docs/retrospective.md`に記録する。
- 関連するskillsに不具合対応で得られた知見の内、今後の開発時に役立つ情報を追記する。本システム特有の問題は記載しない。
- **SKILL.md 記載ルール:**
  - 汎用的な技術知識・ベストプラクティスのみ記載（他プロジェクトでも役立つ内容）
  - 本システム固有のファイル名・スクリプト名は記載しない
  - 具体的なコードは間違いやすい内容でない限り記載しない
- 開発中に以下の改善点を見つけた場合、必ず GitHub Issue として登録すること：
  - 🐛 関係のないバグ（現在のタスクとは無関係）
  - ✨ 必要そうだが現在のスコープ外の機能
  - 🗑️ 後方互換のために残っているが不要かもしれないコード
  - 🔧 リファクタリング対象として識別されたコード
  - 🚀 長期的には別の実装方法に変更すべき機能
- Reactで作成するすべてのUIはPencil編集前提で生成する

---

## 📚 スキルの確認タイミング

各 `.github/skills/*/SKILL.md` ファイルは以下のときに確認・参照する。

| スキル                                     | 確認タイミング                                                                                                |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| **core-design.md**                         | 新規システム設計時、大規模リファクタリング検討時、パフォーマンス改善時                                        |
| **security.md**                            | API設計・実装時、ユーザー入力処理時、認証・認可実装時、本番デプロイ前                                         |
| **testing.md**                             | ユニットテスト作成時、統合テスト追加時、バグ修正時、リリース前品質確認時、**E2Eテスト作成時**                 |
| **frontend/SKILL.md**                      | React/TypeScriptコンポーネント実装時、UI修正時、本番リリース前のアクセシビリティチェック時                    |
| **frontend/foundation-ui.md**              | SaaS UI要素実装時、デザインシステム構築時                                                                     |
| **frontend/saas-layout.md**                | SaaS共通レイアウト実装時、管理画面構築時                                                                      |
| **frontend/auth-ui.md**                    | 認証画面実装時                                                                                                |
| **frontend/chat-ui.md**                    | AIチャットUI実装時                                                                                            |
| **frontend/settings-ui.md**                | 設定画面実装時                                                                                                |
| **frontend/form-builder.md**               | フォーム構築・バリデーション・エラー処理実装時                                                                |
| **frontend/data-table.md**                 | データテーブル（ページネーション・ソート）実装時                                                              |
| **frontend/refactor-clean.md**             | 生成コードを本番品質に改善する際のリファクタリング基準                                                        |
| **frontend/animation-microinteraction.md** | Serendie思想に基づくマイクロインタラクション実装時                                                            |
| **frontend/state-patterns.md**             | 状態管理・複雑な状態設計時                                                                                    |
| **frontend/pencil-ui.md**                  | Pencil使用時のUI生成・編集時                                                                                  |
| **refactoring.md**                         | 既存コード保守性向上時、技術的負債解消時、パフォーマンスチューニング時                                        |
| **aws-cdk/SKILL.md**                       | AWS CDK（Infrastructure as Code）デプロイ時、Lambda関数実装時、ECS Fargate設定時                         |
| **aws-operations/SKILL.md**                | AWS運用・コスト最適化戦略検討時、セキュリティ・IAM権限設定時、本番環境デプロイ前                     |
| **backend/SKILL.md**                       | Python バックエンド実装時、API エンドポイント設計時、DynamoDB操作実装時                                       |
| **git/SKILL.md**                           | 機能ブランチ作成時、コミット実行時、Pull Request作成時、タスク完了後のGit操作時、**改善点・技術的負債検出時** |

---

## 🎭 PlayWright MCP（E2Eテスト自動化）

GitHub CopilotがPlayWrightを使用したE2Eテストを自動生成・支援することが可能になりました。

### 対応機能

- **ユーザーインタラクションテスト生成：** ログイン、フォーム操作、ナビゲーションなどのE2Eテストを自動生成
- **Copilot Chat統合：** Copilot Chatでテストコード生成、テスト実行コマンド提案
- **テストデバッグ支援：** 失敗したテストの原因分析と修正提案

### 使用方法

1. `npm run e2e` でテスト実行
2. `npm run e2e:ui` でテストUIで対話的に実行
3. Copilot ChatでPlayWrightのテストコード生成を依頼（例：「ログイン機能のE2EテストをPlayWrightで書いて」）

---

## 🎯 タスク実行フロー

1. **タスク受け取り** → 不明点があれば確認を求める
2. **適切なスキルを確認** → 上の表から選択・参照
3. **規約に従いコード実装** → ドキュメント作成
4. **git/SKILL.md に従い Git 操作実行** → feature branch → commit → push → PR
5. **README.md 更新** → `docs/retrospective.md` に記録

---

## ✅ タスク完了前チェックリスト

- [ ] 各スキル要件に違反していないか？
- [ ] アクセシビリティ（frontend）/ セキュリティ（backend）対応済み？
- [ ] README.md と `.github/skills/*.md` を更新した？
- [ ] git/SKILL.md に従い Git 操作を完了した？（branch → commit → push → PR）
- [ ] `docs/retrospective.md` に記録した？
