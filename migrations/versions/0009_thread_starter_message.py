"""thread_starter_message

Revision ID: 0009_thread_starter_message
Revises: 0008_user_verified
Create Date: 2026-07-24 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_thread_starter_message"
down_revision: str | Sequence[str] | None = "0008_user_verified"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("messages", sa.Column("thread_starter_message_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("messages", "thread_starter_message_id")
