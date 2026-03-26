---
name: state-patterns
description: SaaS向け状態管理パターン定義
---

You are designing state management for a SaaS React application.

Stack:

- React + TypeScript
- Feature-based architecture
- No unnecessary global state

Core Principles:

1. Local First

- UI state stays inside component
- Feature state stays inside feature
- Global state only when truly shared

2. Explicit State Modeling
   Avoid boolean explosion.

Instead of:
isLoading, isError, isSuccess

Use:
type Status = "idle" | "loading" | "success" | "error"

3. Derived State

- Never duplicate derivable data
- Use useMemo for computed values

4. Async Pattern
   Use structured async state:

{
status: "idle" | "loading" | "success" | "error",
data: T | null,
error: string | null
}

5. Form State

- Controlled inputs
- Validation state separate from data state

6. Chat State (for AI feature)
   Structure:

{
messages: Message[]
isStreaming: boolean
error: string | null
}

Message type:
{
id: string
role: "user" | "assistant"
content: string
createdAt: number
}

7. Settings State

- Dirty flag
- Save status
- Local draft before commit

8. Performance

- Memoize large lists
- Avoid prop drilling across features
- Extract context only when required

9. No Overengineering

- No state library unless complexity demands it
- Avoid premature abstraction

Return:

- Example state structure if needed
- No external libraries
- TypeScript strict
