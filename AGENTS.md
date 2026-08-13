# ArborDocs

A knowledge layer that captures **decisions made in Discord** and reconciles
them against a **GitHub codebase** (and optional Google Drive docs). Proposed
decisions are never public until a human approves them.

## Architecture

Three processes, one shared Postgres + pgvector database (Neon in prod):

- `app/web` — FastAPI + Jinja2 + HTMX (admin UI, OAuth, review queue, portal)
- `app/ingestion` — Discord bot + GitHub App client + Google Drive client
- `app/worker` — polls Postgres job queue; runs Stage 0→1→2→3 + reconciliation
- `app/pipeline` — reconstruction, candidate filter, extraction, supersession,
  GitHub/Drive index, reconciliation, audit, Drive drafts
- `app/db` — SQLAlchemy models + async session

Processes do **not** call each other over HTTP. They coordinate through Postgres.

Deploy: Fly.io process groups (`web`, `bot`, `worker`) — see ADR-0004.

## Hard Rules

1. **No commits to `main`.** Feature work happens on a branch; open a PR to `main`.
2. **Python-only web stack.** FastAPI + Jinja2 + HTMX. No React/Next/separate frontend build (ADR-0002).
3. **Two primary data sources.** Discord (chat) + GitHub (ground truth). Drive is optional indexing/drafts. No Slack/Jira/Notion in v1 (ADR-0001).
4. **Channel-scoped ingestion.** Only explicitly attached Discord channels (and their threads) are ingested (ADR-0003).
5. **Human-in-the-loop.** Extracted decisions land as `proposed`. Never auto-publish to the portal. Never auto-write docs without an explicit apply step.
6. **Package manager.** Use `uv` exclusively. Do not create `requirements.txt`, Poetry, or pip-tools lockfiles.
7. **No secrets in git.** Platform secrets live in `.env` / Fly secrets. Project-scoped tokens live in Postgres. Never commit `.env` or real keys.
8. **Use `logging`, not `print`.** Prefer `logging.getLogger("arbordocs.…")`.
9. **ORM / Alembic for schema.** Model changes require an Alembic migration under `migrations/versions/`. Prefer SQLAlchemy over raw SQL.
10. **Tests live in `tests/`.** Mirror modules under `tests/test_*.py`. Keep eval harness under `eval/`.
11. **ADRs are append-only.** Never renumber or delete; supersede with a new ADR (same principle as product decisions).

## Where To Look

- Product thesis + schema: `docs/SPEC.md`
- Runtime flow: `docs/ARCHITECTURE.md`
- Build ADRs: `docs/decisions/`
- Phased roadmap: `docs/ROADMAP.md`
- Changelog: `docs/changes/CHANGELOG.md`
- Cursor rules: `.cursor/rules/`
- Cursor skills: `.cursor/skills/`

## Setup

```bash
uv sync
docker compose up -d
cp .env.example .env   # fill secrets
uv run alembic upgrade head
uv run python -m scripts.seed_admin --github-login <you>
sh scripts/install-hooks.sh
```

## Skills

Invoke via `/` in Cursor Agent chat, or ask the agent to apply them:

- `/alembic-migration` — add an Alembic migration + model update
- `/web-route` — add a FastAPI route + Jinja template + tests
- `/pipeline-module` — add or extend a pipeline stage
- `/architecture-decision-record` — record a build ADR
- `/test-first` — implement with a pytest red-green-refactor loop
- `/code-review` — review changes against ArborDocs constraints
- `/cleanup` — clean changed files without expanding scope
- `/explore-plan-code` — structure non-trivial implementation work
- `/pre-commit-quality-gate` — verify before commit or PR

## Common Dev Commands

```bash
uv run uvicorn app.web.main:app --reload --port 8000
uv run python -m app.ingestion.discord.bot
uv run python -m app.worker.main
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run alembic revision -m "description" --autogenerate
uv run alembic upgrade head
uv run alembic check
uv run python -m eval.harness --verbose
```
