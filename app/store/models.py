# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""SQLAlchemy models of the history store (design D2)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class HistorySeries(Base):
    __tablename__ = "history_series"
    __table_args__ = (
        UniqueConstraint(
            "dataset",
            "symbol",
            "provider",
            "interval",
            "extended_hours",
            "tenor_days",
            "instrument",
            name="uq_history_series_identity",
        ),
        Index("ix_history_series_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String(8))  # prices | iv
    symbol: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8))
    extended_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    tenor_days: Mapped[int] = mapped_column(Integer, default=0)
    instrument: Mapped[str] = mapped_column(String(64), default="")
    sec_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_instrument: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_interval: Mapped[str | None] = mapped_column(String(8), nullable=True)
    covered_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    covered_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PriceBarRow(Base):
    __tablename__ = "price_bars"
    __table_args__ = (Index("ix_price_bars_series_date", "series_id", "bar_date"),)

    series_id: Mapped[int] = mapped_column(
        ForeignKey("history_series.id", ondelete="CASCADE"), primary_key=True
    )
    bar_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    bar_date: Mapped[date] = mapped_column(Date)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[Decimal] = mapped_column(Numeric())
    high: Mapped[Decimal] = mapped_column(Numeric())
    low: Mapped[Decimal] = mapped_column(Numeric())
    close: Mapped[Decimal] = mapped_column(Numeric())
    volume: Mapped[int] = mapped_column(BigInteger)


class EarningsSync(Base):
    """Synchronisation state per provider and scope (`calendar` or a symbol)."""

    __tablename__ = "earnings_sync"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    covered_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    covered_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EarningsEventRow(Base):
    __tablename__ = "earnings_events"
    __table_args__ = (
        Index("ix_earnings_events_provider_date", "provider", "report_date"),
        Index("ix_earnings_events_period", "provider", "symbol", "fiscal_period_end"),
    )

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(8))  # calendar | history
    report_time: Mapped[str] = mapped_column(String(8))
    date_status: Mapped[str] = mapped_column(String(10))
    reported: Mapped[bool] = mapped_column(Boolean, default=False)
    fiscal_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    eps_estimate: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    eps_actual: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    eps_surprise: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    eps_surprise_pct: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IvPointRow(Base):
    __tablename__ = "iv_points_daily"

    series_id: Mapped[int] = mapped_column(
        ForeignKey("history_series.id", ondelete="CASCADE"), primary_key=True
    )
    point_date: Mapped[date] = mapped_column(Date, primary_key=True)
    iv_call: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    iv_put: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    iv: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
