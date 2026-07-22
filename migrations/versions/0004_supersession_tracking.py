"""supersession_tracking

Revision ID: 0004_supersession_tracking
Revises: 0003_decision_extraction
Create Date: 2026-07-22 18:46:28.874291

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_supersession_tracking"
down_revision: str | Sequence[str] | None = "0003_decision_extraction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "decisions",
        sa.Column(
            "statement_embedding",
            pgvector.sqlalchemy.vector.VECTOR(dim=384).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
    op.add_column("decisions", sa.Column("supersedes", sa.UUID(), nullable=True))
    op.add_column("decisions", sa.Column("superseded_by", sa.UUID(), nullable=True))
    op.create_foreign_key("decisions_supersedes_fkey", "decisions", "decisions", ["supersedes"], ["id"])
    op.create_foreign_key("decisions_superseded_by_fkey", "decisions", "decisions", ["superseded_by"], ["id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("decisions_superseded_by_fkey", "decisions", type_="foreignkey")
    op.drop_constraint("decisions_supersedes_fkey", "decisions", type_="foreignkey")
    op.drop_column("decisions", "superseded_by")
    op.drop_column("decisions", "supersedes")
    op.drop_column("decisions", "statement_embedding")
