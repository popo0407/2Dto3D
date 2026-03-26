---
name: data-table
description: SaaSデータテーブル（ページネーション・ソート・状態管理）
---

Create a production-ready SaaS data table.

Stack:

- React + TypeScript
- Tailwind only

Requirements:

- Sortable columns
- Pagination
- Empty state
- Loading state
- Optional row selection
- Responsive (horizontal scroll on mobile)

State:

- Controlled sorting state
- Controlled pagination state
- No global state unless required

Accessibility:

- <table> semantic usage
- Proper scope attributes
- aria-sort on sortable headers
- Keyboard accessible sorting

UX:

- Hover highlight
- Clear active sort indicator
- No layout shift during loading
- Skeleton loading allowed

Design:

- Clean SaaS
- Minimal borders
- zebra rows optional
- subtle hover background

Structure:

- DataTable
- TableHeader
- TableRow
- Pagination component

No external libraries.
No explanation.
Code only.
