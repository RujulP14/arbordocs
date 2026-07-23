# Changelog

All notable changes to this project are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added (Discord DM notification to the decider)
- `app/ingestion/discord/client.py` — `DiscordBotClient.send_dm(user_id,
  content)`, the client's first outbound capability (opens a DM channel via
  `POST /users/@me/channels`, sends via `POST /channels/{channel_id}/
  messages`). Raises on failure — caller decides how to handle it.
- `app/worker/main.py`'s `run_extraction` now attempts a DM to
  `decision.decider` right after logging `decision_extracted`, containing
  the statement + a link to the decision's portal page. Skipped entirely
  if `decider` is empty (no fallback to `participants`). A DM failure is
  caught, logged as `decider_notification_failed` via the audit ledger,
  and never propagates into the pipeline; success logs `decider_notified`.
- `tests/conftest.py` — new `FakeDiscordClient`/`fake_discord_client`
  fixture mirroring `FakeGroqClient`'s shape (records calls, a
  `should_fail` flag to simulate the external-failure path).
- 3 new tests in `tests/test_audit_log.py`: DM sent + `decider_notified`
  logged when `decider` is set; no DM attempted and no DM-related audit
  row when `decider` is empty; a raising DM client is caught, the pipeline
  still returns the decision normally, `decider_notification_failed` is
  logged instead.
- Verified against the real Discord API (not just unit tests): sent a
  real DM to a real Discord account (`rujul14`) and confirmed it arrived
  with the correct statement and portal link.
