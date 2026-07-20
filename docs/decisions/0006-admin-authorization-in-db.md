# ADR-0006: Admin authorization lives in the DB, not an env allowlist

Status: Accepted

Refines [ADR-0005](0005-multi-tenant-projects.md)'s admin-login section: login
still happens via GitHub OAuth, but *authorization* (who counts as an admin)
moves from an env-configured allowlist to a `users` table.

## Context

ADR-0005 originally proposed `ADMIN_GITHUB_LOGINS` — a comma-separated env var
checked after GitHub OAuth login succeeds. That works but means every change
to who's an admin requires an env edit + redeploy, and there's no natural
place to store per-user data (email, display name, created_at) if the app
ever needs it.

The alternative — a `users` table with `is_admin` — needs one thing env-based
login doesn't: a way to get the *first* admin into the table before any UI
exists to create one. This is a real bootstrap problem, not a detail to wave
away.

## Decision

- **Login mechanism** (unchanged): admin authenticates via the GitHub App's
  OAuth flow (see [ADR-0007](0007-single-github-app-for-login-and-repos.md)
  for why one GitHub App handles this). GitHub returns the user's identity
  (email/login).
- **Authorization**: on successful OAuth callback, look up a `users` row by
  email. If found and `is_admin = true`, create a session. If not found,
  reject — no self-serve signup in v1.
- **Bootstrapping the first admin**: a one-time seed script
  (`scripts/seed_admin.py` or a migration) inserts the first admin's email
  with `is_admin = true` directly into Postgres. Run once, manually, by the
  operator when standing up a new deployment. This is the only place an
  admin's identity is ever set outside the running app.
- Future "invite another admin" functionality (out of scope for v1) would
  just insert/update a `users` row — no env var, no redeploy.

## Consequences

- No `ADMIN_GITHUB_LOGINS` env var. Admin management is entirely DB state
  after the initial seed.
- Adds a `users` table (`id`, `email`, `github_login`, `is_admin`,
  `created_at`) to the Phase 1 schema, and a one-time seed step to the
  deployment runbook — must happen before the first login attempt or it will
  correctly fail closed.
- Reinforces the general principle from ADR-0005: only ArborDocs' own
  bootstrap credentials (GitHub App keys, Discord bot token, DB connection
  string) live in `.env`; everything about specific admins, projects, repos,
  or channels lives in Postgres.
