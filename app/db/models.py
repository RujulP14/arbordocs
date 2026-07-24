import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.pipeline.embeddings import EMBEDDING_DIM

# JSONB on Postgres (prod/dev), plain JSON elsewhere (e.g. sqlite in tests).
JsonColumn = JSON().with_variant(JSONB(), "postgresql")

# pgvector on Postgres (prod/dev), plain JSON elsewhere (e.g. sqlite in tests
# — sqlite has no vector type, but schema-sanity tests don't need real
# similarity search, just a column that round-trips a list of floats).
EmbeddingColumn = Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    github_login: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    projects: Mapped[list["Project"]] = relationship(back_populates="created_by_user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    created_by_user: Mapped["User"] = relationship(back_populates="projects")
    github_installation: Mapped["GitHubInstallation | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    google_drive_installation: Mapped["GoogleDriveInstallation | None"] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    channels: Mapped[list["ProjectChannel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class GitHubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), unique=True, nullable=False
    )
    installation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="github_installation")


class GoogleDriveInstallation(Base):
    """A project's connected Google Drive folder (issue #14, piece 1).

    OAuth per-admin (mirrors GitHubInstallation's shape) — but unlike
    GitHub's long-lived JWT-derived installation tokens, Google's OAuth
    access tokens expire hourly, so the authorizing admin's `refresh_token`
    is stored to mint fresh access tokens on every sync without them
    present. Stored as plain text, matching this project's existing
    precedent (the GitHub App private key is also a plain base64 env var,
    not per-row-encrypted) — not a new regression in this piece.
    """

    __tablename__ = "google_drive_installations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), unique=True, nullable=False
    )
    folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    folder_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="google_drive_installation")


class DiscordGuild(Base):
    __tablename__ = "discord_guilds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    guild_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    channels: Mapped[list["ProjectChannel"]] = relationship(back_populates="discord_guild")


class ProjectChannel(Base):
    __tablename__ = "project_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    discord_guild_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discord_guilds.id"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authority_tier: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="channels")
    discord_guild: Mapped["DiscordGuild"] = relationship(back_populates="channels")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_project_channel_created", "project_id", "channel_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    discord_message_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    author_id: Mapped[str] = mapped_column(String(64), nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_roles: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thread_starter_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reactions: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    discussion_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discussion_units.id"), nullable=True
    )
    embedding: Mapped[list | None] = mapped_column(EmbeddingColumn, nullable=True)

    discussion_unit: Mapped["DiscussionUnit | None"] = relationship(back_populates="messages")


class DiscussionUnit(Base):
    """A grouped arc of related messages — Stage 0 (SPEC.md §5).

    Reconstruction is per-message bookkeeping done by the `bot` process as
    messages arrive; closing (inactivity/signal) and Stage 1 filtering are
    done by the `worker` process polling this table.
    """

    __tablename__ = "discussion_units"
    __table_args__ = (
        Index("ix_discussion_units_project_channel_status", "project_id", "channel_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    participant_ids: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)
    signal_close_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_embedding: Mapped[list | None] = mapped_column(EmbeddingColumn, nullable=True)

    messages: Mapped[list["Message"]] = relationship(back_populates="discussion_unit")
    candidates: Mapped[list["Candidate"]] = relationship(back_populates="discussion_unit")


class Candidate(Base):
    """Stage 1 output — a closed discussion unit flagged as decision-like.

    Tuned for recall, not precision (SPEC.md §5): flagged on any signal
    (keyword match, embedding similarity to an exemplar, or a checkmark
    reaction). No LLM involved — that's Stage 2 (Phase 4).
    """

    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    discussion_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discussion_units.id"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    matched_keywords: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)
    embedding_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reaction_signal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    discussion_unit: Mapped["DiscussionUnit"] = relationship(back_populates="candidates")


class Decision(Base):
    """LLM-extracted decision record (SPEC.md §5, §6).

    `statement_embedding`, `supersedes`, `superseded_by` are Stage 3
    (SPEC.md §5): semantic retrieval over `statement_embedding` finds
    existing active decisions a new one might relate to; an LLM classifies
    the relationship (unrelated/amendment/reversal/duplicate) and, for
    reversal/duplicate, the chain is updated here. `reconciliation` (Phase 5,
    tier-b) is populated by `app/pipeline/reconciliation.py`: embedding
    retrieval over the project's `RepoDocument` index surfaces related code/
    docs for a human to confirm — `state` is always `"unverified"` in v1
    since tier-a (concrete contradiction detection, the only path to
    `"consistent"`/`"contradiction"`) is deferred to Phase 6.

    `status` (ARCHITECTURE.md step 9): Stage 2 extraction always writes
    `"proposed"`; a human review action in `app/web/decisions.py` flips it to
    `"active"` (approve) or `"rejected"` (reject) — only `"active"` decisions
    are visible to Stage 3's supersession search or any future portal.
    `"superseded"` is set by Stage 3 on an existing decision when a new one
    reverses/duplicates it.
    """

    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    statement_embedding: Mapped[list | None] = mapped_column(EmbeddingColumn, nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    participants: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    message_ids: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authority_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="proposed", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    supersedes: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=True
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decisions.id"), nullable=True
    )
    reconciliation: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    candidate: Mapped["Candidate"] = relationship()


class RepoDocument(Base):
    """A project's ground-truth index — GitHub doc sections/code symbols
    (SPEC.md §4) and, since issue #14, Google Drive doc sections — queryable
    by the reconciliation engine (Phase 5) and, eventually, Drive
    draft-generation (issue #14, piece 2).

    Unified table rather than one per source/kind: every row is
    conceptually "a chunk of repo/doc content with an embedding," and
    reconciliation queries "find related content for this decision" once,
    not once per content type. `kind` discriminates `doc_section`
    (GitHub), `code_symbol` (GitHub), and `drive_section` (Google Drive);
    `symbol_name` and `line_start`/`line_end` only apply to
    `kind="code_symbol"`. Resync replaces a project's rows for one `kind`
    wholesale rather than diffing incrementally — scoped by `kind` so a
    Drive resync never touches a project's GitHub-sourced rows and vice
    versa.
    """

    __tablename__ = "repo_documents"
    __table_args__ = (Index("ix_repo_documents_project_kind", "project_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anchor: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(EmbeddingColumn, nullable=True)
    line_start: Mapped[int | None] = mapped_column(nullable=True)
    line_end: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLogEntry(Base):
    """Append-only pipeline activity log (SPEC.md §4, ARCHITECTURE.md step
    10) — "separates what changed from why the system proposed it."

    Unified table rather than one per stage, matching this codebase's
    established preference (`Candidate`'s signal-flag columns,
    `RepoDocument`'s single `kind` discriminator). `subject_type`/
    `subject_id` are a polymorphic reference (no FK constraint — the
    subject can be a DiscussionUnit, Candidate, or Decision) rather than a
    literal foreign key; `actor` is a denormalized string ("system" for
    pipeline-driven entries, or a user's `github_login` for human-review
    actions) so the trail survives even if the user row is later deleted.
    """

    __tablename__ = "audit_log_entries"
    __table_args__ = (
        Index("ix_audit_log_project_created", "project_id", "created_at"),
        Index("ix_audit_log_subject", "subject_type", "subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), default="system", nullable=False)
    payload: Mapped[dict] = mapped_column(JsonColumn, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
