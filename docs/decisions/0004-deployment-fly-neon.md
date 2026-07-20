# ADR-0004: Deploy to Fly.io + Neon

Status: Accepted

## Context

The system needs a long-lived Discord gateway websocket connection plus an
always-running worker draining a job queue — both rule out serverless
platforms (Vercel/Netlify-style), which spin functions up per-request rather
than running persistent processes. The system otherwise wants to stay a
single small deployable: one web process, one bot process, one worker
process, one Postgres database with the pgvector extension.

## Decision

- **App platform: Fly.io.** Runs arbitrary long-lived containers, supports
  declaring multiple process types (`web`, `bot`, `worker`) from one
  `fly.toml`, has a free/cheap tier suitable for a portfolio project's real
  traffic level.
- **Database: Neon.** Managed serverless Postgres with pgvector support on
  the free tier, scales to zero when idle so cost stays near-zero without
  self-hosting/operating Postgres.
- **Queue: Postgres-native**, via `SELECT ... FOR UPDATE SKIP LOCKED` between
  pipeline stages. No separate broker (Redis/Celery) for v1 — unnecessary
  infra at this scale.
- Secrets (Discord bot token, GitHub App private key, LLM API key, Neon
  connection string) via Fly's secrets manager, never committed to the repo.

## Consequences

- Entire runtime is: one Fly app (3 process types) + one Neon database. No
  Kubernetes, no message broker, no separate frontend host.
- `git push` / `fly deploy` is the whole deploy story.
- If worker throughput ever becomes a real bottleneck, revisit the
  Postgres-native queue — not expected at this project's scale.
