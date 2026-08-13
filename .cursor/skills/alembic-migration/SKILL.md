---
name: alembic-migration
description: Creates and verifies ArborDocs SQLAlchemy model and Alembic schema changes. Use when adding tables, columns, indexes, constraints, or data backfills.
---

# Alembic Migration

1. Read `app/db/models.py`, `migrations/env.py`, and the latest revision.
2. Update the SQLAlchemy model first.
3. Generate with `uv run alembic revision -m "<description>" --autogenerate`.
4. Rename the revision to the repository's `NNNN_snake_case.py` convention and keep its revision identifiers consistent.
5. Review generated operations; remove unrelated schema churn.
6. Provide a practical `downgrade()`.
7. For existing rows, design a safe backfill before adding non-null constraints.
8. Verify:

```bash
uv run alembic upgrade head
uv run alembic check
uv run pytest tests/test_models.py -q
```

Never edit an already-shipped migration. Project-scoped tables must preserve
`project_id` isolation. Do not put secrets or environment-specific values in
migrations.
