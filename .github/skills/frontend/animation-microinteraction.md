---
name: animation-microinteraction
description: Serendie思想に基づくマイクロインタラクション実装
---

You are implementing UI according to Serendie Design Philosophy.

Core Serendie Principles:

1. Circulation (循環)

- Show visible connection between actions and results
- Data flow must feel alive
- Avoid isolated UI reactions

2. Co-Creation (共創)

- Lock states must feel respectful
- Use positive language (e.g., "◯◯さんが思考中")
- Avoid aggressive blocking UI

3. Inspiration (ひらめき)

- Subtle motion
- No heavy animation
- Calm but meaningful feedback

Animation Rules:

Micro-interactions:

- Slight elevation on selection
- Soft scale (1.01–1.02)
- Subtle transition (150–250ms)
- No bounce, no overshoot

Loading:

- Avoid simple spinner only
- Use abstract "weaving" or "building" visual hint
- Suggest value creation, not waiting

Lock UI:

- Glassmorphism allowed (subtle backdrop blur)
- Soft opacity overlay
- Gentle progress fill instead of countdown pressure

Accessibility:

- Animations must not exceed WCAG motion guidelines
- Respect prefers-reduced-motion
- No flashing elements

Design Constraints:

- Clean SaaS base
- Neutral base colors
- Accent color only for meaningful state
- No excessive shadows

Implementation:

- Use Tailwind transitions
- No heavy animation libraries
- Keep performance light

Return:

- Updated components
- No explanation
- Code only
