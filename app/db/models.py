import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB on Postgres (prod/dev), plain JSON elsewhere (e.g. sqlite in tests).
JsonColumn = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    github_login: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    channels: Mapped[list["ProjectChannel"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class GitHubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), unique=True, nullable=False
    )
    installation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="github_installation")


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
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
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
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    discord_message_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    author_id: Mapped[str] = mapped_column(String(64), nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_roles: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reactions: Mapped[list] = mapped_column(JsonColumn, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
