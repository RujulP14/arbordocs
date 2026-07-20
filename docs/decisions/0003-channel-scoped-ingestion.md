# ADR-0003: Channel-scoped ingestion as the noise/scope control

Status: Accepted (superseded in part by [ADR-0005](0005-multi-tenant-projects.md) —
scope is now expressed as `project_id`, not a flat `product_scope` tag; the
reasoning below for *why* scoping happens at ingestion time still holds)

## Context

A real deployment could span ~100 Discord channels, covering multiple
unrelated products and a lot of off-topic chatter. Two distinct concerns come
from this, and they have different fixes:

1. **Storage size.** At realistic volumes (even 50k messages/day across 100
   channels), raw text storage is on the order of tens of GB/year — not a
   real constraint for a project this size. This is not the problem worth
   solving for.
2. **Scope contamination.** Messages about unrelated products, or pure noise
   channels (`#random`, `#memes`), would pollute discussion reconstruction
   (Stage 0) and bloat the candidate-filter search space (Stage 1) if
   ingested indiscriminately.

Filtering noise out *after* ingestion (post-hoc) still costs embedding calls
and still risks two unrelated discussions merging into one "unit" if they
happen to be temporally adjacent in the same channel.

## Decision

Scope at ingestion time, not after. The Discord bot only ingests channels
explicitly attached to a project (via the integrations page — see
[ADR-0005](0005-multi-tenant-projects.md)) — everything else is never stored,
not filtered later.

`project_id` is enforced as a hard boundary in Stage 0 discussion
reconstruction: two messages belonging to different projects are never merged
into the same discussion unit, even if temporally adjacent or (in principle)
in the same channel. Authority tiering (Stage 4) is a per-channel attribute
within a project's config, not a separate global mapping.

Additionally, high-frequency embedding calls (Stage 0 boundary detection,
Stage 1 exemplar similarity) use a local `sentence-transformers` model rather
than an API, since these run per-message/per-pair at volume. API-based
embeddings are reserved for the low-frequency Stage 3 supersession search over
the much smaller set of already-extracted decisions.

## Consequences

- Ingestion requires an onboarding step (create project → attach repo →
  attach channels, see ADR-0005) before the bot does anything for a given
  project — this is now part of Phase 1, not an afterthought.
- Discussion reconstruction and candidate filtering only ever operate within
  one project's relevant channels — the search space stays naturally bounded.
- Embedding cost scales with API calls only at the (small) decision-level, not
  at the (large) message level.
- Retention/archival of old raw messages is a legitimate future control but
  explicitly deferred — not a v1 concern.
