# Build Order / Roadmap

Mirrors [SPEC.md §10](SPEC.md#10-build-order-ship-after-phase-5). A finished
Phase 5 beats a half-built Phase 6 — do not start a phase before the prior one
is checked off.

- [x] **Phase 1 — Admin login + integrations page + Discord ingestion + storage.**
      GitHub OAuth admin login (DB-backed authorization, ADR-0006). Project
      CRUD. GitHub App install callback (store `installation_id` per project).
      Discord bot invite flow + channel picker (attach channels to a
      project). Bot connected, messages persisted with metadata (author,
      roles, channel, replies, reactions, timestamps), all rows tagged
      `project_id`. Nothing is ingested for a project until its repo/channels
      are explicitly attached (see ADR-0005). Code complete and verified
      locally (schema, web app, auth gate, template rendering); the live
      GitHub OAuth/App and Discord bot flows still need real credentials
      (register the GitHub App + Discord bot application, fill in `.env`,
      run `scripts/seed_admin.py`) before they're exercisable end-to-end.
- [x] **Phase 2 — Stage 0 + Stage 1.**
      Discussion reconstruction (`app/pipeline/reconstruction.py`, run by the
      `bot` process per-message) + cheap candidate filter (`app/pipeline/
      candidate_filter.py`, run by the `worker` process's polling loop on
      unit close). No LLM — local `sentence-transformers` embeddings only.
      New tables: `discussion_units`, `candidates`; `messages` gained
      `discussion_unit_id` + `embedding`. Verified end-to-end against real
      Postgres + the real embedding model (not just mocked tests): a 3-message
      decision arc with a ✅ reaction correctly grouped into one unit, closed
      on the reaction signal, and flagged as a candidate on all three signal
      types (keyword, embedding similarity ~0.71, reaction). `worker` runs
      locally only in this pass — not yet deployed to Fly.
- [x] **Phase 3 — Eval harness + labeled dataset.**
      Seeded synthetic dataset (`eval/dataset.py`, 24 labeled threads across
      technical/policy/process/product decisions and open-question/
      unresolved-proposal/provisional/joke/status-update/casual non-decisions)
      + harness (`eval/harness.py`, `uv run python -m eval.harness
      [--verbose]`) that runs each thread through the real Stage 0 + Stage 1
      pipeline (real embedding model, not test fakes) and reports
      decision-detection precision/recall/F1 via `sklearn`. Current numbers:
      **precision=0.73, recall=1.00, F1=0.85** — all four misses are
      false positives on jokes/casual chat using decision-like phrasing
      ("final decision: pineapple doesn't belong on pizza"), which is exactly
      the failure mode Stage 2's LLM gate (SPEC.md §8) exists to fix, not a
      Stage 1 bug. Also reports a separate Stage 0 grouping-purity metric on
      a deliberately interleaved multi-topic scenario (SPEC.md §7's
      with/without-Stage-0 ablation guidance); purity=1.00 on the harness's
      current interleaved cases, though manual testing this phase found
      accuracy can drop into the ~65-70% range on short, low-content,
      no-reply cross-topic messages — a known Stage 0 limitation, not yet
      covered by a harness case.
- [x] **Phase 4 — Stage 2 + Stage 3.**
      LLM extraction into the schema; supersession tracking. Re-run eval, add
      the supersession-classification metric.
      **Stage 2:** `app/pipeline/extraction.py` does the gate+extract call
      (SPEC.md §5) into a new `decisions` table (migration
      `0003_decision_extraction.py`), wired into the `worker`'s poll loop
      right after Stage 1 (`run_extraction` in `app/worker/main.py`).
      Supports two interchangeable providers (`extract_decision(...,
      provider=...)`) — compared side-by-side via `eval/compare_providers.py`,
      first against 5 curated threads and then the full 24-thread labeled
      dataset (`--full`). **Groq (`openai/gpt-oss-120b`)** is the default:
      23/24 correct gate decisions on the full dataset after strengthening
      the prompt's decision definition and adding few-shot examples (up from
      22/24); the one remaining miss is a genuinely ambiguous case (decisive
      "let's go with X" phrasing on a non-technical/lunch topic). **Ollama
      (`qwen2.5:7b`, fully local, no API key)** reached 22/24 with the
      opposite failure mode — false negatives on real decisions plus weaker
      extraction quality (occasional empty `statement`, citation-only
      `rationale`, uncalibrated `confidence`) — and remains available as a
      no-cost fallback via `provider="ollama"`. Gemini was scoped and
      implemented first but dropped entirely after never being verified
      end-to-end and after Groq/Ollama both proved out — no Gemini code
      remains. Hardened against prompt injection from Discord message
      content: untrusted-data framing in the system prompt, delimited
      transcript with sanitization against smuggled closing tags, and
      `decider` grounded to the discussion unit's real participants (same
      anti-hallucination pattern as `message_ids`).
      **Stage 3:** `app/pipeline/supersession.py` retrieves existing active
      decisions in the same project above `settings.
      supersession_similarity_threshold` (cosine similarity over a new
      `statement_embedding` column, computed in Python against
      `app/pipeline/embeddings.py:cosine_similarity` — same pattern as
      Stage 0/1, since pgvector's DB-side ops don't work against the
      in-memory sqlite used by tests), then LLM-classifies the relationship
      to each (`unrelated`/`amendment`/`reversal`/`duplicate`) and, for
      `reversal`/`duplicate`, marks the old decision `status="superseded"`
      and links `supersedes`/`superseded_by` both directions (migration
      `0004_supersession_tracking.py`). Wired into the worker right after
      Stage 2 (`run_supersession`). Verified end-to-end against the real
      Groq API: a decision reversing an earlier one *without naming it*
      ("drop offset pagination, cursor-based is cleaner") was correctly
      classified `reversal` (confidence 0.99) and the chain linked
      correctly both directions; a genuinely unrelated decision (an oncall
      rotation policy) correctly scored below the similarity threshold and
      never reached the LLM at all — the retrieval-then-classify
      cost-control design working as intended.
