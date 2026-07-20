# ADR-0002: Python-only web stack — FastAPI + Jinja2 + HTMX

Status: Accepted

## Context

The backend (ingestion, pipeline, reconciliation) is Python/FastAPI by
necessity — `discord.py`, AST parsing, `sentence-transformers`, and pgvector
tooling are all Python-native. The original spec suggested Next.js for the
review UI + portal, which would mean maintaining a second language/toolchain
and a separate frontend build/deploy step for a two-page-type UI (a review
queue and a read-only portal).

## Decision

Build the review UI and the public portal as server-rendered pages within the
same FastAPI app, using Jinja2 templates and HTMX for interactivity (approve /
edit / reject without full page reloads). No separate JS framework, no
separate frontend build pipeline.

## Consequences

- Entire project is one language, one deploy artifact, one process type
  family (see [ADR-0004](0004-deployment-fly-neon.md)).
- HTMX covers the interactivity actually needed here (queue actions, live
  status updates) without adopting React/Next for a UI this simple.
- If the portal ever needs a genuinely rich client-side experience, revisit —
  but that bar is intentionally high for v1.
