---
name: code-review
description: Reviews ArborDocs changes for correctness, architecture, security, tests, and hidden assumptions. Use for branch reviews, PR preparation, or significant local changes.
---

# Code Review

Review the requested diff, not unrelated repository code. Report findings
before summaries, ordered by severity, with file and line references.

Check:

- behavior matches the request and existing patterns
- `project_id` isolation is preserved
- extracted decisions remain `proposed` until human approval
- Discord ingestion remains channel-scoped
- route handlers stay thin and portal data is correctly filtered
- model changes include an Alembic revision
- secrets, OAuth tokens, cookies, and authorization headers are neither committed nor logged
- async paths avoid blocking I/O and unsafe session use
- tests cover happy paths, boundaries, and failures
- changes are minimal and do not introduce duplicate abstractions

If there are no findings, state that explicitly and list residual risks or
verification gaps. A passing test suite is evidence, not proof of correctness.
