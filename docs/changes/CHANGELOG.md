# Changelog

All notable changes to this project are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added (Phase 5, piece 2 — reconciliation engine, tier-b)
- `Decision` gains a `reconciliation` JSON column (migration
  `0006_decision_reconciliation`), matching SPEC.md §6's exact shape
  (`state`, `related_code`, `related_docs`, `notes`).
- `app/pipeline/reconciliation.py` — `find_related_repo_documents` retrieves
  `RepoDocument` rows above `settings.reconciliation_similarity_threshold`
  (cosine similarity scored in Python, same pattern as Stage 0/1/3);
  `reconcile_decision` reuses the decision's existing `statement_embedding`
  (computed at Stage 2 extraction time, no redundant embedding call), splits
  results into `related_code`/`related_docs` by `RepoDocument.kind`,
  formats each as `path#anchor`, caps each list at `settings.
  reconciliation_max_related`, and always writes `state="unverified"` —
  tier-a (concrete contradiction detection, the only path to
  `"consistent"`/`"contradiction"`) is Phase 6 scope, so this piece never
  emits those states. No LLM call: tier-b is pure embedding retrieval, no
  `SYSTEM_PROMPT`/schema/provider dispatch needed. Returns `None` without
  modifying the decision when it has no `scope`, no `statement_embedding`,
  or the project has zero `RepoDocument` rows (repo not connected/synced).
- `app/config.py` / `.env.example` — `reconciliation_similarity_threshold`
  (0.35 — lower than Stage 3's 0.5 since decision statements and code/doc
  content are more semantically distant than two decision statements),
  `reconciliation_max_related` (5).
- `app/worker/main.py` — `run_reconciliation` added to the poll loop, called
  right after `run_supersession` on every batch of newly-extracted
  decisions.
- `tests/test_reconciliation.py` — 7 tests: threshold filtering, project
  scoping, the three no-op edge cases (no scope, no statement embedding, no
  synced `RepoDocument` rows), correct `related_code`/`related_docs`
  splitting with `path#anchor` formatting, and the max-related cap.
- Verified end-to-end against real data (not just unit tests): ran
  `reconcile_decision` against two decisions and the real 236-row
  `RepoDocument` index from the actual ArborDocs repo (indexed during
  piece 1's verification). A decision about the worker poll loop correctly
  surfaced `app/worker/main.py#run_forever`/`#poll_once` and
  `docs/ARCHITECTURE.md#job-queue`/`#processes`; a decision about switching
  the extraction LLM provider correctly surfaced
  `app/pipeline/extraction.py#extract_decision` and the matching SPEC.md/
  CHANGELOG.md sections — confirming the embedding-similarity retrieval
  surfaces semantically relevant content, not noise. Full test suite (48
  tests) and `ruff check`/`ruff format --check` both clean.

### Added (Phase 5, piece 1 — GitHub content ingestion)
- New unified `RepoDocument` table (migration `0005_github_content_index`):
  one row per doc section or code symbol, distinguished by a `kind` column
  (`doc_section`/`code_symbol`) rather than two separate tables, since both
  are "a chunk of repo content with an embedding" that reconciliation needs
  to query together. `GitHubInstallation` gains a nullable `last_synced_at`
  timestamp.
- `app/ingestion/github/client.py` — `GitHubAppClient` gains
  `get_repo_tree(installation_id, repo_full_name)` (recursive Git Trees API,
  one call for the whole file listing) and
  `get_file_content(installation_id, repo_full_name, path)` (Contents API,
  base64-decoded), following the client's existing style exactly (short-lived
  `httpx.AsyncClient()` per call, installation-token auth).
- `app/pipeline/github_index.py` — `parse_doc_sections` splits a markdown
  file into sections by heading with GitHub-style anchor slugs;
  `parse_code_symbols` walks a Python file's stdlib `ast.parse()` tree for
  top-level functions/classes and class methods (dotted names for methods,
  e.g. `Bar.method_a`); `sync_repo_index` orchestrates listing the installed
  repo's tree, fetching markdown/`.py` files under configurable size/count
  caps, parsing, embedding each chunk (`get_embedder()`), and replacing the
  project's `RepoDocument` rows wholesale on resync.
