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
- [ ] **Phase 5 — GitHub ingestion + reconciliation (tier-b first) + human
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
