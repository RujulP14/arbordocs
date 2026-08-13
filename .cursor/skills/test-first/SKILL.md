---
name: test-first
description: Implements ArborDocs features and bug fixes with a red-green-refactor loop using pytest. Use when behavior can be expressed as a focused unit or integration test.
---

# Test-First Development

1. Define inputs, expected behavior, edge cases, and failure behavior.
2. Add a focused test under `tests/test_*.py`, mirroring the affected module.
3. Run it and confirm it fails for the intended reason:

```bash
uv run pytest tests/<test_file>.py -q
```

4. Implement the smallest correct change.
5. Re-run the focused test until green.
6. Refactor without changing behavior, then run relevant neighboring tests.

Tests should verify outcomes rather than implementation details. Prefer real
domain behavior over broad mocking. Async DB and HTTP paths should use async
tests; `pytest-asyncio` already uses automatic mode.
