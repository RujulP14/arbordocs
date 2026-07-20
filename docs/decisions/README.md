# Architecture Decision Records

Lightweight ADRs for decisions made about *how ArborDocs itself is built* —
not to be confused with the product's own "decision record" concept (§6 of
[SPEC.md](../SPEC.md)), which is what the running system extracts from
Discord. These are meta: decisions about the project, made by its author.

Format: Context / Decision / Consequences. Numbered sequentially, never
renumbered or deleted — if a decision is reversed, add a new ADR that
supersedes it and note that link in both files (the same supersession
principle the product itself implements).

| # | Title | Status |
|---|-------|--------|
| [0001](0001-two-data-sources-only.md) | Two data sources only: Discord + GitHub | Accepted |
| [0002](0002-python-only-web-stack.md) | Python-only web stack: FastAPI + Jinja2 + HTMX | Accepted |
| [0003](0003-channel-scoped-ingestion.md) | Channel-scoped ingestion as the noise/scope control | Accepted |
| [0004](0004-deployment-fly-neon.md) | Deploy to Fly.io + Neon | Accepted |
| [0005](0005-multi-tenant-projects.md) | Multi-tenant model: single admin, per-project GitHub + Discord integrations | Accepted |
| [0006](0006-admin-authorization-in-db.md) | Admin authorization lives in the DB, not an env allowlist | Accepted |
| [0007](0007-single-github-app-for-login-and-repos.md) | One GitHub App for both admin login and repo access | Accepted |
