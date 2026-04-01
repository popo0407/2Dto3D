---
name: git-versioning
description: GitHub バージョン管理の手順と規約
---

## GitHub バージョン管理の原則

AIエージェントがシステム変更を完了した後、Git を通じて一元管理し、人間による確認・マージを可能にする。

---

## 1. GitHub Issue 管理

### 1.1 Issue→ブランチ→PR のフロー

```
Issue #123 を受け取る
  ↓
feature/issue-123-description ブランチ作成
  ↓
コード実装 + "Closes #123" をコミットメッセージに記載
  ↓
PR 作成 + PR説明に "Closes #123" を記載
  ↓
マージ時に Issue は自動クローズ
```

### 1.3 Issue リンクキーワード（自動クローズ）

| キーワード   | 用途                       | 例                |
| ------------ | -------------------------- | ----------------- |
| `Closes`     | バグ/機能の完了            | `Closes #123`     |
| `Fixes`      | バグ修正                   | `Fixes #456`      |
| `Resolves`   | 問題解決                   | `Resolves #789`   |
| `Related to` | 参照のみ（クローズしない） | `Related to #100` |

### 1.4 推奨ラベル

- **Type**: `bug`, `feature`, `docs`, `refactor`, `test`
- **Priority**: `priority/critical`, `priority/high`, `priority/medium`, `priority/low`
- **Status**: `status/open`, `status/in-progress`, `status/review`, `status/done`

---

## 3. コミット規約（Conventional Commits）

### 3.1 コミットメッセージフォーマット

```
<type>(<scope>): <subject>

<body>

<footer>
```

### 3.2 Type の種別

| Type       | 説明                   | 例                                          |
| ---------- | ---------------------- | ------------------------------------------- |
| `feat`     | 新機能                 | `feat(auth): add cognito integration`       |
| `fix`      | バグ修正               | `fix(lambda): resolve timeout issue`        |
| `docs`     | ドキュメント           | `docs(aws): update CDK deployment guide`    |
| `style`    | コード整形（機能なし） | `style(frontend): format TypeScript files`  |
| `refactor` | リファクタリング       | `refactor(backend): extract lambda handler` |
| `perf`     | パフォーマンス改善     | `perf(api): optimize dynamodb query`        |
| `test`     | テスト追加・修正       | `test(frontend): add wcag compliance tests` |
| `chore`    | 依存関係・設定変更     | `chore(cdk): upgrade aws-cdk-lib`           |
| `ci`       | CI/CD設定変更          | `ci: add github actions workflow`           |

### 3.3 コミットメッセージ例

```
feat(cdk): implement auto-layer versioning

- Implement CDK Layer version management
- Add automatic dependency detection
- Update Lambda functions with new layer references
- Add hash-based versioning to prevent redundant builds

Closes #123
```

### 3.4 コミットの粒度

✅ **良い例**：機能ごとに分けたコミット

```
1. feat(cdk): add lambda_stack.py scaffold
2. feat(lambda): implement auth function handler
3. feat(cdk): define api gateway integration
4. test(auth): add unit tests for auth handler
```

❌ **悪い例**：まとめすぎたコミット

```
1. feat: add entire backend with tests and deployment scripts
```