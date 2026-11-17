"""earnings: events and synchronisation state

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "earnings_sync",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("scope", sa.String(64), primary_key=True),
        sa.Column("covered_from", sa.Date()),
        sa.Column("covered_to", sa.Date()),
        sa.Column("synced_at", sa.DateTime(timezone=True)),
        sa.Column("sync_failed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "earnings_events",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("symbol", sa.String(64), primary_key=True),
        sa.Column("report_date", sa.Date(), primary_key=True),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("report_time", sa.String(8), nullable=False),
        sa.Column("date_status", sa.String(10), nullable=False),
        sa.Column("reported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fiscal_period_end", sa.Date()),
        sa.Column("eps_estimate", sa.Numeric()),
        sa.Column("eps_actual", sa.Numeric()),
        sa.Column("eps_surprise", sa.Numeric()),
        sa.Column("eps_surprise_pct", sa.Numeric()),
        sa.Column("currency", sa.String(8)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_earnings_events_provider_date",
        "earnings_events",
        ["provider", "report_date"],
    )
    op.create_index(
        "ix_earnings_events_period",
        "earnings_events",
        ["provider", "symbol", "fiscal_period_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_earnings_events_period", table_name="earnings_events")
    op.drop_index("ix_earnings_events_provider_date", table_name="earnings_events")
    op.drop_table("earnings_events")
    op.drop_table("earnings_sync")
