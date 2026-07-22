# ArborDocs

A knowledge layer that captures **decisions made in Discord** and reconciles
them against your **GitHub codebase** — so "let's go with cursor-based
pagination" doesn't evaporate into scrollback, and so you find out when the
code quietly drifts from a decision the team actually made.

Most "AI docs" tools solve an already-commoditized problem: *a commit
changed, so update the doc.* ArborDocs solves the other half — the decision
almost never gets written down in the first place. It watches chat, extracts
the durable decisions, checks them against the real repo, and puts them in
front of a human to confirm before anything becomes official.

**Live instance:** [arbordocs.fly.dev](https://arbordocs.fly.dev) — deployed,
but currently running only the `web` and `bot` process groups; the `worker`
process (which actually runs the extraction pipeline) isn't deployed there
yet, see [Deploying](#deploying). Admin login is gated to registered admins
(ADR-0006) — there's no public signup.

## How it works

```
Discord chat ──► Discussion       ──► Candidate  ──► LLM extraction ──► Decision
                  reconstruction       filter          (gate+extract)    (proposed)
                  (Stage 0)            (Stage 1)        (Stage 2)             │
                                                                               │
                                                          ┌────────────────────┼──────────────────┐
                                                          ▼                    ▼                  ▼
                                                   Supersession         Reconciliation      Human review
                                                   tracking             (vs. GitHub)         (approve/
                                                   (Stage 3)                                 reject/edit)
                                                                                                   │
                                                                                                   ▼
                                                                                            active decision
```

1. **Discord ingestion** — a shared bot invited into your server watches only
   the channels you explicitly attach to a project; nothing else is ever
   ingested.
2. **Discussion reconstruction (Stage 0)** — messages are grouped into
   discussion units by reply-chain, then temporal proximity + participant
   overlap + embedding similarity — because a decision is rarely one message.
3. **Candidate filter (Stage 1)** — a cheap, high-recall pass (keyword cues +
   embedding similarity to known-decision exemplars + a ✅ reaction) flags a
   closed discussion as decision-like. Tuned for recall — it's fine to
   over-flag here.
4. **LLM extraction (Stage 2)** — an LLM gates ("is this actually a resolved
   decision?") and, if so, extracts it into a structured record: statement,
   type, scope, rationale, decider, and the exact source messages it's
   grounded in.
5. **Supersession tracking (Stage 3)** — every new decision is checked by
   embedding similarity against existing active decisions in the same
   project; an LLM classifies the relationship
   (`unrelated`/`amendment`/`reversal`/`duplicate`) and updates the chain —
   this is how it catches "actually, let's use cursor pagination instead"
   *without* the message ever naming the original decision.
6. **GitHub reconciliation** — your connected repo's docs and code are parsed
   into a lightweight, embedded index. Every decision is checked against it
   by similarity, surfacing the files/docs it likely affects — for a human to
   confirm, never auto-written.
7. **Human review** — every extracted decision lands as `proposed`, never
   visible anywhere else, until a human approves, edits, or rejects it in the
   review UI — with the real source-message transcript, confidence, and
   reconciliation flags right there.

See [`docs/SPEC.md`](docs/SPEC.md) for the full design rationale and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the exact runtime flow.

## What's built today

- ✅ Admin login (GitHub OAuth), multi-project support, GitHub App install +
  repo picker, Discord bot invite + channel picker
- ✅ Stage 0 (discussion reconstruction) + Stage 1 (candidate filter)
- ✅ Stage 2 (LLM extraction) + Stage 3 (supersession/reversal tracking) —
  Groq (`openai/gpt-oss-120b`) by default, Ollama (`qwen2.5:7b`, fully local)
  as a no-cost fallback
- ✅ GitHub content ingestion — docs/code parsed into a per-project index
- ✅ Reconciliation engine (tier-b: embedding-similarity surfacing against
  the GitHub index)
- ✅ Human review UI — approve / reject / edit queue for proposed decisions
- ✅ Eval harness — decision-detection F1 measured against a labeled
  synthetic dataset (`eval/harness.py`)

## What's not built yet

- ⬜ Public read-only portal over active decisions ([#12](https://github.com/RujulP14/arbordocs/issues/12))
- ⬜ Audit ledger ([#13](https://github.com/RujulP14/arbordocs/issues/13))
- ⬜ Discord Thread ingestion/grouping ([#11](https://github.com/RujulP14/arbordocs/issues/11))
- ⬜ Tier-a concrete contradiction detection (Phase 6 stretch)
- ⬜ Google Drive doc auto-update on approval ([#14](https://github.com/RujulP14/arbordocs/issues/14))

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the full phased build order and
[open issues](https://github.com/RujulP14/arbordocs/issues) for known gaps.

## Using it

ArborDocs is a self-hosted app, not a multi-tenant SaaS with public signup —
admin accounts are provisioned directly in the database (ADR-0006), not via
self-serve registration. The [live instance](https://arbordocs.fly.dev) is
one deployment of it; you can also run your own (locally or deployed) and
connect your own Discord server + GitHub repo to it.

Once you have admin access, the flow is:

1. Log in with GitHub.
2. Create a project.
3. Connect a GitHub repo (installs a GitHub App, pick the repo).
4. Invite the Discord bot to your server and pick which channels to watch.
5. Let it run — decisions extracted from chat show up in the review queue at
   `/projects/{id}/decisions` for you to approve, reject, or edit.

## Running it locally

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (dependency manager)
- Docker (for local Postgres + pgvector)
- A [GitHub App](https://github.com/settings/apps/new) registered (used for
  both admin login and per-project repo access — see
  [ADR-0007](docs/decisions/0007-single-github-app-for-login-and-repos.md))
- A [Discord bot application](https://discord.com/developers/applications)
- A free [Groq API key](https://console.groq.com/keys) (Stage 2 extraction),
  or [Ollama](https://ollama.com/) installed locally as a no-cost alternative

### Setup

```bash
git clone https://github.com/RujulP14/arbordocs.git
cd arbordocs

# Install dependencies
uv sync

# Start local Postgres + pgvector
docker compose up -d

# Configure environment
cp .env.example .env
# Fill in: GITHUB_APP_* (from your GitHub App settings), DISCORD_* (from your
# Discord application), GROQ_API_KEY (or leave blank to use Ollama instead)

# Apply database migrations
uv run alembic upgrade head

# Bootstrap yourself as the first admin (your GitHub username)
uv run python -m scripts.seed_admin --github-login <your-github-username>
```

### Run it

Three processes, each in its own terminal:

```bash
# Web app — admin UI, login, review queue
uv run uvicorn app.web.main:app --host 0.0.0.0 --port 8000 --reload

# Discord bot — ingests messages from attached channels
uv run python -m app.ingestion.discord.bot

# Worker — runs the extraction pipeline (Stage 1 → 2 → 3 → reconciliation)
uv run python -m app.worker.main
```

Then open `http://localhost:8000/auth/github/login`, log in, and follow the
[Using it](#using-it) flow above to connect a repo and some Discord channels.

### Tests

```bash
uv run pytest                                    # full test suite
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run python -m eval.harness --verbose          # decision-detection F1 on the labeled dataset
```

## Deploying

Single [Fly.io](https://fly.io) app running three process groups (`web`,
`bot`, `worker`) against a [Neon](https://neon.tech) (serverless
Postgres + pgvector) database — see
[ADR-0004](docs/decisions/0004-deployment-fly-neon.md) for why this shape.

```bash
export DATABASE_URL_PROD='postgresql+asyncpg://<user>:<pass>@<host>/<db>'  # your Neon connection string
./scripts/deploy.sh
```

The script pushes your `.env` values as Fly secrets, deploys, and scales all
three process groups. After first deploy, update your GitHub App's callback
URL and Discord's redirect URI to point at your Fly app's domain.

## Stack

Python + FastAPI + Jinja2/HTMX (no separate frontend build), Postgres +
pgvector, `discord.py`, GitHub App (JWT + installation tokens), Groq/Ollama
for LLM extraction, local `sentence-transformers` embeddings. See
[ADR-0002](docs/decisions/0002-python-only-web-stack.md) for the
single-stack rationale.

## Docs

- [`docs/SPEC.md`](docs/SPEC.md) — full project spec (thesis, components,
  extractor design, data model, evaluation plan)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — runtime flow: how data
  moves through the running system end to end
- [`docs/decisions/`](docs/decisions/) — ADRs for decisions made about how
  the project itself is built
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phased build order, with real
  verification evidence for each completed piece
- [`docs/changes/CHANGELOG.md`](docs/changes/CHANGELOG.md) — notable changes
