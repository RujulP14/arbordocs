---
name: explore-plan-code
description: Structures non-trivial ArborDocs work into exploration, planning, implementation, and verification. Use when changes cross modules or involve architectural tradeoffs.
---

# Explore, Plan, Code

## Explore

- Read `AGENTS.md`, relevant ADRs, implementation, and tests.
- Trace current data flow and identify affected boundaries.
- State assumptions and unknowns; do not edit yet.

## Plan

- Define testable success criteria and non-goals.
- List files to change in order.
- Identify schema, security, lifecycle, and rollback risks.
- Include exact verification commands.
- For materially different valid approaches, recommend one and explain the tradeoff.

For architecture changes or when the user requested planning, stop for approval.
For straightforward implementation requests, proceed once the plan is internally
sound.

## Code

- Prefer test-first changes where behavior is testable.
- Keep edits within scope and follow existing patterns.
- Re-plan if runtime evidence invalidates the approach.

## Verify

- Run focused tests, then proportionate Ruff/Alembic/full-suite checks.
- Review the diff against the request and report concrete evidence.
