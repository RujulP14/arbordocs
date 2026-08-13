---
name: pipeline-module
description: Adds or extends ArborDocs decision-pipeline stages and worker orchestration. Use for reconstruction, candidate filtering, extraction, supersession, indexing, reconciliation, or auditing.
---

# Pipeline Module

1. Read `docs/ARCHITECTURE.md`, the affected module under `app/pipeline/`, its tests, and worker wiring when relevant.
2. Preserve the stage contract:
   - Stage 0: reconstruct discussions
   - Stage 1: high-recall candidate filter
   - Stage 2: grounded extraction into `proposed`
   - Stage 3: supersession classification
   - Then reconciliation and human review
3. Keep stage logic independently testable; orchestration belongs in `app/worker/main.py`.
4. Treat `project_id` as a hard data boundary.
5. Cite real `message_ids`; never invent grounding.
6. Append audit events for durable state changes.
7. Add focused tests. For Stage 1/2 behavior changes, run or assess `eval/harness.py`.

Never auto-activate decisions, auto-publish them, or auto-apply document edits.
Processes coordinate through Postgres, not internal HTTP calls.
