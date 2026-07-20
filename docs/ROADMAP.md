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
- [ ] **Phase 2 — Stage 0 + Stage 1.**
      Discussion reconstruction + cheap candidate filter. Output candidates to
      a console/table. No LLM yet.
- [ ] **Phase 3 — Eval harness + labeled dataset.**
      Build this early — it tells you whether later stages actually work.
      Get decision-detection F1 measurable before writing Stage 2/3.
- [ ] **Phase 4 — Stage 2 + Stage 3.**
      LLM extraction into the schema; supersession tracking. Re-run eval, add
      the supersession-classification metric.
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
