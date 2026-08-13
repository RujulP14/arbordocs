---
name: pre-commit-quality-gate
description: Runs ArborDocs branch-scoped cleanup, review, tests, migration checks, and security checks before commit or PR creation.
---

# Pre-Commit Quality Gate

1. Confirm the current branch is not `main` or `master`.
2. Determine the requested diff scope and inspect all staged/uncommitted files.
3. Apply `.cursor/skills/code-review/SKILL.md`.
4. Apply `.cursor/skills/cleanup/SKILL.md` only to changed files.
5. Check staged paths for `.env`, keys, tokens, coverage artifacts, and unintended generated files.
6. Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run alembic check
uv run pytest -q
```

7. If available, run:

```bash
gitleaks protect --staged --config .gitleaks.toml --verbose
```

8. Fix failures in scope and rerun affected checks. Do not report ready until
required checks pass or the user explicitly accepts a documented exception.

Report review findings, cleanup applied, each check's result, and residual
risks. Do not commit or push unless the user separately requests it.
