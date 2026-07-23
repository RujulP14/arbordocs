"""user_verified

Revision ID: 0008_user_verified
Revises: 0007_audit_log
Create Date: 2026-07-23 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_user_verified"
down_revision: str | Sequence[str] | None = "0007_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE users SET verified = true WHERE is_admin = true")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "verified")
