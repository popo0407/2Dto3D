# 🚀 AI 開発エージェント向けシステム設計・開発憲章

## ⭐ 最重要事項

### コーディング前の思考プロセス
1. **不明点は即座に明確化**: 勝手な判断・推測でコーディング開始しない。複数の実装方法がある場合は選択肢を提示
2. **シンプルさ優先**: 要求されていない機能は追加しない。過度な抽象化・複雑な構造を避け、最小限のコードを書く
3. **外科手術のような修正**: 必要な箇所だけ触る。既存スタイルに適応し、自分の修正に直結しないコードに触らない
4. **ゴール主導の実行**: 成功基準を明確にし、検証可能な形でタスク完了を確認する（テスト・実行検証などでループ確立）

### 開発ルール
- .github/agents/.agent.md に記載されたルールを厳守する。特に、ドキュメントの作成・更新は必ず実施する
- 分析や戦略立案、コード内の記載などの内部思考プロセスは英語で行い、実装計画・説明・ドキュメントはすべて日本語で提供する。
- 機能追加時やエラー発生時などAI が独断でフォールバック処理を追加しない。
- タスク完了時には、この憲章に違反していないかを自己確認し、README.md を更新した上で GitHub への`add`・`commit`・`push`を行う。
- タスク完了後は、問題の原因・改善策・再発防止策を整理し、`docs/retrospective.md`に記録する。

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
| **docs/SKILL.md**                          | ドキュメント作成・更新時、README.md変更時、API仕様書・技術仕様書作成時、SKILL.md記載ルール確認時             |
| **aws-cdk/SKILL.md**                       | AWS CDK（Infrastructure as Code）デプロイ時、Lambda関数実装時、ECS Fargate設定時                         |
| **aws-operations/SKILL.md**                | AWS運用・コスト最適化戦略検討時、セキュリティ・IAM権限設定時、本番環境デプロイ前                     |
| **backend/SKILL.md**                       | Python バックエンド実装時、API エンドポイント設計時、DynamoDB操作実装時                                       |
| **git/SKILL.md**                           | 機能ブランチ作成時、コミット実行時、Pull Request作成時、タスク完了後のGit操作時、**改善点・技術的負債検出時** |

---

##  タスク実行フロー

1. **タスク受け取り** → 不明点があれば確認を求める
2. **適切なスキルを確認** → 上の表から選択・参照
3. **規約に従いコード実装** → ドキュメント作成
4. **git/SKILL.md に従い Git 操作実行** → feature branch → commit → push → PR
5. **README.md 更新** → `docs/retrospective.md` に記録

---

## ✅ タスク完了前チェックリスト

- [ ] README.md と `.github/skills/*.md` を更新した？
- [ ] git/SKILL.md に従い Git 操作を完了した？（branch → commit → push → PR）
- [ ] `docs/retrospective.md` に記録した？
