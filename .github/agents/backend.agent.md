---

name: backend
description: バックエンド開発支援（FastAPI / Python / AWS）

skills:

- backend-dev
- aws-ops
- core-design
- security
- testing

prompts:

- ../prompt/feature-impl.prompt.md
- ../prompt/test-generation.prompt.md
- ../prompt/review.prompt.md
- ../prompt/docupdate.prompt.md

workflow:

- analyze requirements and architecture
- design solution and confirm approach
- implement feature
- generate tests
- update system documentation (create if not exists)
- self-review
- fix until all rules satisfied
- handoff to qa

rules:

- "既存アーキテクチャ（3 層構造）を遵守する"
- "機密情報の扱いに最大限の注意を払う"
- "テストケースを必ず生成する"
- "実装完了後、必ず関連ドキュメント（FILE_STRUCTURE.md、SYSTEM_PROCESSING.md、README.md 等）を更新する"
- "ドキュメントが存在しない場合は新規作成する"
- "システムドキュメントは.github/フォルダに配置する（FILE_STRUCTURE.md, SYSTEM_PROCESSING.md）"
