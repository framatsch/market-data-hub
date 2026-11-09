#!/usr/bin/env python
"""Compare what the equity RIC search resolves with the native index/future RICs.

Bare symbols (`SPX`, `ES`) go through `LSEGProvider._ticker_to_ric`; `I:SPX` and
`F:ES` use the native RICs from `_native_instrument` (`.SPX`, `ESc1`). This prints,
per candidate RIC, the daily summary (columns + last row) or the exact LSEG error so
a wrong native RIC can be told apart from a missing entitlement.

Run with the same environment as the service (KEYS_DB_PATH, APP_ENCRYPTION_KEY):

    python scripts/diagnostics/lseg_native_ric_check.py            # SPX ES
    python scripts/diagnostics/lseg_native_ric_check.py NDX CL ZN
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from refinitiv.data.content import historical_pricing  # noqa: E402

from app.providers.lseg import LSEGProvider, _native_instrument  # noqa: E402


def probe(provider: LSEGProvider, label: str, ric: str) -> None:
    print(f"  [{label}] RIC={ric}")
    try:
        provider._get_session()
        response = historical_pricing.summaries.Definition(
            universe=ric,
            interval=historical_pricing.Intervals.DAILY,
            count=3,
        ).get_data()
        frame = response.data.df
        if frame is None or frame.empty:
            print("    -> EMPTY (no rows)")
            return
        print(f"    -> columns: {list(frame.columns)}")
        print(f"    -> last row:\n{frame.tail(1).to_string()}")
    except Exception as exc:  # report LSEG's exact message
        print(f"    -> ERROR {type(exc).__name__}: {exc}")


def main(roots: list[str]) -> None:
    provider = LSEGProvider()
    for root in roots:
        print(f"\n=== {root} ===")
        try:
            searched = provider._ticker_to_ric(root)
        except Exception as exc:
            searched = None
            print(f"  search for bare '{root}': ERROR {type(exc).__name__}: {exc}")
        if searched:
            print(f"  search for bare '{root}' -> {searched}")
            probe(provider, "bare (search)", searched)
        for sec_type in ("index", "future"):
            native = _native_instrument(root, sec_type)
            if native and native != searched:
                probe(provider, f"{sec_type} (native)", native)


if __name__ == "__main__":
    main(sys.argv[1:] or ["SPX", "ES"])
