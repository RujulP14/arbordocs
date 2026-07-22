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
- [ ] **Phase 4 — Stage 2 + Stage 3.**
      LLM extraction into the schema; supersession tracking. Re-run eval, add
      the supersession-classification metric.
      **Stage 2 done, Stage 3 not started.** `app/pipeline/extraction.py`
      does the gate+extract call (SPEC.md §5) into a new `decisions` table
      (migration `0003_decision_extraction.py`), wired into the `worker`'s
      poll loop right after Stage 1 (`run_extraction` in
      `app/worker/main.py`). Supports two interchangeable providers
      (`extract_decision(..., provider=...)`) — compared side-by-side via
      `eval/compare_providers.py`, first against 5 curated threads and then
      the full 24-thread labeled dataset (`--full`). **Groq
      (`openai/gpt-oss-120b`)** is the default: 22/24 correct gate decisions
      on the full dataset, misses being 2 false positives on jokes with
      decision-like phrasing (the same failure mode Stage 2 exists to fix —
      a stricter gate prompt could plausibly tighten this further).
      **Ollama (`qwen2.5:7b`, fully local, no API key)** also reached 22/24,
      but with the opposite failure mode — 2 false negatives, missing real
      decisions (one ✅-confirmed, one an explicit "the policy is X")
      — plus weaker extraction quality throughout: occasional empty
      `statement`, citation-only `rationale` (e.g. just `['thread-id-1']`
      instead of prose), uncalibrated `confidence` (flips between 0 and 1
      with no correlation to certainty), and some `type` mislabeling.
      Ollama remains available as a no-cost fallback via `provider="ollama"`.
      Gemini was scoped and implemented first but dropped entirely after
      never being verified end-to-end (no working API key was available)
      and after Groq/Ollama both proved out — no Gemini code remains.
      Stage 3 (supersession tracking) is unbuilt — no
      `supersedes`/`superseded_by` columns exist yet on `decisions`.
- [ ] **Phase 5 — GitHub ingestion + reconciliation (tier-b first) + human
      review UI + decision store + portal + audit ledger.**
      This is the shippable v1 checkpoint.
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
