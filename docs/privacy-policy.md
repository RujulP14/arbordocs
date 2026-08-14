# Privacy Policy — ArborDocs

**Last updated:** 2026-08-14

**Operator:** Rujul Dudhat  
**Contact:** prujul14@gmail.com  
**Service:** ArborDocs at https://arbordocs.fly.dev/ (also referred to as “we”, “us”, or “the Service”)

This Privacy Policy describes how ArborDocs collects, uses, stores, and shares information when you use the Service. ArborDocs helps teams capture technical decisions from Discord, reconcile them against a connected GitHub repository (and optionally Google Drive docs), and publish approved records to a team portal after human review.

This document is a product privacy notice, not legal advice. You may want counsel to review it before relying on it for regulatory compliance.

---

## 1. Who this applies to

This policy covers:

- **Account holders** who sign in with GitHub (admins and verified team members).
- **Workspace content** that connected integrations send to ArborDocs (Discord messages in attached channels, GitHub repository content, and optional Google Drive documents).
- **Visitors** to public marketing pages (home, pricing, support, this policy).

Discord users whose messages appear in an attached channel are not required to create an ArborDocs account. Their message content and related metadata may still be processed as described below because a workspace admin connected that channel.

---

## 2. Information we collect

### 2.1 Account and authentication

When you sign in with GitHub OAuth we may store:

- GitHub username (`login`)
- Display name (if provided by GitHub)
- Email address (if provided by GitHub)
- Account flags such as verified / admin status
- Account creation timestamp

We keep a signed **session cookie** so you stay logged in while using the admin UI and portal. Logging out clears that session.

### 2.2 Project and integration configuration

Per project we may store:

- Project name and description
- Which GitHub App installation and repository are attached (`installation_id`, repo full name, sync timestamps)
- Which Discord guilds/channels are attached (ids, names, authority tier)
- Optional Google Drive folder connection (folder id/name, sync timestamps, and the authorizing admin’s **OAuth refresh token** needed to sync)

### 2.3 Discord workspace content (primary chat source)

For channels an admin explicitly attaches to a project, we ingest and store:

- Message content
- Author Discord id and display name
- Author role ids/names as available
- Channel id/name, timestamps
- Reply / thread structure
- Reactions
- Derived groupings (discussion units), embeddings, and pipeline artifacts used to detect decision-like conversations

**Scope limits:** we only ingest channels the admin attaches (and threads of those channels). We do not intentionally ingest the rest of a Discord server, private DMs between users, or channels that are not attached.

**Outbound Discord messages:** when the pipeline extracts a proposed decision and can identify a decider, we may send that person a **Discord direct message** noting that ArborDocs recorded a candidate decision. The bot is not used to post into your server channels as part of normal ingestion.

### 2.4 GitHub content (ground truth index)

For the repository attached via the GitHub App we may fetch and store indexed representations of:

- Documentation sections (e.g. markdown docs)
- Code symbols (e.g. functions, classes, endpoints) derived from repository files
- Paths, anchors, and embedding vectors used for reconciliation

We store installation metadata needed to access the repo through the GitHub App; we do not store a long-lived personal access token for repo access.

### 2.5 Google Drive content (optional)

If an admin connects a Drive folder:

- We store OAuth credentials (refresh token) for that connection
- We index Google Docs under the connected folder (flattened text / sections) for reconciliation and drafting
- After a human approves a decision, we may generate a **draft edit**; applying that edit to a live Google Doc requires a **second explicit confirmation** in the UI. We do not auto-write docs without that step.

### 2.6 Decisions, review, and audit data

We store structured decision records (statement, type, scope, rationale, participants, confidence, status, supersession links, reconciliation notes), review outcomes (proposed → active / rejected / superseded), and an **append-only audit log** of decision-related events.

Approved (`active`) decisions are visible in the **team portal** to signed-in, verified users. Proposed decisions stay in the review queue and are not published to the portal.

### 2.7 Support and marketing contact

If you submit the support contact form, we may use your name, email, topic, and message so we can respond. Until form delivery is fully wired, you can also email **prujul14@gmail.com** directly. Do not include secrets or credentials in support messages.

### 2.8 Technical and client-side data

- Server logs may include request metadata (timestamps, paths, error traces, project/decision ids). We aim not to log tokens, session secrets, or Authorization headers.
- The web UI may store a **theme preference** in your browser’s `localStorage` (client-side only; not sent as an analytics identifier).
- We do **not** currently use third-party advertising or product-analytics cookies (e.g. no Google Analytics / similar trackers wired into the product).

---

## 3. How we use information

We use the information above to:

- Authenticate users and enforce admin / verified access controls
- Ingest only the integrations and channels you configure
- Run the decision pipeline (reconstruction, filtering, extraction, supersession, reconciliation)
- Show humans a review queue and a searchable portal of approved decisions
- Optionally draft/apply documentation updates in Google Drive after explicit confirmation
- Operate, secure, debug, and improve the Service
- Respond to support requests
- Comply with law or enforce our terms when required

