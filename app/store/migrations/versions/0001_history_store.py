"""history store: series, price bars, daily IV points

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "history_series",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dataset", sa.String(8), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column(
            "extended_hours", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("tenor_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("instrument", sa.String(64), nullable=False, server_default=""),
        sa.Column("sec_type", sa.String(16)),
        sa.Column("source_instrument", sa.String(64)),
        sa.Column("covered_from", sa.DateTime(timezone=True)),
        sa.Column("covered_to", sa.DateTime(timezone=True)),
        sa.Column("synced_at", sa.DateTime(timezone=True)),
        sa.Column("sync_failed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "dataset",
            "symbol",
            "provider",
            "interval",
            "extended_hours",
            "tenor_days",
            "instrument",
            name="uq_history_series_identity",
        ),
    )
    op.create_index("ix_history_series_symbol", "history_series", ["symbol"])
    op.create_table(
        "price_bars",
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("history_series.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("bar_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("bar_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=False),
        sa.Column("high", sa.Numeric(), nullable=False),
        sa.Column("low", sa.Numeric(), nullable=False),
        sa.Column("close", sa.Numeric(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_price_bars_series_date", "price_bars", ["series_id", "bar_date"]
    )
    op.create_table(
        "iv_points_daily",
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("history_series.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("point_date", sa.Date(), primary_key=True),
        sa.Column("iv_call", sa.Numeric()),
        sa.Column("iv_put", sa.Numeric()),
        sa.Column("iv", sa.Numeric()),
    )


def downgrade() -> None:
    op.drop_table("iv_points_daily")
    op.drop_table("price_bars")
    op.drop_index("ix_history_series_symbol", table_name="history_series")
    op.drop_table("history_series")
