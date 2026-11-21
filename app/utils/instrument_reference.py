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


"""Curated reference data for well-known indices and ETFs.

Providers deliver names for ETFs but no sector or description, and none of them serves
indices. This table backs `GET /companies/{symbol}` for those instruments so consumers
can label `I:SPX` or `XLK` without keeping their own copy.
"""

from dataclasses import dataclass

from app.models.company import CompanyProfile
from app.utils.symbols import ParsedSymbol, SecType

REFERENCE_PROVIDER = "reference"


@dataclass(frozen=True, slots=True)
class InstrumentReference:
    name: str
    description: str
    sector: str | None = None

    def profile(self, root: str) -> CompanyProfile:
        return CompanyProfile(
            symbol=root,
            name=self.name,
            description=self.description,
            exchange="",
            currency="USD",
            sector=self.sector,
            provider=REFERENCE_PROVIDER,
        )


def _sector_etf(name: str, sector: str) -> InstrumentReference:
    return InstrumentReference(
        name=f"{name} Select Sector SPDR Fund",
        description=f"Select Sector SPDR ETF holding the {sector} stocks of the S&P 500.",
        sector=sector,
    )


_REFERENCE: dict[tuple[SecType, str], InstrumentReference] = {
    ("index", "SPX"): InstrumentReference(
        "S&P 500 Index",
        "Market-cap-weighted index of 500 large US companies; the main benchmark of the US stock market.",
    ),
    ("index", "NDX"): InstrumentReference(
        "Nasdaq-100 Index",
        "Index of the 100 largest non-financial companies listed on the Nasdaq; technology-heavy.",
    ),
    ("index", "DJX"): InstrumentReference(
        "Dow Jones Industrial Average (DJX, 1/100)",
        "Price-weighted index of 30 large US companies; DJX is the Cboe options symbol at 1/100 of the index level.",
    ),
    ("index", "RUT"): InstrumentReference(
        "Russell 2000 Index",
        "Market-cap-weighted index of about 2,000 US small-cap companies.",
    ),
    ("index", "VIX"): InstrumentReference(
        "Cboe Volatility Index",
        "Expected 30-day volatility of the S&P 500 derived from SPX option prices; not directly tradable.",
    ),
    ("etf", "SPY"): InstrumentReference(
        "SPDR S&P 500 ETF Trust", "ETF tracking the S&P 500 Index."
    ),
    ("etf", "QQQ"): InstrumentReference(
        "Invesco QQQ Trust", "ETF tracking the Nasdaq-100 Index."
    ),
    ("etf", "DIA"): InstrumentReference(
        "SPDR Dow Jones Industrial Average ETF Trust",
        "ETF tracking the Dow Jones Industrial Average.",
    ),
    ("etf", "IWM"): InstrumentReference(
        "iShares Russell 2000 ETF", "ETF tracking the Russell 2000 Index."
    ),
    ("etf", "XLK"): _sector_etf("Technology", "Information Technology"),
    ("etf", "XLF"): _sector_etf("Financial", "Financials"),
    ("etf", "XLE"): _sector_etf("Energy", "Energy"),
    ("etf", "XLV"): _sector_etf("Health Care", "Health Care"),
    ("etf", "XLI"): _sector_etf("Industrial", "Industrials"),
    ("etf", "XLY"): _sector_etf("Consumer Discretionary", "Consumer Discretionary"),
    ("etf", "XLP"): _sector_etf("Consumer Staples", "Consumer Staples"),
    ("etf", "XLU"): _sector_etf("Utilities", "Utilities"),
    ("etf", "XLB"): _sector_etf("Materials", "Materials"),
    ("etf", "XLRE"): _sector_etf("Real Estate", "Real Estate"),
    ("etf", "XLC"): _sector_etf("Communication Services", "Communication Services"),
}


def reference_for(symbol: ParsedSymbol) -> InstrumentReference | None:
    """Reference entry of a parsed symbol; a bare ticker of type stock matches ETFs too."""
    kinds: tuple[SecType, ...] = (
        ("etf",) if symbol.sec_type == "stock" else (symbol.sec_type,)
    )
    for kind in kinds:
        if (entry := _REFERENCE.get((kind, symbol.root))) is not None:
            return entry
    return None
