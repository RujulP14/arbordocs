# ArborDocs — Project Specification

> A knowledge layer that captures **decisions from team chat** and reconciles them
> against the **codebase**. This document is the single source of truth for the
> build — it is written to be handed directly to a coding agent (Claude Code)
> as context.

---

## 1. Thesis (read this first)

Most "AI documentation" tools solve an already-commoditized problem: *a commit
changed, so update the doc.* Claude Code, Cursor, DeepDocs, and GitHub Actions
like Code-to-Docs all do this. Building another one adds nothing.

The real, unsolved problem is that **the most important decisions never get
written down at all.** They happen in chat — "let's go with Postgres," "all API
responses must be paginated," "we're deprecating the v1 auth flow" — and then
evaporate. No tool watches that layer.

ArborDocs captures those decisions and does the one thing no single-source tool
can do: **reconciles them against the codebase.** A chat decision that
contradicts what the code actually does, or a code change that quietly violates a
past decision, is surfaced. The unit of value is not "an updated doc" — it is a
**decision record**: extracted from chat, structured, version-tracked, and
checked against reality.

Two data sources only: **Discord** (chat) and **GitHub** (code/docs = ground
truth). Not because more was too hard to build, but because these two together
produce a capability neither has alone.

---

## 2. What this is NOT

To keep scope honest and the project finishable by one person:

