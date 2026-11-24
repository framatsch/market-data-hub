"""Contract-selection rules shared by both IBKR futures-option transports."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.options import OptionChain, OptionQuote
from app.providers.ibkr_common import FUTURES_EXCHANGES
from app.utils.errors import CapabilityNotSupportedError, DataValidationError
from app.utils.symbols import canonical_symbol

# Verified standard series codes, not guesses based on the future's root or month.
REGULAR_FUTURES_OPTION_CLASSES = {"ES": "ES", "CL": "LO"}


def futures_option_exchange(root: str, provider: str) -> str:
    if root not in REGULAR_FUTURES_OPTION_CLASSES:
        error = CapabilityNotSupportedError(
            provider,
            "option_chain",
            sec_type="future",
            supported=sorted(REGULAR_FUTURES_OPTION_CLASSES),
        )
        error.details["root"] = root
        raise error
    return FUTURES_EXCHANGES[root]


def select_trading_class(
    root: str, expiry: date, classes: Iterable[str], requested: str | None
) -> str | None:
    available = {value.upper() for value in classes if value}
    if requested:
        requested = requested.upper()
        return requested if requested in available else None
    regular = REGULAR_FUTURES_OPTION_CLASSES.get(root)
    if regular in available:
        return regular
    if len(available) > 1:
        raise DataValidationError(
            "Multiple futures option trading classes; specify trading_class",
            details={
                "symbol": canonical_symbol(root, "future"),
                "expiry": expiry.isoformat(),
                "trading_classes": sorted(available),
            },
        )
    return next(iter(available), None)


@dataclass(frozen=True, slots=True)
class FuturesOptionTerms:
    trading_class: str
    exchange: str
    multiplier: Decimal | None

    def chain(
        self,
        root: str,
        expiry: date,
        provider: str,
        options: list[OptionQuote],
        *,
        underlying_contract: str | None = None,
        underlying_price: Decimal | None = None,
    ) -> OptionChain:
        return OptionChain(
            underlying_symbol=canonical_symbol(root, "future"),
            expiry=expiry,
            options=options,
            provider=provider,
            underlying_contract=underlying_contract,
            underlying_price=underlying_price,
            trading_class=self.trading_class,
            exchange=self.exchange,
            multiplier=self.multiplier,
        )
