# ADR-0008: Portal is login-gated, not fully public

Status: Accepted

## Context

SPEC.md §4 frames the portal as "a generated, read-only, searchable site" —
the "headless" framing suggests no auth at all, similar to a public
documentation site. But no ADR or SPEC section ever actually decided the
portal's access model; it was an open question flagged explicitly in the
issue that scoped this work.

Today, only `is_admin=True` users can authenticate at all (ADR-0006 — no
self-serve signup). A separate, not-yet-built change will introduce a
`verified` flag for non-admin users who can log in but aren't full admins —
at that point, "logged in" and "is_admin" stop being the same thing.

## Decision

The portal is gated behind login (any authenticated user, admin or not) —
not fully public. A new `require_login` dependency (`app/web/deps.py`) wraps
the existing `get_current_user` check without requiring `is_admin`; the
portal's routes (`app/web/portal.py`) use `require_login`, while the human
review UI (`app/web/decisions.py`) continues to use `require_admin`.

`require_admin` itself is refactored to call `require_login` first, then
check `is_admin` on top — so "logged in" is now the strictly broader gate,
and "admin" a strict superset of it, rather than two independent checks.

This is deliberately **not** the SPEC.md "headless, fully public" framing.
Given the project has no public signup and a small, curated user base by
design, an unauthenticated public portal isn't a real requirement yet — and
gating it costs nothing today, since `require_login` already exists as the
natural next tier down from `require_admin`.

## Consequences

- Once non-admin `verified` users can log in, they see the portal
  automatically — no additional code change needed, since `require_login`
  doesn't check `is_admin`.
- If the portal needs to become fully public later, the fix is to drop
  `Depends(require_login)` from `app/web/portal.py`'s two routes — a small,
  isolated change, not a rearchitecture.
- The message-permalink redirect route
  (`GET /decisions/{id}/messages/{message_id}/open`, shared by both the
  review UI and the portal) also moved from `require_admin` to
  `require_login`, since a portal visitor following a source-message link
  is not performing an admin action.