- Not a general "sync docs to code" agent (that's the commoditized part).
- Not 8–9 connectors. Ingestion is adapter-based; Discord is built because it has
  an open API. Slack would be the same interface behind a different adapter, but
  is out of scope for v1.
- Not a streaming/CDC platform. A GitHub webhook + Discord gateway/bot events are
  the realistic event sources. Choosing a webhook over Kafka is a deliberate
  cost/complexity tradeoff, not a shortcut.
- Not a permissions engine. Authority is approximated by channel-scoping + simple
  signals (see §5, Stage 4).

---

## 3. Architecture overview

Two inputs feed a core engine. Discord messages flow through a **decision
extractor** that pulls durable decisions out of noisy chat. Those decisions go
into a **reconciliation engine** that checks each one against GitHub (code +
docs). Contradictions and proposed records go to **human review**; approved
records land in a **decision store + read-only portal**. An **append-only audit
ledger** records every decision's history, and an **eval harness** measures the
extractor offline.

```
Discord ──► Decision extractor ──►┐
                                  ├──► Reconciliation engine ──► Human review ──► Decision store + portal
GitHub (code/docs = truth) ──────►┘                                   │
                                                                      └──► Audit ledger (append-only)

Eval harness (offline, measures the extractor)
```

Color-of-responsibility: the extractor + reconciliation engine are the novel
core; Discord/GitHub are inputs; the store/portal + human review are output;
the eval harness is measurement.

---

## 4. Components

**Multi-tenancy.** ArborDocs is multi-tenant: a single admin (logged in via
GitHub OAuth) can register multiple **projects** through an integrations page,
each with its own GitHub repo and its own set of Discord channels. See
[ADR-0005](decisions/0005-multi-tenant-projects.md) for the full model. All
components below operate per-project.

**Discord ingestion.** One shared bot application, invited by admins into
their own Discord servers via OAuth; an admin then picks which channels feed
which project. Pulls message history and subscribes to new messages for
attached channels only. Captures: message content, author + author roles,
channel, timestamps, reply/thread structure, reactions. Store raw messages;
do not pre-filter at ingestion (but see [ADR-0003](decisions/0003-channel-scoped-ingestion.md)
for project-scope allowlisting).

**GitHub ingestion (ground truth).** One shared GitHub App; admins install it
on their own GitHub account/org and attach a chosen repo to a project (via an
`installation_id`, not a stored PAT). Parse docs (markdown in `/docs`, README,
API reference) into sections. Parse code into symbols (functions, classes,
endpoints, config keys) via AST. Build a lightweight per-project index of
symbols and doc sections that the reconciliation engine can query. GitHub's
role is to be the objective, measurable side of the system — not to
auto-update docs.

**Decision extractor.** The core NLP pipeline. See §5 for the full design.

**Reconciliation engine.** Given a structured, active decision with a `scope`,
check it against GitHub. Two tiers: (a) for decisions that map to a detectable
code/doc pattern, flag concrete contradictions; (b) otherwise, use embedding
similarity to surface the files/docs the decision likely affects and let a human
confirm. "Surface + human-confirm" is an acceptable v1 — full semantic
reconciliation is explicitly out of scope.

**Human review.** Each extracted decision or flagged contradiction appears as a
review item: the decision statement, source message links, confidence, and any
reconciliation flags. Human confirms / edits / rejects. Autonomy toggle:
draft-only vs. auto-commit for high-confidence structural items.

**Decision store + portal.** Postgres-backed store of decision records. A
generated, read-only, searchable site renders current active decisions and
their history. No manual edit UI — maintenance is the pipeline's job; consumption
is read-only. (This is the "headless" framing.)

**Audit ledger.** Append-only log of every detection, extraction, supersession,
and human decision, with the source that triggered it. Separates *what changed*
from *why the system proposed it*. Doubles as the decision-history feature.

---

## 5. The decision extractor (the make-or-break component)

The naive approach — send every message to an LLM asking "is this a decision?" —
fails on cost, on noise, and because a decision is almost never one message.
Build it in stages.

### Definition of a "decision" (write this down before coding)
A **durable statement about how the team will operate**: a technical choice, a
policy, a process change, or a product/scope call. Explicitly excluded:
questions, unresolved proposals, jokes, status updates. Decide up front whether
provisional decisions ("let's try X and see") count — this definition doubles as
the labeling guide for evaluation.

### Stage 0 — Reconstruct discussions, not messages
Group related messages into discussion units. Use Discord's native reply/thread
structure first; fall back to temporal proximity + shared participants + topic
continuity (embedding similarity between consecutive messages). The unit of
analysis is the discussion arc ("should we do X?" → debate → "ok, going with Y"),
never the isolated message.

### Stage 1 — Cheap, high-recall candidate filter
Do not send every discussion to an LLM. First pass tuned for **recall** (over-flag
freely; the next stage handles precision). Combine keyword/pattern cues
("let's go with", "we decided", "from now on", "the policy is", "final call",
✅ reactions) with embedding similarity to a handful of known-decision exemplars.
Above threshold → candidate. This two-stage design is the cost-control story.

### Stage 2 — LLM extraction into a fixed schema
For each candidate discussion, the LLM does two jobs:
1. **Gate:** Is there a *resolved* decision here, or just discussion? (kills
   over-extraction of brainstorming)
2. **Extract:** If yes, fill the structured schema below.

Force structured JSON output. Ground extraction strictly in the source text and
require the model to cite the `message_ids` it used (kills hallucinated rationale).

### Stage 3 — Supersession & reversal tracking (the part that makes the project)
Decisions get reversed weeks later, usually **without referencing the original**
("actually, drop pagination, cursor-based is cleaner"). Reference-matching won't
catch this. When a new decision is extracted:
1. Retrieve semantically similar **existing active** decisions (vector search over
   the `statement` field).
2. LLM-classify the relationship: `unrelated` / `amendment` / `reversal` /
   `duplicate`.
3. Update the chain: mark superseded decisions, link via
   `supersedes` / `superseded_by`.

Output is a **decision history** — how "our auth approach" evolved over time, with
sources at each step. No single-source tool has this.

### Stage 4 — Authority & confidence (keep simple)
Not every decision is a policy. Approximate authority with a config mapping
channels to tiers (`#eng-leads` > `#general`), plus light signals: author role
from Discord, consensus reactions, linguistic certainty ("final" vs "maybe").
Do NOT build a permissions engine — channel-scoping as an authority proxy is a
defensible, deliberate v1 choice.

---

## 6. Data model — decision record

```json
{
  "id": "uuid",
  "project_id": "uuid",
  "statement": "API responses must be paginated by default",
  "type": "policy | technical | process | product",
  "scope": "backend/api",
  "rationale": "large payloads were timing out mobile clients",
  "decider": "discord_user_id",
  "participants": ["discord_user_id", "..."],
  "source": {
    "platform": "discord",
    "channel": "#eng-decisions",
    "message_ids": ["...", "..."],
    "timestamp": "ISO-8601"
  },
  "authority_tier": "high | medium | low",
  "status": "active | proposed | superseded | reversed",
  "confidence": 0.82,
  "supersedes": "uuid | null",
  "superseded_by": "uuid | null",
  "reconciliation": {
    "state": "consistent | contradiction | unverified",
    "related_code": ["path/to/file.py#symbol"],
    "related_docs": ["docs/api.md#pagination"],
    "notes": "..."
  }
}
```

---

## 7. Evaluation (three separate metrics — the centerpiece of the project)

Do not skip measurement; it's what separates this from an LLM wrapper. Source a
public Discord export (or seed synthetic decision threads) and hand-label.

1. **Decision detection — headline metric.** Label a few hundred discussions as
   decision / not-a-decision. Report precision / recall / F1.
2. **Extraction quality.** On true decisions, human-rate whether `statement`
   captures the real decision (small set).
3. **Supersession classification.** Build a set of decision pairs; report accuracy
   on `unrelated / amendment / reversal / duplicate`. This is the most impressive
   number because it proves you engaged the actual hard problem.

Also run ablations where cheap: candidate-filter recall vs. threshold; with/without
Stage 0 discussion reconstruction.

---

## 8. Failure modes to design against (and to be ready to discuss)

- **Over-extraction** (brainstorming logged as decisions) → Stage 2 gate.
- **Missed implicit reversals** → Stage 3 semantic retrieval, not reference-matching.
- **Hallucinated rationale** → ground extraction in cited `message_ids`.
- **Noise domination** (~95% of chat is not decisions) → Stage 1 cheap filter.

---

## 9. Tech stack

- **Backend:** Python + FastAPI.
- **Discord:** `discord.py` (or Discord API + bot token) for ingestion.
- **GitHub:** GitHub App + webhooks; AST via Python `ast` for v1 (tree-sitter as
  the language-agnostic upgrade — mention, don't build yet).
- **Embeddings + vector search:** local `sentence-transformers` for high-frequency
  Stage 0/1 embeddings, stored in **Postgres + pgvector** (one DB for records,
  embeddings, and ledger — do not add a separate vector DB).
- **LLM:** Groq (`openai/gpt-oss-120b`) for the Stage 2 gate/extraction and
  Stage 3 relationship classification — chosen after a side-by-side
  comparison against Gemini and a local Ollama model (`eval/
  compare_providers.py`); Groq's free tier gave the most accurate `type`
  classification and best-calibrated confidence scores. Use structured/JSON
  output (`response_format.json_schema`, `strict: true`). Ollama
  (`qwen2.5:7b`, fully local, no API key) remains available via
  `extract_decision(..., provider="ollama")` as a no-cost fallback.
- **Frontend:** FastAPI + Jinja2 templates (+ HTMX for interactivity) for both the
  review UI and the read-only portal — kept in Python end-to-end, no separate
  JS framework/build step.
- **Deploy:** single Fly.io app (web / bot / worker processes) + Neon
  (Postgres + pgvector, serverless).

---

## 10. Build order (ship after Phase 5)

1. **Admin login + integrations page + Discord ingestion + storage.** GitHub
   OAuth admin login; project CRUD; GitHub App install flow; Discord bot
   invite + channel picker (see ADR-0005). Bot connected, messages persisted
   with metadata (author, roles, channel, replies, reactions, timestamps),
   scoped to channels explicitly attached to a project (see ADR-0003).
2. **Stage 0 + Stage 1.** Discussion reconstruction + cheap candidate filter.
   Output candidates to a console/table. No LLM yet.
3. **Eval harness + labeled dataset.** Build this early — it tells you whether
   later stages actually work. Get decision-detection F1 measurable.
4. **Stage 2 + Stage 3.** LLM extraction into the schema; supersession tracking.
   Re-run eval, add the supersession metric.
5. **GitHub ingestion + reconciliation (tier-b first) + human review UI +
   decision store + portal + audit ledger.**
6. **(Stretch)** Tier-a concrete contradiction detection; Slack adapter; a
   query bot (RAG over approved decisions with citations); per-domain configs
   reframed as "specialist agents."

A finished Phase-5 version beats a half-built Phase-6 one.

---

## 11. Resume framing

Lead with the measured result and the engineering, not marketing language:

> Built a knowledge tool that extracts durable team decisions from Discord chat
> and reconciles them against a GitHub codebase. Two-stage pipeline (cheap
> high-recall filter → LLM structured extraction) with semantic supersession
> tracking; achieved [X] F1 on decision detection and [Y]% on supersession
> classification over [N] labeled discussions. Python, FastAPI, pgvector,
> Discord + GitHub APIs.

Be ready to answer: how you defined and labeled a "decision"; why two-stage
instead of one LLM call (cost/noise); how you catch reversals that don't
reference the original; and why channel-scoping stands in for a permissions model.

---

## 12. Positioning notes (for README / project summary)

- Frame ingestion as "chat platforms (Discord, Slack)" — Discord chosen because
  its API is open; the ingestion layer is adapter-based.
- The differentiator is **cross-source reconciliation**, not chat→docs alone.
  Cursor can't see Discord; a Discord bot can't see the codebase. This tool sits
  in the gap.
- The unit of value is a **decision record with history**, not a rendered doc.
