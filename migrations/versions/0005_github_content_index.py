"""github_content_index

Revision ID: 0005_github_content_index
Revises: 0004_supersession_tracking
Create Date: 2026-07-22 19:28:02.322084

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_github_content_index"
down_revision: str | Sequence[str] | None = "0004_supersession_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "repo_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("symbol_name", sa.String(length=255), nullable=True),
        sa.Column("anchor", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.vector.VECTOR(dim=384).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_documents_project_kind", "repo_documents", ["project_id", "kind"], unique=False)
    op.add_column(
        "github_installations", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("github_installations", "last_synced_at")
    op.drop_index("ix_repo_documents_project_kind", table_name="repo_documents")
    op.drop_table("repo_documents")
