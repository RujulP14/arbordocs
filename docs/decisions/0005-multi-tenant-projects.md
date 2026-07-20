# ADR-0005: Multi-tenant model — single admin, per-project GitHub + Discord integrations

Status: Accepted

Supersedes the single-server/single-repo assumption baked into the original
[SPEC.md](../SPEC.md) and the flat channel config in
[ADR-0003](0003-channel-scoped-ingestion.md) (see that file's updated version).

## Context

The original spec assumed ArborDocs tracks one Discord server and one GitHub
repo, configured via `.env`. In practice, an org running ArborDocs works on
multiple products/repos at once, and wants to register each one — its GitHub
repo plus the Discord channels discussing it — as a distinct unit through an
integrations page, without an engineer editing environment variables per
deployment.

This also means credentials split into two categories that were previously
conflated:

- **Platform-level secrets** — belong to ArborDocs itself (you, the operator):
  one GitHub App, one Discord bot application. Registered once, shared across
  every admin/project that uses the platform.
- **Per-project references** — belong to a specific admin's specific project:
  which repo, which Discord channels. These are data, not secrets — they live
  in Postgres, entered through the integrations UI, not in `.env`.

## Decision

**Identity.** A single admin login per account, authenticated via GitHub OAuth
(reuses the GitHub App's OAuth flow — see [ADR-0007](0007-single-github-app-for-login-and-repos.md) —
rather than building password/email auth from scratch). Authorization (who
counts as an admin) is a `users` table in Postgres, not an env allowlist — see
[ADR-0006](0006-admin-authorization-in-db.md) for why and how the first admin
is bootstrapped.

**Projects.** The core new entity. An admin creates one `project` per
thing being tracked. Each project owns:
- exactly one GitHub repo connection (a GitHub App installation + selected
  repo — see below)
- a list of Discord channels mapped to it (selected from servers the shared
  bot has been invited to — see below)

All decision records, embeddings, and reconciliation state are scoped to a
`project_id`. This replaces the flat `channel → {product_scope,
authority_tier}` config from the original ADR-0003 — scope is now a first-
class entity (`project`), not a tag.

**GitHub connection (per project) — no manual entry.** ArborDocs registers a
single GitHub App (one App ID, one private key — platform secrets, set once
in `.env`, never seen by end users). From the integrations page, the admin
clicks **"Connect GitHub"**, which opens GitHub's own install screen; the
admin picks which repo(s) to grant access to there (on GitHub's site, not
ours). GitHub redirects back to ArborDocs with an `installation_id`; our UI
then calls GitHub's API to list the granted repos and shows them as a
dropdown — the admin picks one and attaches it to a project with a click. The
admin never pastes a repo URL, a token, or any credential into any ArborDocs
form. We store `installation_id` + chosen repo name against the project row.

**Discord connection (per project) — no manual entry.** ArborDocs registers a
single Discord bot application (one bot token — platform secret, set once in
`.env`, never seen by end users). From the integrations page, the admin
clicks **"Add to Discord"**, which opens Discord's own OAuth bot-invite
screen; the admin approves it for their server there (on Discord's site, not
ours). Discord redirects back to ArborDocs; our UI then calls the Discord API
(using the platform bot token) to list channels in that server and shows them
as a checklist — the admin picks which ones attach to the project. The admin
never pastes a bot token, channel ID, or webhook URL into any ArborDocs form.
The bot process serves every server it's been invited to across all admins/
projects; routing an incoming message to the right project is a channel-ID →
project-ID lookup in our DB, not a separate bot instance per tenant.

**Onboarding flow, end to end:**
1. Admin logs in via GitHub OAuth (allowlisted identity).
2. Admin creates a project (name, description).
3. Admin installs the GitHub App on their repo, or picks an existing
   installation → attaches the repo to the project.
4. Admin invites the shared bot to their Discord server (if not already
   present) → picks channels → attaches them to the project.
5. Ingestion begins for that project only.

## Consequences

- `.env` / platform secrets shrink to: GitHub App ID + private key + OAuth
  client id/secret + webhook secret, Discord bot token + OAuth client
  id/secret, admin allowlist, database URL, LLM key. No `GITHUB_REPO` env var
  — repo selection is per-project DB data entered through the UI.
- Every table that previously assumed a single global scope (`messages`,
  `decisions`, embeddings, the job queue, the audit ledger, the GitHub
  symbol/doc index) now carries a `project_id` foreign key.
- The Discord bot is one process serving many guilds/channels across many
  projects — message routing is a lookup, not a deploy-per-tenant model.
- The GitHub App is one App with potentially many installations (one per
  admin/org) — reconciliation and webhook handling must key off
  `installation_id` → `project_id`, not assume a single repo.
- Discussion reconstruction, candidate filtering, and reconciliation all
  operate strictly within one project's data — a project is now the hard
  boundary that `product_scope` used to informally represent.
- Building the integrations page (project CRUD, GitHub install callback,
  Discord invite + channel picker) becomes part of Phase 1, before ingestion
  can meaningfully start for a real user.
