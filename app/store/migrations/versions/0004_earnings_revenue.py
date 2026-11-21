"""earnings: revenue fields and day-sync invalidation

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "earnings_events", sa.Column("revenue_estimate", sa.Numeric(), nullable=True)
    )
    op.add_column(
        "earnings_events", sa.Column("revenue_actual", sa.Numeric(), nullable=True)
    )
    op.add_column(
        "earnings_sync",
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("earnings_sync", "invalidated_at")
    op.drop_column("earnings_events", "revenue_actual")
    op.drop_column("earnings_events", "revenue_estimate")
