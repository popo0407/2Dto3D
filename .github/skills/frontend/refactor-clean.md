---
name: refactor-clean
description: 生成コードを本番品質に改善
---

Review and refactor the provided code for production quality.

Focus on:

Architecture:

- Single responsibility components
- Proper feature isolation
- Extract reusable UI primitives
- Remove duplication

Code Quality:

- No unnecessary wrapper divs
- Strong typing
- Remove magic numbers
- Remove unused variables
- Proper dependency arrays

Tailwind:

- Remove redundant classes
- Consistent spacing scale (4px base)
- Replace arbitrary values if unnecessary

Accessibility:

- aria attributes verified
- Keyboard support ensured
- Color contrast safe

Performance:

- Memoize where meaningful
- Avoid unnecessary re-renders

Do not:

- Change business logic
- Introduce new libraries

Return full updated code.
No explanation.
