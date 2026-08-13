---
name: architecture-decision-record
description: Authors ArborDocs build ADRs and updates the decision index. Use when recording or superseding an architectural, dependency, deployment, or system-boundary decision.
---

# Architecture Decision Record

1. Read `docs/decisions/README.md`, related ADRs, and the latest ADR number.
2. Create `docs/decisions/NNNN-kebab-title.md`.
3. Use:

```markdown
# ADR-NNNN: Title

Status: Accepted

## Context

## Decision

## Consequences
```

4. Update the index in `docs/decisions/README.md`.
5. ADRs are append-only. If superseding one, link both records; never delete or renumber history.
6. If the decision changes permanent guidance, update `AGENTS.md` and the relevant `.cursor/rules/*.mdc`.

These ADRs describe how ArborDocs is built. They are distinct from product
decision records extracted from Discord.
