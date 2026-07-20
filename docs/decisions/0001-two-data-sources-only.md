# ADR-0001: Two data sources only — Discord + GitHub

Status: Accepted

## Context

An "AI docs" tool that syncs one source (code) to another (docs) is a
commoditized problem — Claude Code, Cursor, DeepDocs, and Code-to-Docs actions
already do this. Adding more chat/code connectors (Slack, Jira, Notion, Linear)
would look more "enterprise-ready" but doesn't add a new capability, only more
surface area to build and maintain.

## Decision

Ingest from exactly two sources: Discord (chat, where decisions are made and
lost) and GitHub (code + docs, the objective ground truth). No other
connectors in v1. Ingestion is adapter-based so a Slack adapter is a plausible
future extension, but it is explicitly out of scope now.

## Consequences

- The differentiator is cross-source reconciliation (chat decision vs. code
  reality), not breadth of ingestion. This is what makes the project
  finishable by one person and defensible in an interview.
- GitHub's role is strictly "ground truth to check against" — it is not a
  target the system auto-updates.
- Adding Slack later is a real but deliberately deferred stretch item (see
  [ROADMAP.md](../ROADMAP.md) Phase 6).
