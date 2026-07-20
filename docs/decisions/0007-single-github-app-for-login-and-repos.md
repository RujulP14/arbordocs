# ADR-0007: One GitHub App for both admin login and repo access

Status: Accepted

## Context

GitHub authentication for this project needs to answer two different
questions: "who is this person?" (admin login) and "can ArborDocs read this
repo?" (per-project repo access). Historically these mapped to two different
GitHub registrations — a plain OAuth App for identity, and a GitHub App for
installable repo access with webhooks. GitHub Apps now include user-to-server
OAuth natively, so a single GitHub App registration can serve both purposes
with one client id/secret pair.

## Decision

Register exactly one GitHub App for ArborDocs. Use its OAuth flow for admin
login (identity only — see [ADR-0006](0006-admin-authorization-in-db.md) for
how that identity maps to admin authorization) and its installation flow for
per-project repo access (see [ADR-0005](0005-multi-tenant-projects.md)).

## Consequences

- One registration on GitHub's developer settings, one client id/secret pair
  (`GITHUB_APP_CLIENT_ID` / `GITHUB_APP_CLIENT_SECRET`), alongside the App's
  own `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY_B64` / `GITHUB_WEBHOOK_SECRET`.
  No separate OAuth-App credentials to manage. The private key is stored
  base64-encoded (not as a file path) so the same env-var-based secret
  mechanism works identically in local `.env` and in a deployed platform's
  secrets store (e.g. `fly secrets set`) — no file needs to be placed on disk
  in either environment.
- Login and repo-installation are still functionally separate flows in the
  app (different redirect URLs, different scopes requested), they just share
  one underlying GitHub-side registration.
