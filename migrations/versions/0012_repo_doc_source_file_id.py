"""repo_doc_source_file_id

Revision ID: 0012_repo_doc_source_file_id
Revises: 0011_drive_draft_edit
Create Date: 2026-07-25 09:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_repo_doc_source_file_id"
down_revision: str | Sequence[str] | None = "0011_drive_draft_edit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("repo_documents", sa.Column("source_file_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("repo_documents", "source_file_id")