- Note: the portal link is only actionable for deciders who already have
  an ArborDocs account — full usefulness depends on the not-yet-built
  verified-flag signup (issue #16), but the DM ships the link now since
  it degrades gracefully (a login redirect) rather than blocking on that.

### Added (Phase 5, piece 5 — audit ledger, Phase 5 complete)
- New `AuditLogEntry` model + migration `0007_audit_log` — one unified,
  append-only table (`event_type` discriminator) rather than per-stage
  tables. `subject_type`/`subject_id` are a polymorphic reference (no FK
  constraint); `actor` is a denormalized string (`"system"` or a user's
  `github_login`) so the trail survives independent of the `User` row.
  Indexes on `(project_id, created_at)` and `(subject_type, subject_id)`.
- `app/pipeline/audit.py` — shared `log_event(db, project_id, event_type,
  subject_type, subject_id, actor="system", payload=None)` helper; caller
  owns the commit, matching every other pipeline function's shape.
- Wired into all 5 pipeline mutation points in `app/worker/main.py`:
  `close_due_units` (`unit_closed`), `run_candidate_filter`
  (`candidate_flagged`), `run_extraction` (`decision_extracted` on success,
  `decision_gated_out` on gate-out), `run_supersession`
  (`supersession_classified`, logged even for `"unrelated"` results),
  `run_reconciliation` (`reconciliation_computed`).
- Wired into all 3 human-review actions in `app/web/decisions.py`:
  `approve_decision`/`reject_decision`/`edit_decision` each capture the old
  value(s) before mutating and log with `actor=user.github_login` — the
  first record anywhere of *who* changed a decision's status.
- `app/web/portal.py`/`portal_detail.html` — the portal detail page gained
  a "History" section showing a decision's full chronological audit trail;
  no new web surface was added for this.
- `tests/test_audit_log.py` — 10 tests, one per pipeline call site,
  exercising the real worker functions end-to-end via a monkeypatched
  `async_session`. 5 more tests added to `tests/test_web_decisions.py`
  (approve/reject/edit logging) and `tests/test_web_portal.py` (history
  rendering).
- Verified end-to-end against the real local Postgres DB: ran the real
  `active` decision from piece 4 back through
  `classify_relationship`/`reconcile_decision`, producing a real
  `reconciliation_computed` row; reset it to `proposed` and approved it
  through the live web UI, producing a real `decision_approved` row with
  `actor="RujulP14"` — both render correctly, in order, on the portal's
  History section. Full test suite (78 tests) and `ruff check`/`ruff
  format --check` both clean.
- **This completes Phase 5** — every component SPEC.md §4 scopes under it
  (GitHub ingestion, reconciliation, human review, decision store +
  portal, audit ledger) is now implemented and verified.

### Added (Phase 5, piece 4 — decision store + portal)
- `app/web/portal.py` — read-only portal: `GET /projects/{id}/portal` lists
  `status="active"` decisions newest-first with optional `?type=`/`?scope=`
  query-param filters; `GET /projects/{id}/portal/{decision_id}` shows the
  full decision detail (source-message transcript, reconciliation flags,
  supersession chain) with no approve/reject/edit controls. Reuses
  `_resolve_message_url` from `app/web/decisions.py` rather than
  duplicating it.
- `app/web/deps.py` — new `require_login` dependency (any authenticated
  user, admin or not); `require_admin` refactored to compose it (login
  check, then admin check) instead of duplicating the session check.
- New templates `portal_list.html`/`portal_detail.html`, matching the
  existing card/badge/two-column conventions; `project_detail.html` gains
  a "View portal" link alongside "Review decisions".
- **[ADR-0008](../decisions/0008-portal-login-gated.md)**: the portal is
  login-gated (`require_login`), not fully public — despite SPEC.md's
  "headless" framing, no ADR had ever actually decided this. Chosen because
  it composes cleanly with the not-yet-built `verified`-flag work (#16):
  once non-admin verified users can log in, they see the portal
  automatically, no code change needed.
- `tests/test_web_portal.py` — 6 tests: active-only filtering (proposed/
  rejected/superseded decisions never appear), type/scope query filters,
  reconciliation + supersession rendering on the detail page, absence of
  any review-action controls, and an unauthenticated request redirecting
  to login.
- Verified end-to-end against the real local Postgres DB: browsed the
  portal for the project with a real `active` decision ("The team will use
  REST for the new public API.") extracted earlier this session — renders
  correctly, no approve/reject/edit controls present. Full test suite (67
  tests) and `ruff check`/`ruff format --check` both clean.

### Fixed (Stage 1 recall — real-world testing)
- `app/pipeline/candidate_filter.py` — `KEYWORD_PATTERNS` expanded from 10
  brittle exact phrases to ~55 patterns organized into 7 categories
  (let's-go-with variants, decided/agreed/settled, going-with,
  switching/moving-to, explicit decision framing, use/adopt/keep/drop,
  temporal framing). Root cause: a real Discord test ("let's **just** go
  with REST") was silently dropped because the keyword list only matched
  the exact phrase "let's go with", not natural paraphrasing.
  `EXEMPLAR_DECISIONS` expanded from 5 to 15, adding technology/framework/
  protocol-choice decision shapes that had zero coverage before (e.g.
  "We decided to go with REST instead of GraphQL").
- `app/ingestion/discord/bot.py` — `on_reaction_add` now appends the ✅
  emoji to `message_row.reactions` (previously only
  `signal_close_requested` was set on the unit, so a live reaction closed
  the discussion but stayed invisible to Stage 1's `reaction_signal`
  check — every live ✅ was silently ignored by candidate scoring).
- Verified no regression via `uv run python -m eval.harness`: F1 held at
  0.85 (precision=0.73, recall=1.00) before and after both changes.
  Verified against a real Discord conversation ("should we use REST or
  GraphQL... let's just go with REST") that previously produced zero
  Stage 1 signal — now correctly flags (`matched_keywords=["let's just go
  with"]`) and flows through Stage 2→3→reconciliation→review UI as a real
  decision.
- A related Stage 0 (discussion reconstruction) grouping gap was found
  during this same testing and filed as a separate GitHub issue — a
  non-reply message scoring just under `reconstruction_similarity_threshold`
  opened a new discussion unit instead of joining the parent conversation.
  Independent, pre-existing limitation; not fixed as part of this change.

### Added (Phase 5, piece 3 — human review UI)
- `app/web/decisions.py` — review queue (`GET /projects/{id}/decisions`,
  `status="proposed"` decisions oldest-first) and detail page (`GET
  /projects/{id}/decisions/{id}`) showing the full decision record, real
  source-message transcript (resolved from `Message.discord_message_id`,
  with a graceful placeholder for deleted/missing messages), reconciliation
  flags, and supersession links. `POST /decisions/{id}/approve|reject|edit`
  actions.
- Per ARCHITECTURE.md step 9 ("only approval flips status to active"):
  `app/pipeline/extraction.py`'s `Decision(...)` construction now writes
  `status="proposed"` instead of the previous default of `"active"` —
  `app/db/models.py`'s column default changed to match. A human must now
  approve (`"active"`) or reject (`"rejected"`, new terminal status) before
  a decision is visible to any future portal. Stage 3/reconciliation are
  unaffected (both only gate on `existing.status == "active"` for
  comparison targets, never the new decision's own status).
- New templates (`decisions_queue.html`, `decision_detail.html`) plus a
  visual overhaul of `app/web/static/style.css` and the existing templates
  (card-based sections, color-coded status/type badges, two-column sticky-
  sidebar detail layout) — same Jinja2 + HTMX server-rendered approach, no
  new frontend build step.
- `tests/test_web_decisions.py` — 10 tests via `httpx.ASGITransport` +
  `app.dependency_overrides` (the standard FastAPI test pattern, first use
  in this codebase): queue filtering by status, approve/reject/edit,
  reconciliation display (present and absent), and source-message
  rendering including the missing-message placeholder.
- Verified end-to-end against the real local Postgres DB: approved,
  rejected, and edited real decisions (including ones extracted from an
  actual Discord conversation per the Stage 1 fix above) through the live
  web UI, confirming persisted status transitions.

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