- [x] **Phase 5 — GitHub ingestion + reconciliation (tier-b first) + human
      review UI + decision store + portal + audit ledger.**
      This is the shippable v1 checkpoint.
      **Piece 1, GitHub content ingestion, done:** `app/pipeline/
      github_index.py` parses repo docs into sections (`parse_doc_sections`,
      splitting markdown by heading, GitHub-style anchor slugs) and code into
      symbols (`parse_code_symbols`, stdlib `ast` — top-level functions,
      classes, and class methods with dotted names like `Bar.method_a`) into
      a new unified `RepoDocument` table (migration
      `0005_github_content_index`; one `kind` column distinguishes
      `doc_section`/`code_symbol` rather than two separate tables).
      `GitHubAppClient` gained `get_repo_tree`/`get_file_content` (Git Trees
      + Contents APIs). `sync_repo_index` orchestrates: list the installed
      repo's tree, fetch markdown/`.py` files under configurable size/count
      caps (`github_sync_max_file_size_bytes`, `github_sync_max_files`),
      parse, embed each chunk (same `get_embedder()` singleton as Stage 0/1),
      and replace the project's `RepoDocument` rows wholesale on resync (no
      incremental diffing in v1). Wired into the existing `worker` poll loop
      (`run_github_sync`, gated by a per-installation `last_synced_at`
      timestamp vs. `github_sync_interval_seconds`, default 3600s) rather
      than a separate process. Verified end-to-end against the real
      ArborDocs GitHub repo via a live GitHub App installation (not just
      unit tests): 236 `RepoDocument` rows created (70 doc sections, 166
      code symbols) across every `.md`/`.py` file in the repo, with correct
      anchors spot-checked against known content, e.g.
      `docs/SPEC.md#5-the-decision-extractor-the-make-or-break-component`
      and `app/pipeline/extraction.py#extract_decision` (lines 238-300).
      8 unit tests in `tests/test_github_index.py` cover parsing, size-cap
      filtering, and resync-replaces-not-duplicates behavior.
      **Piece 2, reconciliation engine (tier-b), done:** `app/pipeline/
      reconciliation.py` — `find_related_repo_documents` retrieves
      `RepoDocument` rows above `settings.reconciliation_similarity_threshold`
      (Python-scored cosine similarity, same pattern as Stage 0/1/3);
      `reconcile_decision` reuses the decision's existing
      `statement_embedding` (no redundant embedding call), splits results
      into `related_code`/`related_docs` by `kind`, caps each at
      `settings.reconciliation_max_related`, and writes a `reconciliation`
      dict (`Decision` gained this JSON column, migration
      `0006_decision_reconciliation`) matching SPEC.md §6's exact shape.
      `state` is always `"unverified"` — tier-a (concrete contradiction
      detection) is Phase 6 scope, so this piece never emits
      `"consistent"`/`"contradiction"`. No LLM call: tier-b is pure
      embedding retrieval. Wired into the worker (`run_reconciliation`,
      called after `run_supersession` in `poll_once`). Verified end-to-end
      against real data: two decisions run through `reconcile_decision`
      against the real 236-row `RepoDocument` index (from piece 1's
      verification) — a decision about the worker poll loop correctly
      surfaced `app/worker/main.py#run_forever`/`#poll_once` and
      `docs/ARCHITECTURE.md#job-queue`/`#processes`; a decision about
      switching the extraction LLM provider correctly surfaced
      `app/pipeline/extraction.py#extract_decision` and the matching
      SPEC.md/CHANGELOG.md sections. 7 unit tests in
      `tests/test_reconciliation.py` cover threshold filtering, project
      scoping, the three no-op edge cases (no scope, no embedding, no
      synced repo documents), correct code/doc splitting with anchors, and
      the max-related cap.
      **Piece 3, human review UI, done:** `app/web/decisions.py` — a review
      queue (`GET /projects/{id}/decisions`, listing `status="proposed"`
      decisions oldest-first) and detail page (`GET /projects/{id}/
      decisions/{id}`, showing full statement/scope/rationale/decider/
      participants, real source-message transcript resolved from
      `Message.discord_message_id`, reconciliation flags, and supersession
      links) with approve/reject/edit POST actions
      (`/decisions/{id}/approve|reject|edit`). Per ARCHITECTURE.md step 9
      ("only approval flips status to active"), Stage 2 extraction
      (`app/pipeline/extraction.py`) now writes `status="proposed"` instead
      of defaulting straight to `"active"` — a real behavior change, not
      just a UI addition. Stage 3/reconciliation are unaffected (they only
      gate on `existing.status == "active"` for comparison targets, never
      on the new decision's own status). Templates follow the existing
      Jinja2+HTMX server-rendered convention with a card-based, two-column
      detail layout. 10 unit tests in `tests/test_web_decisions.py` (via
      `httpx.ASGITransport` + `app.dependency_overrides`) cover queue
      filtering, approve/reject/edit, reconciliation display, and
      source-message rendering (including the deleted/missing-message
      placeholder). Verified end-to-end against the real local Postgres
      DB: approved and reviewed real decisions extracted from an actual
      Discord conversation (see the Stage 1 fix below) through the live
      web UI.
      **Stage 1 recall fix (real-world testing):** manual Discord testing
      surfaced two Stage 1 (`app/pipeline/candidate_filter.py`) defects
      causing genuinely-decided conversations to produce zero signal: (1)
      `KEYWORD_PATTERNS` was brittle to natural paraphrasing (e.g. "let's
      **just** go with X" missed the exact-phrase list) and missing entire
      phrasing families (switching-to/moving-to, decided/agreed/settled,
      etc.) — expanded from 10 to ~55 patterns across 7 categories; (2)
      `EXEMPLAR_DECISIONS` (5 entries) had no coverage for general
      technology/framework/protocol-choice decisions — expanded to 15,
      adding that shape class. Separately, `app/ingestion/discord/bot.py`'s
      `on_reaction_add` set `signal_close_requested` on the discussion unit
      but never wrote the ✅ into the message's `reactions` column, so a
      live reaction closed the unit but was invisible to Stage 1's
      `reaction_signal` check — fixed by appending the emoji to
      `message_row.reactions` in the same handler. Verified via
      `uv run python -m eval.harness`: F1 held at 0.85 (precision=0.73,
      recall=1.00) before and after — no regression. Verified against real
      Discord conversations: a "should we use REST or GraphQL... let's just
      go with REST" conversation, previously silently dropped (0 candidate
      signal), now correctly flags via the keyword fix alone
      (`matched_keywords=["let's just go with"]`) and flows all the way
      through Stage 2→3→reconciliation→review UI as a real `proposed`
      decision. A follow-up Stage 0 (discussion reconstruction) grouping
      gap was found during this same testing — tracked as a separate
      GitHub issue since it's an independent, pre-existing limitation (see
      issue link), not part of this piece.
      **Piece 4, decision store + portal, done:** `app/web/portal.py` — a
      read-only sibling of the review UI (`app/web/decisions.py`), listing
      `status="active"` decisions newest-first with optional `?type=`/
      `?scope=` query filters (SPEC.md's "searchable" requirement), plus a
      detail page reusing the exact same source-message/reconciliation/
      supersession data assembly as the review UI, minus every
      approve/reject/edit control. New `require_login` dependency
      (`app/web/deps.py`) — any authenticated user, not just `is_admin` —
      added alongside the existing `require_admin`; `require_admin` now
      composes it (login check first, then admin check) rather than
      duplicating the session check. Portal access is deliberately
      login-gated, not fully public despite SPEC.md's "headless" framing —
      recorded as [ADR-0008](decisions/0008-portal-login-gated.md), since
      no ADR had ever actually decided this and it directly affects the
      not-yet-built `verified`-flag work (issue #16). 6 unit tests in
      `tests/test_web_portal.py` cover active-only filtering, type/scope
      query filters, reconciliation/supersession rendering, absence of
      any review-action controls, and an unauthenticated request correctly
      redirecting to login. Verified end-to-end against the real local
      Postgres DB: browsed `/projects/{id}/portal` for the project with a
      real `active` decision ("The team will use REST for the new public
      API.") extracted earlier this session — confirmed it renders
      correctly with no approve/reject/edit controls anywhere on the page.
      **Piece 5, audit ledger, done — Phase 5 complete:** new unified
      `AuditLogEntry` table (migration `0007_audit_log`) — one
      `event_type`-discriminated table rather than per-stage tables,
      matching the project's established unified-schema preference
      (`Candidate`, `RepoDocument`). `subject_type`/`subject_id` are a
      polymorphic reference (no FK — the subject can be a
      `DiscussionUnit`/`Candidate`/`Decision`); `actor` is a denormalized
      string (`"system"` for pipeline-driven entries, or the acting user's
      `github_login` for human-review actions), so the trail survives
      independent of the `User` row. New shared `app/pipeline/audit.py`'s
      `log_event` helper, called from all 5 pipeline mutation points
      (`close_due_units`, `run_candidate_filter`, `run_extraction` — both
      the success and gate-out paths — `run_supersession`,
      `run_reconciliation` in `app/worker/main.py`) and all 3 human-review
      actions (`approve_decision`/`reject_decision`/`edit_decision` in
      `app/web/decisions.py`, capturing old/new values and the acting
      admin's `github_login`). The portal detail page
      (`app/web/portal.py`/`portal_detail.html`) gained a "History"
      section listing a decision's full chronological audit trail — no
      new web surface invented for this. 10 unit tests in
      `tests/test_audit_log.py` (one per pipeline call site, using a
      monkeypatched `async_session` to exercise the real worker functions
      end-to-end) plus 5 more added to `tests/test_web_decisions.py`/
      `tests/test_web_portal.py` for the human-review and history-display
      paths. Verified end-to-end against the real local Postgres DB: ran
      the real `active` decision from piece 4 back through
      `classify_relationship`/`reconcile_decision`, producing a real
      `reconciliation_computed` audit row; reset it to `proposed` and
      approved it through the live web UI, producing a real
      `decision_approved` row with `actor="RujulP14"` (the real logged-in
      GitHub identity) — both entries render correctly, in chronological
      order, on the portal's History section.
- [x] **Discord DM notification to the decider (post-Phase-5).** When
      Stage 2 extracts a decision, the person identified as
      `Decision.decider` gets a real Discord DM — "ArborDocs noted this
      decision" plus the statement and a portal link — so they find out
      immediately, before any human review. `DiscordBotClient` (`app/
      ingestion/discord/client.py`) gained `send_dm` (opens a DM channel
      via `POST /users/@me/channels`, then sends via `POST /channels/
      {channel_id}/messages`) — the client's first outbound capability;
      every prior method was read-only. Wired into `run_extraction`
      (`app/worker/main.py`), right after the existing `decision_extracted`
      audit entry: skipped entirely if `decider` is empty (no fallback to
      `participants`), and a DM failure (closed DMs, bot removed, etc.) is
      caught and logged as `decider_notification_failed` via the audit
      ledger rather than propagating into the pipeline — success logs
      `decider_notified`. The portal link is only actionable for deciders
      who already have an ArborDocs account; full usefulness is gated on
      the not-yet-built verified-flag signup (issue #16), but the DM ships
      the link regardless since it degrades gracefully (a login redirect)
      until then. 3 new unit tests in `tests/test_audit_log.py` (via a new
      `FakeDiscordClient` fixture in `tests/conftest.py`, mirroring
      `FakeGroqClient`'s shape) cover: DM sent + `decider_notified` logged
      when `decider` is set; no DM attempted and no DM-related audit row
      when `decider` is empty; a raising DM client is caught, the pipeline
      still returns the decision normally, and
      `decider_notification_failed` is logged instead. Verified against
      the real Discord API (not just unit tests): sent a real DM to a real
      Discord account, confirmed received.
- [x] **Verified-flag login gating (post-Phase-5, issue #16).** Any GitHub
      user can now attempt login — a first-ever identity gets a pending
      `User` row (`verified=False`) created instead of a bare rejection
      with nothing to show for it, and is redirected to a clear "awaiting
      approval" page instead of the old "not registered" message.
      `User` gains a `verified: bool` column (migration
      `0008_user_verified`, existing `is_admin=True` rows explicitly
      backfilled to `verified=True`). `app/web/auth.py`'s `callback`
      rewritten: creates the pending row on first sight of an unknown
      `github_login`, then gates session creation on `verified OR
      is_admin` — an existing admin approves a pending user by flipping
      `verified=True` directly in Postgres (no new admin UI, per explicit
      scope). `require_login`/`require_admin` (`app/web/deps.py`) needed
      no changes — `verified` only gates session creation at login time,
      not every subsequent request. `scripts/seed_admin.py` now sets
      `verified=True` explicitly alongside `is_admin=True`.
      [ADR-0006](decisions/0006-admin-authorization-in-db.md) updated in
      place to describe this (a refinement of the same authorization
      model, not a reversal), and corrected a pre-existing inaccuracy
      (the ADR said lookup was by email; the real code has always used
      `github_login`). 4 new tests in `tests/test_auth.py` (the project's
      first auth test file, driving the real `/auth/github/login` →
      `/callback` flow via `httpx.AsyncClient`'s cookie jar, with
      `github_app_client`'s OAuth methods monkeypatched) cover: a new
      identity creates a pending row and is denied a session; a repeat
      pending login doesn't create a duplicate row; a verified non-admin
      logs in successfully; an admin logs in successfully (regression).
      Verified against real Postgres: created a real pending row through
      the exact same code path `callback` uses, confirmed the login gate
      correctly denies it, manually verified it via direct SQL (the real
      approval mechanism), and confirmed the gate then allows it — full
      pending→verified lifecycle proven against the real database. (A
      live second-GitHub-account walkthrough of the OAuth HTTP flow itself
      wasn't independently run — no second account was available — so
      that exact path is covered by `tests/test_auth.py` rather than a
      manual browser session.)
- [x] **Discord Thread ingestion + grouping (post-Phase-5, issue #11).**
      Discord Threads were previously invisible to the pipeline entirely —
      a Thread has its own `channel.id`, distinct from the channel it was
      created in, so `_tracked_channel_ids()`/`on_message` silently dropped
      every message posted inside one. `Message` gains a
      `thread_starter_message_id` column (migration
      `0009_thread_starter_message`, mirroring `reply_to_message_id`'s
      shape exactly). `app/ingestion/discord/bot.py`'s `on_message` and
      `on_reaction_add` now resolve tracking via a Thread's `parent_id`
      instead of its own id; `_store_message` records
      `thread_starter_message_id` (a Thread's own id equals its starter
      message's id, per discord.py); `_backfill_tracked_channels` gained
      `_backfill_channel_threads` to also backfill active + archived
      thread history on bot startup, not just the parent channel's.
      `app/pipeline/reconstruction.py`'s `assign_message_to_discussion_unit`
      gained a new deterministic join check — a Thread message joins its
      starter message's discussion unit directly, bypassing the similarity
      threshold, exactly the way reply-chain already does (reply-chain
      itself needed zero changes). Plain sequential messages remain an
      explicit non-goal, unchanged — `reconstruction_similarity_threshold`
      and the participant-continuity fallback are untouched. 1 new test in
      `tests/test_reconstruction.py` (`test_thread_message_joins_starter_units_unit`,
      mirroring the existing reply-chain test) confirms the join bypasses
      similarity on deliberately dissimilar content; all 7 existing
      reconstruction tests pass unchanged (regression check). Verified via
      `eval/harness.py`: the interleaved-groups Stage 0 purity metric held
      at 1.00 — no regression, as expected since this feature never
      touches the similarity/participant fallback path. Verified against a
      real Discord Thread (not just unit tests): posted a starter message
      in a tracked channel, created a real Thread from it, and posted a
      4-message decision conversation inside — confirmed in Postgres that
      the starter message and all 4 thread messages share one
      `discussion_unit_id`, the unit closed correctly on a ✅ reaction with
      both real participants recorded, and the conversation extracted
      through the full pipeline into a real `proposed` decision ("Cache
      search results with a 5-minute TTL").
- [x] **Google Drive connection + doc indexing (issue #14, piece 1 of 2).**
      First piece of the Drive integration: connect a Google Drive folder
      to a project (OAuth per-admin) and index its Google Docs the same
      way `github_index.py` indexes a repo's docs — no LLM drafting or
      apply-to-Drive logic yet (that's piece 2). `RepoDocument` gains a
      third `kind` value, `"drive_section"`, alongside `doc_section`/
      `code_symbol` — one unified table, not a new one, matching the
      model's own design principle; both `sync_repo_index`'s and the new
      `sync_drive_index`'s resync deletes are scoped by `kind` so a Drive
      resync never touches a project's GitHub rows and vice versa. New
      `GoogleDriveInstallation` model (migration
      `0010_google_drive_installation`) stores the connecting admin's
      OAuth refresh token (Google's access tokens expire hourly, unlike
      GitHub's longer-lived installation tokens — every sync mints a
      fresh access token from it). New `app/ingestion/google/client.py`'s
      `GoogleDriveClient` (raw `httpx`, no Google SDK — matches this
      project's existing GitHub-client convention) and `app/web/
      integrations_google.py` (OAuth connect/callback/attach, mirroring
      `integrations_github.py`; the refresh token is held server-side in
      the session rather than round-tripped through a hidden form field,
      since unlike GitHub's non-secret `installation_id` it's a real
      credential).

      **Two real bugs found and fixed during live smoke testing** (not
      caught by unit tests written before real API access existed):
      (1) Drive's `files.list` only returns a folder's *direct* children —
      a real test folder had every actual Google Doc nested one level
      into subfolders, so the initial flat listing found nothing;
      `list_folder_docs` now recurses into subfolders (capped at
      `max_depth=5`, matching this project's "lightweight index" cap
      framing elsewhere). (2) A real folder ("Rujul Dudhat FTE") that
      *should* have been pickable in the connect flow was invisible,
      because it's shared with the connecting admin, not owned by them —
      Drive treats "my own folders" and "folders shared with me" as
      separate query surfaces; `list_folders` now queries both and merges
      the results, deduplicated by id. Both fixes are covered by new
      regression tests in `tests/test_google_client.py` using a fake
      `_list_folder_children`/fake `httpx.AsyncClient`, not just the
      existing higher-level fakes.

      Verified end-to-end against the real Google Drive/Docs API (not
      just unit tests): connected a real Drive folder via the live OAuth
      flow (including working through a real Google OAuth-consent-screen
      "Testing" mode / test-user gate); fetched a real shared Google Doc
      ("Trilogy Onboarding Runbook (Generic Tools)") and confirmed
      `get_doc_content`'s heading-flattening produced correct `#`/`##`
      markdown, which `parse_doc_sections` (reused as-is from
      `github_index.py`, unmodified) split into 19 real sections with
      correct GitHub-style anchors (e.g. `#how-to-login-kerio-vpn`); ran
      the real `sync_drive_index` against the actual connected
      installation and confirmed it correctly returns empty when the
      connected folder has no docs (an honest negative result, not a
      bug); confirmed via Postgres that GitHub-sourced `RepoDocument` rows
      (288 `code_symbol` + 102 `doc_section`, from the earlier GitHub
      ingestion piece) were completely undisturbed by Drive sync/resync
      operations throughout testing. 12 new unit tests across
      `tests/test_google_client.py` and `tests/test_drive_index.py`
      (including a dedicated regression test proving a Drive resync never
      deletes a project's GitHub rows).
- [x] **Google Drive draft/apply (issue #26, Drive piece 2 of 2).**
      Closes the loop from piece 1: approving a decision now drafts an LLM
      edit to the most-related Drive section and, on a second explicit
      human confirmation, writes it into the real Google Doc. New
      `DriveDraftEdit` model (migration `0011_drive_draft_edit`) — one row
      per decision, `status` `"drafted"` → `"applied"`/`"failed"`; a new
      table rather than reusing `RepoDocument`, since this is a proposal
      *about* a document, not indexed content. `RepoDocument` gains a
      `source_file_id` column (migration `0012_repo_doc_source_file_id`) —
      piece 1 only ever stored a Drive doc's display name (`path`), never
      its real Drive file id, which apply-time needs to call the Docs API;
      `sync_drive_index` now populates it per chunk.

      **Design, per explicit user choices:** retrieval reuses
      `reconciliation.py`'s `find_related_repo_documents` as-is, filtered
      to `kind="drive_section"` in a new `app/pipeline/drive_draft.py`
      (mirrors `supersession.py`'s per-module prompt/schema/dispatch
      shape, reusing only `TRANSCRIPT_TAG`/`_sanitize_for_transcript`/
      `get_groq_client`/`get_ollama_client` from `extraction.py`, per this
      codebase's established cross-module-reuse boundary). If no section
      scores above `reconciliation_similarity_threshold`, the human sees a
      manual section-picker on the decision detail page instead of a
      silent no-op. Draft generation is **inline in `approve_decision`**
      (not a separate worker stage) — wrapped in a broad `try/except` so a
      draft failure never blocks the approval itself, logged via
      `log_event(..., "drive_draft_generated", ...)`. The apply step
      **never persists character-offset indices** — Google Docs'
      `documents.batchUpdate` needs live indices into the *current*
      document, and any edit made upstream of drafting invalidates a
      stale one. `GoogleDriveClient.find_section_range` re-fetches the raw
      structured body fresh, immediately before every apply, and
      re-locates the target section by exact heading-text match, spanning
      to the next heading of equal-or-higher level (mirroring
      `parse_doc_sections`' own boundary logic against live structural
      data instead of a markdown string); returns `None` (fail closed) if
      no confident match, flipping `status="failed"` rather than guessing
      at a stale range. `apply_edit` issues one `documents.batchUpdate`
      call (`deleteContentRange` + `insertText`, atomic within a single
      request). Two new routes: `POST /decisions/{id}/drive-draft/apply`
      and `.../regenerate`; new "Drafted Google Doc edit" card on
      `decision_detail.html` (mirrors the Reconciliation card's
      conditional-render shape). OAuth scope expanded
      (`oauth_authorize_url`) to add `https://www.googleapis.com/auth/
      documents` alongside piece 1's `drive.readonly` — a real,
      user-facing migration: every already-connected installation's stored
      refresh token predates the new scope and needs reconnecting (running
      the OAuth flow again) before apply will work for it.

      **Real bug found and fixed during live smoke testing:** the first
      live "Apply to Google Doc" click returned an Internal Server Error —
      the real Docs API rejected the `deleteContentRange` call with `400
      Invalid requests[0].deleteContentRange: The range cannot include the
      newline character at the end of the segment.` `find_section_range`
      was computing a section running to end-of-document as ending at the
      body's final `endIndex`, which includes the document's terminal
      newline — a character the Docs API will never let you delete.
      Fixed by stopping one character short of the body's last `endIndex`
      in that case. Covered by 4 new regression tests in
      `tests/test_google_client.py` (including one reproducing this exact
      end-of-document case with a fake structured-body response) plus the
      pre-existing 10 in `tests/test_drive_draft.py` (draft generated and
      stored on a confident match; no-match surfaces the manual-picker
      state; regenerate replaces the draft; apply succeeds and logs
      `drive_doc_updated` with real before/after text; apply fails closed
      when `find_section_range` returns `None`) — 111 tests pass total,
      no regressions.

      Verified end-to-end against the real Google Drive/Docs API (not
      just unit tests, and not the pre-fix code path): reconnected the
      project's real Drive folder through the live OAuth flow to pick up
      the expanded write scope (confirmed via server logs that the
      callback requested both `drive.readonly` and `documents` scopes);
      added a real heading + paragraph to a real Google Doc, re-synced,
      and confirmed `source_file_id` populated correctly in Postgres;
      created a real decision ("Switch the API to cursor-based pagination
      instead of offset-based pagination") with a real
      `sentence-transformers` embedding scoring 0.63 similarity (above the
      0.35 threshold) against the doc's real indexed content; approved it
      through the live web UI, producing a real Groq-generated draft
      ("The API now uses cursor-based pagination for all list endpoints
      ...") stored in Postgres with a real `drive_draft_generated` audit
      entry; clicked Apply — after the fix above, this succeeded, flipping
      `status="applied"` and logging a real `drive_doc_updated` entry with
      full before/after text. Independently cross-checked via a **fresh**
      `documents.get` call (not the same response the apply path used):
      the live Google Doc's actual content now reads exactly the applied
      draft text — confirmed outside the application's own write path.
      Cleaned up the smoke-test decision/candidate/discussion-unit rows
      from the dev database afterward; left the doc's edited (correct,
      harmless) content in place.
- [ ] **Phase 6 (stretch) — Tier-a concrete contradiction detection; Slack
      adapter; query bot (RAG over approved decisions with citations);
      per-domain configs reframed as "specialist agents."**

## Risk checkpoints (don't skip)

- **After Phase 1:** confirm project-scope config actually prevents
  cross-project bleed (a channel/repo attached to project A must never leak
  into project B's discussion reconstruction or reconciliation) before
  backfilling history at scale.
- **Before Phase 4:** Phase 3's eval numbers on Stage 0/1 should look
  reasonable. If candidate-filter recall is poor here, fix it before building
  Stage 2/3 on top of it.
- **Phase 3 dataset sourcing:** decide early where labeled discussions come
  from (public Discord export vs. seeded synthetic threads) — this is
  historically the slowest part of the whole build, not the code.
