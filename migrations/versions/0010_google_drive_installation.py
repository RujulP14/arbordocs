"""google_drive_installation

Revision ID: 0010_google_drive_installation
Revises: 0009_thread_starter_message
Create Date: 2026-07-24 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_google_drive_installation"
down_revision: str | Sequence[str] | None = "0009_thread_starter_message"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "google_drive_installations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("folder_id", sa.String(length=255), nullable=False),
        sa.Column("folder_name", sa.String(length=255), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("google_drive_installations")
