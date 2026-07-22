"""decision_reconciliation

Revision ID: 0006_decision_reconciliation
Revises: 0005_github_content_index
Create Date: 2026-07-22 20:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0006_decision_reconciliation"
down_revision: str | Sequence[str] | None = "0005_github_content_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "decisions",
        sa.Column("reconciliation", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("decisions", "reconciliation")