**Human-in-the-loop:** extracted decisions start as `proposed`. We do not auto-publish them to the portal or auto-apply Drive edits without an explicit human action.

---

## 4. AI / LLM processing

Parts of the pipeline send **workspace content** (especially Discord discussion text and related context, and sometimes document/code snippets needed for reconciliation or drafting) to **large language model providers** configured for the Service.

Today the default hosted LLM path uses **Groq**. Local/dev configurations may use other models (e.g. Ollama). Message and document text processed by an LLM is handled under that provider’s terms and data practices in addition to this policy.

We use model output to propose structured decisions and drafts for human review — not to train a public model on your behalf. We do not sell your content.

When we ship customer-managed API keys (BYOK) or additional providers, this section will be updated.

---

## 5. How we share information

We share information only as needed to run the Service:

| Recipient | Role |
| --- | --- |
| **Fly.io** | Application hosting (web, Discord bot, worker) |
| **Neon** | Managed Postgres database (including vector/index data) |
| **GitHub** | Sign-in and repository access via our GitHub App |
| **Discord** | Bot invite, channel message ingestion, optional decider DMs |
| **Google** | Optional Drive/Docs OAuth, indexing, and confirmed doc edits |
| **Groq** (or other configured LLM providers) | Inference for extraction / drafting stages |
| **You / your workspace admins** | Access to project data, review queue, and portal per account permissions |

We do not sell personal information. We may disclose information if required by law, to protect the Service or users, or as part of a merger/acquisition where the successor is bound to equivalent protections.

Subprocessors and regions can change as we operate the product; material changes will be reflected in an updated “Last updated” date on this policy.

---

## 6. Storage, security, and international transfer

- Primary application hosting is on **Fly.io** (current primary region: `iad` / Ashburn, USA).
- Primary database hosting is **Neon** Postgres.
- Platform secrets (bot tokens, GitHub App private key, LLM API keys, database URL) are stored in the host’s secret manager / environment — not in git.
- Project-scoped OAuth tokens needed for integrations (notably Google Drive refresh tokens) are stored in the database so the Service can sync without the admin being present.
- Field-level encryption for message bodies and similar PII at rest is **on the roadmap** and not yet guaranteed for all columns. Database and disk encryption provided by our hosts still apply according to their offerings.

Because we and our processors may operate in the United States and other countries, your information may be processed outside your own country.

No security measure is perfect. Please use least-privilege channel attachment and avoid putting secrets in chat you connect to ArborDocs.

---

## 7. Retention

We retain account, integration, message, decision, and audit data for as long as your project remains connected and the Service needs it to function (including audit history and supersession chains).

Today there is **no fully automated self-serve purge** of all historical messages and embeddings the moment you disconnect a channel. If you disconnect integrations, remove channels, or request deletion, we will delete or de-identify data we control within a reasonable period, except where we must retain information for security, dispute, or legal reasons (for example audit records we are still required to keep).

To request deletion of an account or project data, email prujul14@gmail.com from a verified admin contact associated with the workspace.

---

## 8. Your choices and rights

Depending on where you live, you may have rights to access, correct, delete, or export personal information, or to object to / restrict certain processing. ArborDocs is a small product; many requests are handled manually.

You can:

- Disconnect GitHub, Discord channels, or Google Drive from a project in the product UI (where those controls exist)
- Log out to clear your session cookie
- Ask us to verify, correct, or delete account data via prujul14@gmail.com

If you are a Discord user and want your messages removed from ArborDocs, contact the **workspace admin** who connected the channel, or email us and we will work with that admin where feasible.

---

## 9. Children

The Service is built for professional/team use and is not directed at children under 16 (or the minimum age required in your jurisdiction). We do not knowingly collect personal information from children.

---

## 10. Public pages and OAuth consent screens

Public marketing pages and this Privacy Policy are intended to be reachable without login so that GitHub, Discord, and Google OAuth application settings can link to a stable privacy URL (for example `https://arbordocs.fly.dev/privacy`).

---

## 11. Changes

We may update this policy as the product changes (new providers, encryption, deletion tooling, billing, etc.). We will update the **Last updated** date at the top. Continued use of the Service after an update means you accept the revised policy. For significant changes we may also provide an in-product or email notice when that channel exists.

---

## 12. Contact

Privacy questions or requests: **prujul14@gmail.com**  
Operator: **Rujul Dudhat**

---

## Operator checklist (not shown on the public page)

Before / after publishing `/privacy`:

1. Paste `https://arbordocs.fly.dev/privacy` into GitHub App, Discord app, and Google Cloud OAuth consent screens (privacy / homepage URLs).
2. Revisit this policy when shipping BYOK (#31), PII encryption at rest (#35), support-email delivery (#38), billing, or automated deletion.
