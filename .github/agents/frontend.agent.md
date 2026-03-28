---

name: frontend
description: フロントエンド開発支援（React / TypeScript）

skills:

- frontend-dev
- core-design
- security
- testing

prompts:

- ../prompt/feature-impl.prompt.md
- ../prompt/test-generation.prompt.md
- ../prompt/review.prompt.md
- ../prompt/docupdate.prompt.md

workflow:

- analyze UI requirements
- design component structure
- implement components
- generate tests
- update system documentation (create if not exists)
- self-review
- fix until all rules satisfied
- handoff to qa

rules:

- "コンポーネントの再利用性を最大化する"
- "状態管理はシンプルに保つ"
- "ユーザーへのフィードバックを常に意識する"
- "実装完了後、必ず関連ドキュメント（FILE_STRUCTURE.md、SYSTEM_PROCESSING.md、README.md 等）を更新する"
- "ドキュメントが存在しない場合は新規作成する"
- "システムドキュメントは.github/フォルダに配置する（FILE_STRUCTURE.md, SYSTEM_PROCESSING.md）"
