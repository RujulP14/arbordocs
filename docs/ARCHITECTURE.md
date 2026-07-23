# Architecture — Runtime Flow

This describes how data actually moves through the running system, as decided
in planning discussion prior to build. See [SPEC.md](SPEC.md) for the full
project spec and [decisions/](decisions/) for the rationale behind each choice
below.

## Processes

Three long-running processes, one shared database:

- **web** — FastAPI app: admin login (GitHub OAuth), integrations page
  (project CRUD, GitHub App install callback, Discord invite + channel
  picker), GitHub webhook receiver, review-queue UI, public portal (all
  server-rendered via Jinja2 + HTMX).
- **bot** — discord.py gateway listener. Single process, serves every guild
  the shared bot has been invited to across all projects; routes incoming
  messages to a project via a channel-ID → project-ID lookup.
- **worker** — polling loop that drains the Postgres-backed job queue and runs
  Stage 1 → Stage 2 → Stage 3 → reconciliation, per project.
- **db** — Postgres + pgvector (hosted on Neon). Holds admin accounts,
  projects, raw messages, decision records, embeddings, job queue, and audit
  ledger — every project-scoped table carries a `project_id`.

See [decisions/0004-deployment-fly-neon.md](decisions/0004-deployment-fly-neon.md)
for why this shape and where it deploys, and
[decisions/0005-multi-tenant-projects.md](decisions/0005-multi-tenant-projects.md)
for the multi-tenant/project model.

## Onboarding (new project)

1. Admin logs in via GitHub OAuth (checked against an admin allowlist).
2. Admin creates a project (name, description).
3. Admin installs the shared GitHub App on their repo (or reuses an existing
   installation) → picks the repo → attaches it to the project.
4. Admin invites the shared Discord bot to their server (if not already
   present) → picks channels → attaches them to the project, optionally
   setting an authority tier per channel.
5. Ingestion begins for that project only — nothing is ingested before a
   channel/repo is explicitly attached.

## End-to-end pipeline

1. **Discord ingestion (continuous, event-driven).**
   Bot listens live via gateway events (`on_message`, `on_reaction_add`) for
   channels explicitly attached to a project (see
   [decisions/0005-multi-tenant-projects.md](decisions/0005-multi-tenant-projects.md))
   — including messages posted inside a Discord Thread of a tracked
   channel, resolved via the Thread's parent channel id. On startup,
   backfills history for those channels and their threads (active and
   archived). Every message is written to the raw `messages` table
   immediately, unfiltered, tagged with its `project_id`.

2. **Discussion reconstruction (per incoming message).**
   Assigns the message to a discussion unit: reply parent or Thread starter
   message if present (both deterministic, bypass the similarity
   threshold), else temporal proximity + participant overlap + embedding
   similarity to recent messages in the same channel. `project_id` is a
   hard boundary — messages in different projects never merge into the
   same unit. Units stay open and keep absorbing messages.

3. **Discussion closing.**
   A unit closes on inactivity timeout OR an explicit signal (✅ reaction,
   thread marked resolved, clear topic shift). Closing enqueues the unit for
   candidate filtering.

4. **Candidate filter (Stage 1, on close).**
   Runs over the full closed unit — keyword/pattern cues + local
   (`sentence-transformers`) embedding similarity to known-decision exemplars.
   Above threshold → enqueued for Stage 2. Tuned for recall, not precision.

5. **LLM gate + extraction (Stage 2, async worker).**
   Worker pulls a candidate off the queue, LLM gates ("real decision or just
   discussion?"), then extracts into the fixed schema (see SPEC.md §6),
   citing `message_ids`. Written to `decisions` as `status: proposed`. If a
   `decider` was identified, they're immediately sent a Discord DM noting
   the decision and linking to it — a DM failure is logged but never
   blocks the pipeline.

6. **Supersession check (Stage 3, per new decision).**
   Vector search over existing `active` decisions (API-quality embeddings —
   this step is low-frequency, so cost is fine), LLM classifies the
   relationship (`unrelated` / `amendment` / `reversal` / `duplicate`), updates
   `supersedes` / `superseded_by` links.

7. **GitHub ingestion (event-driven, independent track).**
   Webhook fires on push/PR merge for any installation of the shared GitHub
   App. Payload's `installation_id` (+ repo) is resolved to a `project_id`;
   changed docs/code are re-parsed into that project's symbol/doc-section
   index. Runs independently of the Discord track — just keeps the
   ground-truth index fresh, per project.

8. **Reconciliation (per new/changed decision).**
   Tier-a: pattern match against detectable code/doc conventions. Tier-b
   fallback: embedding similarity against the GitHub index, surfacing likely
   related files for human confirmation. Writes into the decision's
   `reconciliation` field.

9. **Human review (async, pull-based).**
   Everything from step 5 onward sits in a review queue (FastAPI + Jinja2 +
   HTMX). A human sees the decision, source links, confidence, and any
   reconciliation flags, and approves / edits / rejects. Only approval flips
   status to `active` and makes it visible in the portal.

10. **Audit ledger.**
    Every write in steps 2–9 appends an entry — detection, extraction,
    supersession link, reconciliation flag, human verdict — tagged with what
    triggered it.

11. **Portal.**
    Server-rendered, read-only pages (FastAPI + Jinja2) over `active` /
    `superseded` / `reversed` decisions, showing current state and full
    history per decision. No manual edit UI — the pipeline is the only writer.

## Scoping & noise control

One org can run many projects, each spanning its own repo and Discord
channels — and a single Discord server can itself host channels for multiple
unrelated projects. See
[decisions/0003-channel-scoped-ingestion.md](decisions/0003-channel-scoped-ingestion.md)
and [decisions/0005-multi-tenant-projects.md](decisions/0005-multi-tenant-projects.md)
for the full reasoning; summary:

- Storage is not the constraint (raw text at this volume is cheap).
- The constraint is **scope contamination** — unrelated discussions merging
  into the same discussion unit, or bloating the candidate-filter/reconciliation
  search space across projects.
- Fix is ingestion-time allowlisting at the `project` level, not post-hoc
  filtering. Channels/repos not explicitly attached to a project are never
  ingested at all.
- `project_id` is enforced as a hard boundary in discussion reconstruction,
  candidate filtering, supersession search, and reconciliation.

## Job queue

No separate broker (Redis/Celery) for v1. Postgres itself is the queue via
`SELECT ... FOR UPDATE SKIP LOCKED`. Revisit only if worker throughput becomes
a real bottleneck — unlikely at portfolio-project scale.
