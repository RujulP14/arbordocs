# ArborDocs

A knowledge layer that captures decisions from team chat (Discord) and
reconciles them against the codebase (GitHub) — surfacing when a chat
decision contradicts what the code actually does, or when code quietly drifts
from a decision that was made.

## Docs

- [`docs/SPEC.md`](docs/SPEC.md) — full project spec (thesis, components,
  extractor design, data model, evaluation plan).
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — runtime flow: how data
  moves through the running system end to end.
- [`docs/decisions/`](docs/decisions/) — ADRs for decisions made about how
  the project itself is built.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phased build order.
- [`docs/changes/CHANGELOG.md`](docs/changes/CHANGELOG.md) — notable changes.

## Stack

Python + FastAPI + Jinja2/HTMX, Postgres + pgvector (Neon), discord.py,
GitHub App + webhooks, Claude/OpenAI for extraction. Deployed on Fly.io.
See [ADR-0002](docs/decisions/0002-python-only-web-stack.md) and
[ADR-0004](docs/decisions/0004-deployment-fly-neon.md).

## Status

Pre-Phase 1. See [ROADMAP.md](docs/ROADMAP.md).
