---
name: cleanup
description: Cleans ArborDocs feature changes without expanding scope. Use after implementation or review to remove dead code, debug output, stale comments, and accidental complexity.
---

# Cleanup

Scope cleanup to files changed for the current task unless the user requests a
broader refactor.

- Remove dead code, unused imports, stale TODO/HACK markers, and temporary instrumentation.
- Replace accidental `print` calls with intentional ArborDocs logging or remove them.
- Keep useful operational and error logs; never log secrets.
- Collapse abstractions that have only one use and add no meaningful boundary.
- Preserve comments that explain non-obvious domain or security constraints.
- Do not mix formatting or unrelated refactors into the feature.

Finish with focused tests plus:

```bash
uv run ruff check <changed-python-files>
uv run ruff format --check <changed-python-files>
```
