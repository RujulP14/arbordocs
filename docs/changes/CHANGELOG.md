# Changelog

All notable changes to this project are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added (Phase 4, Stage 2 implementation)
- New `Decision` model + Alembic migration `0003_decision_extraction`: the
  Stage 2 output table (`statement`, `type`, `scope`, `rationale`, `decider`,
  `participants`, `message_ids`, `authority_tier`, `confidence`, `status`
  fixed at `"active"` for now — `supersedes`/`superseded_by`/`reconciliation`
  deferred to Stage 3/Phase 5).
- `app/pipeline/extraction.py` — Stage 2 gate+extract: one LLM call per
  `Candidate` decides `resolved: bool` and, if true, fills the decision
  schema grounded in cited `message_ids` (schema-enforced enum of the
  discussion unit's actual message ids — citing a message the model didn't
  see is a validation failure, not just a prompt request). Supports two
  interchangeable providers via `extract_decision(..., provider=...)`:
  Groq, Ollama.
- `app/worker/main.py` — `run_extraction` runs Stage 2 on every candidate
  Stage 1 flags, called right after `run_candidate_filter` in `poll_once`.
- `eval/compare_providers.py` — side-by-side comparison runner
  (`uv run python -m eval.compare_providers [--providers ...] [--full] [--verbose]`)
  over 4 curated labeled threads + 1 real Discord thread by default, or the
  full 24-thread labeled dataset with `--full` (prints a per-provider gate
  accuracy tally).
- **Provider decision: Groq (`openai/gpt-oss-120b`) is the default.**
  Initially compared against Gemini and Ollama (`qwen2.5:7b`, fully local)
  on 5 curated threads: Gemini was never verified (no working API key was
  available), Groq and Ollama both reached 5/5 correct gate decisions.
  Re-run against the full 24-thread dataset: **both landed at 22/24**, but
  with opposite failure modes — Groq's 2 misses were false positives on
  jokes with decision-like phrasing (the exact pattern Stage 2 exists to
  catch); Ollama's 2 misses were false negatives on real decisions (missed
  a ✅-confirmed decision and an explicit "the policy is X" statement), plus
  weaker extraction quality overall (occasional empty `statement`,
  citation-only `rationale`, uncalibrated `confidence` flipping between 0
  and 1, some `type` mislabeling). Ollama's initial empty-`statement` issue
  was fixed by adding a `description` to every schema field (a
  generalizable structured-output robustness improvement, not
  Ollama-specific). Groq's stronger extraction quality tipped the decision;
  Ollama remains available as a no-cost, no-API-key fallback via
  `provider="ollama"`. Gemini's code was removed entirely after the
  comparison concluded — no code, config, or dependency for it remains.

### Added (Phase 3 implementation)
- `eval/dataset.py` — 24 hand-labeled synthetic threads (technical/policy/
  process/product decisions; open-question/unresolved-proposal/provisional/
  joke/status-update/casual non-decisions) + `INTERLEAVED_GROUPS` for a
  deliberate Stage 0 multi-topic stress scenario.
- `eval/harness.py` — runs the dataset through the real Stage 0 + Stage 1
  pipeline (real embedding model) and reports decision-detection
  precision/recall/F1 via `sklearn`, plus a separate Stage 0 grouping-purity
  metric. Current numbers: precision=0.73, recall=1.00, F1=0.85 — all four
  misses are false positives on joke/casual chat with decision-like
  phrasing, which Stage 2's LLM gate (added this same session) now fixes.

### Added (Phase 2 implementation)
- Postgres schema additions (Alembic migration `0002_discussion_reconstruction`):
  `discussion_units`, `candidates` tables; `messages` gained `discussion_unit_id`
  and `embedding` (pgvector `vector(384)`, `.with_variant(JSON, "sqlite")` for
  fast in-memory tests). Migration also runs `CREATE EXTENSION IF NOT EXISTS
  vector` defensively for fresh local Postgres instances.
- `app/pipeline/embeddings.py` — lazy-loaded local `sentence-transformers`
  singleton (`all-MiniLM-L6-v2`) + cosine similarity, injectable for tests
  (ADR-0003: local embeddings for high-frequency Stage 0/1 use).
- `app/pipeline/reconstruction.py` — Stage 0: groups messages into discussion
  units via reply-chain, then temporal window + participant overlap +
  embedding similarity fallback; opens a new unit otherwise.
- `app/pipeline/candidate_filter.py` — Stage 1: flags a closed discussion
  unit as a candidate on any signal (keyword phrase, embedding similarity to
  a hardcoded exemplar-decision set, or a ✅ reaction) — tuned for recall.
- `app/worker/main.py` — polling loop (`worker` process): closes discussion
  units on inactivity timeout or reaction-requested signal, runs the
  candidate filter on each newly-closed unit.
- `app/ingestion/discord/bot.py`: `_store_message` now runs Stage 0
  reconstruction on every stored message (live and backfill); new
  `on_reaction_add` handler sets a unit's close signal on a ✅ reaction.
- New config settings (`app/config.py`), all env-overridable for Phase 3
  ablations: `embedding_model_name`, `reconstruction_inactivity_minutes`,
  `reconstruction_similarity_threshold`, `candidate_embedding_threshold`,
  `worker_poll_interval_seconds`.
- `tests/conftest.py` — shared sqlite `db_session` fixture + a deterministic
  `fake_embedder` fixture so tests never load the real model.
- Verified end-to-end against real Postgres + the real embedding model (not
  just unit tests): a synthetic 3-message decision arc ("should we use
  Postgres or MySQL?" → "Postgres has better JSON support" → "ok let's go
  with Postgres, final call" + ✅ reaction) correctly grouped into one
  discussion unit, closed via the reaction signal, and flagged as a candidate
  on all three signal types (keyword match, embedding similarity ~0.71,
  reaction). `worker` process runs locally only — not yet deployed to Fly.

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
