# Changelog

All notable changes to this project are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added (Phase 1 implementation)
- Postgres schema (SQLAlchemy models + Alembic migration `0001_initial`):
  `users`, `projects`, `github_installations`, `discord_guilds`,
  `project_channels`, `messages` — every project-scoped table carries
  `project_id`.
- `scripts/seed_admin.py` — one-time first-admin bootstrap (ADR-0006).
- `app/ingestion/github/client.py` — `GitHubAppClient`: App JWT signing,
  OAuth login exchange, installation token exchange, repo listing.
- `app/ingestion/discord/client.py` — `DiscordBotClient`: bot invite URL,
  guild/channel listing via REST.
- `app/ingestion/discord/bot.py` — `discord.py` gateway client: backfills
  and ingests messages only for channels attached to a project via
  `project_channels`; untracked channels are never written (ADR-0003/0005).
- FastAPI web app (`app/web/`): GitHub OAuth login/callback/logout, project
  CRUD, GitHub repo connect + picker, Discord channel connect + picker —
  server-rendered with Jinja2 + HTMX, no separate frontend build (ADR-0002).
- `docker-compose.yml` (pgvector/pgvector:pg16 for local dev), `pyproject.toml`
  (uv-managed), unit tests for JWT signing and schema/project-scoping.
- Verified locally: migration applies cleanly, seed script creates an admin,
  full login → dashboard → create project → connect-repo/connect-discord page
  flow renders correctly against a real Postgres instance. Live GitHub/Discord
  OAuth exchanges are not yet exercised — they require registering the actual
  GitHub App and Discord bot application and filling in `.env`.

### Changed
- Admin authorization moved from an `ADMIN_GITHUB_LOGINS` env allowlist to a
  `users` table (`is_admin` flag) in Postgres, bootstrapped via a one-time
  seed script for the first admin (ADR-0006).
- Collapsed to a single GitHub App registration used for both admin login
  (OAuth identity) and per-project repo access (install flow) — removed
  separate `GITHUB_OAUTH_CLIENT_ID/SECRET` (ADR-0007).
- Pivoted from single-tenant (one Discord server + one hardcoded repo via
  `.env`) to multi-tenant: one admin login (GitHub OAuth) registers multiple
  **projects**, each with its own GitHub repo (via a shared GitHub App
  installation) and its own set of Discord channels (via a shared bot's OAuth
  invite flow), managed through an integrations page. See ADR-0005.
- Updated ADR-0003, SPEC.md, ARCHITECTURE.md, ROADMAP.md, and `.env.example`
  to express scope as `project_id` instead of a flat channel/product tag.

### Added
- Repo scaffolding: `app/` package layout (ingestion, pipeline, web, worker,
  db), `docs/` folder (spec, architecture, decisions, roadmap, changelog).
- Project spec captured at `docs/SPEC.md`.
- Runtime flow documented at `docs/ARCHITECTURE.md`.
- Architecture decisions recorded: two-source scope (ADR-0001), Python-only
  web stack (ADR-0002), channel-scoped ingestion (ADR-0003), Fly.io + Neon
  deployment (ADR-0004), multi-tenant project model (ADR-0005).
