"""drive_draft_edit

Revision ID: 0011_drive_draft_edit
Revises: 0010_google_drive_installation
Create Date: 2026-07-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_drive_draft_edit"
down_revision: str | Sequence[str] | None = "0010_google_drive_installation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "drive_draft_edits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("repo_document_id", sa.UUID(), nullable=False),
        sa.Column("draft_content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["repo_document_id"], ["repo_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("drive_draft_edits")