- `app/config.py` / `.env.example` — `github_sync_interval_seconds` (3600),
  `github_sync_max_file_size_bytes` (200,000), `github_sync_max_files` (500).
- `app/worker/main.py` — `run_github_sync` added to the existing poll loop,
  gated per-`GitHubInstallation` by `last_synced_at` vs. the configured
  interval rather than a separate process/schedule.
- `tests/test_github_index.py` — 8 tests: heading-based doc splitting +
  anchors, headingless-file edge case, function/class/method symbol
  extraction, invalid-Python edge case, `sync_repo_index` creating documents
  from a fake GitHub client + fake embedder, size-cap filtering, resync
  replacing rather than duplicating rows, and the no-installation-attached
  edge case.
- Verified end-to-end against the real ArborDocs GitHub repo via a live
  GitHub App installation (`installation_id=148287703`,
  `RujulP14/arbordocs`) — not just unit tests: `sync_repo_index` produced
  236 real `RepoDocument` rows (70 doc sections, 166 code symbols) across
  every `.md`/`.py` file in the repo. Spot-checked anchors match expected
  format exactly, e.g.
  `docs/SPEC.md#5-the-decision-extractor-the-make-or-break-component` and
  `app/pipeline/extraction.py#extract_decision` (lines 238-300). Full test
  suite (41 tests) and `ruff check`/`ruff format --check` both clean.

### Added (Phase 4, Stage 3 implementation)
- `Decision` gains `statement_embedding`, `supersedes`, `superseded_by`
  columns (migration `0004_supersession_tracking`) — `status` is no longer
  hardcoded to `"active"`; Stage 3 can now transition it to `"superseded"`.
- `app/pipeline/supersession.py` — Stage 3: for each newly-extracted
  decision, `find_similar_active_decisions` retrieves existing active
  decisions in the same project above `settings.
  supersession_similarity_threshold` (cosine similarity over
  `statement_embedding`, scored in Python — same pattern as Stage 0/1,
  since pgvector's DB-side ops don't work against the in-memory sqlite used
  by tests). `classify_relationship` then LLM-classifies the relationship
  to each retrieved candidate (`unrelated`/`amendment`/`reversal`/
  `duplicate`) and, for `reversal`/`duplicate`, marks the old decision
  `status="superseded"` and links `supersedes`/`superseded_by` both
  directions. Same untrusted-data prompt framing as Stage 2 (both
  decisions' statements ultimately trace back to Discord chat).
- `app/pipeline/extraction.py` — `extract_decision` now computes
  `statement_embedding` via the existing `get_embedder()` at extraction
  time, so it's ready for Stage 3 retrieval without re-embedding later.
- `app/worker/main.py` — `run_supersession` runs Stage 3 on every decision
  Stage 2 extracts, called right after `run_extraction` in `poll_once`.
- Verified end-to-end against the real Groq API: a decision reversing an
  earlier one *without naming it* ("drop offset pagination, cursor-based is
  cleaner" vs. the original "use offset-based pagination") was correctly
  classified `reversal` (confidence 0.99), with the old decision marked
  superseded and both `supersedes`/`superseded_by` links set correctly. A
  genuinely unrelated decision (an oncall rotation policy) scored below the
  similarity threshold and never reached the LLM at all, confirming the
  retrieve-then-classify cost-control design works as intended.

### Changed (Phase 4, Stage 2 prompt hardening)
- Strengthened `SYSTEM_PROMPT`'s definition of a "resolved decision" (covers
  plain agreement without ceremonial phrasing) and added 5 few-shot examples
  (written fresh, not from `eval/dataset.py`, to avoid contaminating the
  eval benchmark). Verified via `eval/compare_providers.py --full`: Groq's
  full-dataset gate accuracy improved from 22/24 to 23/24; the one
  remaining miss is a genuinely ambiguous case (decisive "let's go with X"
  phrasing on a non-technical/lunch topic).
- Hardened against prompt injection from Discord message content (fully
  attacker-controlled): `SYSTEM_PROMPT` explicitly frames the transcript as
  untrusted data, never instructions; the transcript is now wrapped in
  `<discord_transcript>` delimiters with sanitization stripping any
  attacker-smuggled closing tag; `decider` is now enum-constrained to the
  discussion unit's real participant `author_id`s (same anti-hallucination
  grounding pattern already used for `message_ids`).

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
