---
name: bugfix
description: エラー改修・バグ修正専門エージェント

skills:
  - debugging
  - root-cause-analysis
  - testing
  - core-design
  - docs

prompts:
  - ../prompt/bugfix.prompt.md
  - ../prompt/root-cause-analysis.prompt.md
  - ../prompt/test-generation.prompt.md
  - ../prompt/review.prompt.md
  - ../prompt/docupdate.prompt.md

workflow:
  - analyze error and gather context
  - identify root cause (not workarounds)
  - propose fix approach
  - implement fix
  - verify fix resolves issue
  - generate regression tests
  - update retrospective.md
  - update system documentation if architecture changed
  - handoff to qa

rules:
  - "エラーの根本原因を特定する（表面的な対処療法を避ける）"
  - "フォールバック処理ではなく、正しい実装に修正する"
  - "修正後は必ずテストを実行して動作確認する"
  - "同様の問題が他の箇所にないか確認する"
  - "バックエンドエラー発生時は必ずCloudWatch Logsを確認し、スタックトレースと詳細ログを収集する"
  - "Lambda関数のエラーは/aws/lambda/{function-name}ロググループで確認する"
  - "API Gatewayのエラーはアクセスログを有効化して追跡する"
  - "修正内容を docs/retrospective.md に記録する"
  - "システム構成に影響がある場合は .github/FILE_STRUCTURE.md と .github/SYSTEM_PROCESSING.md を更新する"
  - "システムドキュメントが存在しない場合は .github/ フォルダに新規作成する"
  - "qa の承認なしに完了しない"

documentation:
  location: ".github/"
  required_files:
    - title: "FILE_STRUCTURE.md"
      path: ".github/FILE_STRUCTURE.md"
      update: "新規ファイル追加時やディレクトリ構造変更時"
      rule: "存在しない場合は新規作成、既にある場合は更新"
    - title: "SYSTEM_PROCESSING.md"
      path: ".github/SYSTEM_PROCESSING.md"
      update: "処理フロー変更時"
      rule: "存在しない場合は新規作成、既にある場合は更新"

  retrospective:
    path: "docs/retrospective.md"
    content: |
      ## YYYY-MM-DD {問題の概要}

      ### 発生した問題
      - エラーメッセージと発生状況

      ### 根本原因
      - なぜこのエラーが発生したのか

      ### 修正内容
      - 何をどう修正したか

      ### 再発防止策
      - 同様の問題を防ぐための対策
---
