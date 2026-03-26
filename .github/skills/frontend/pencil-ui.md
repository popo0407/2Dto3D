---
name: pencil-ui
description: Pencil使用時のUI生成制約
---

You are generating UI intended to be edited inside Pencil.

Constraints:

- Layout must be clean and flat
- Avoid deeply nested wrappers
- Avoid dynamic layout hacks
- Use consistent spacing scale (4px base)
- Do not use arbitrary Tailwind values unless necessary
- Keep structure predictable
- Prefer flex/grid over absolute positioning
- No CSS tricks that break visual editing

Component Rules:

- Each visual block should be a component
- Avoid merging unrelated UI parts
- Keep DOM shallow

Responsiveness:

- Mobile-first
- No breakpoint explosion

Accessibility required.

Return:

- Clean structured code
- No explanation
