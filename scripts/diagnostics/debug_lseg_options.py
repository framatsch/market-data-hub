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

#!/usr/bin/env python3
"""
Debug script to explore Refinitiv EQUITY_DERIVATIVE APIs for options.
Run this to discover available fields, expirations, and strikes.
"""

import sys

# Add project to path
sys.path.insert(0, '/home/fscheffold/private/market-data-hub')

from app.config import settings

print("="*80)
print("REFINITIV EQUITY DERIVATIVE API EXPLORATION")
print("="*80)

try:
    import refinitiv.data as rd
    from refinitiv.data.content import search, historical_pricing, derivatives

    print("\n✅ Refinitiv SDK imported successfully")
    print(f"   APP_KEY configured: {bool(settings.LSEG_APP_KEY)}")
    print(f"   USERNAME configured: {bool(settings.LSEG_USERNAME)}")
    print(f"   PASSWORD configured: {bool(settings.LSEG_PASSWORD)}")

    # Initialize session
    print("\n📡 Connecting to Refinitiv...")
    session = rd.session.platform.Definition(
        app_key=settings.LSEG_APP_KEY,
        grant=rd.session.platform.GrantPassword(
            username=settings.LSEG_USERNAME,
            password=settings.LSEG_PASSWORD
        ),
        signon_control=True
    ).get_session()

    session.open()
    rd.session.set_default(session)
    print("✅ Session opened")

    # Test 1: Get RIC for AAPL
    print("\n" + "="*80)
    print("TEST 1: GET RIC FOR AAPL")
    print("="*80)

    symbol = "AAPL"
    response = search.Definition(
        view=search.Views.EQUITY_QUOTES,
        query=symbol,
        filter=f"TickerSymbol eq '{symbol}'",
        select="RIC, DisplayName, TickerSymbol",
        top=1
    ).get_data()

    if response.data.df is not None and not response.data.df.empty:
        ric = response.data.df['RIC'].iloc[0]
        print(f"✅ RIC for {symbol}: {ric}")
    else:
        print(f"❌ Could not get RIC for {symbol}")
        sys.exit(1)

    # Test 2: Search EQUITY_DERIVATIVE_INSTRUMENTS for options
    print("\n" + "="*80)
    print("TEST 2: SEARCH EQUITY_DERIVATIVE_INSTRUMENTS")
    print("="*80)

    try:
        print(f"\nSearching for derivatives of {symbol} (RIC: {ric})...")
        response = search.Definition(
            view=search.Views.EQUITY_DERIVATIVE_INSTRUMENTS,
            query=symbol,
            select="RIC, DisplayName, TickerSymbol, StrikePrice, ExpiryDate, OptionType",
            top=50
        ).get_data()

        if response.data.df is not None and not response.data.df.empty:
            print(f"✅ Found {len(response.data.df)} derivative instruments")
            print(f"\nColumns available: {list(response.data.df.columns)}")
            print("\nFirst 10 rows:")
            print(response.data.df.head(10).to_string())
        else:
            print("❌ No results from EQUITY_DERIVATIVE_INSTRUMENTS search")
    except Exception as e:
        print(f"⚠️  EQUITY_DERIVATIVE_INSTRUMENTS search failed: {e}")

    # Test 3: Try EQUITY_DERIVATIVE_QUOTES
    print("\n" + "="*80)
    print("TEST 3: EQUITY_DERIVATIVE_QUOTES VIEW")
    print("="*80)

    try:
        print(f"\nTrying EQUITY_DERIVATIVE_QUOTES with universe={ric}...")
        response = search.Definition(
            view=search.Views.EQUITY_DERIVATIVE_QUOTES,
            query=symbol,
            select="RIC, DisplayName, BID, ASK, TRDPRC_1, IV, DELTA, GAMMA, VEGA, THETA",
            top=20
        ).get_data()

        if response.data.df is not None and not response.data.df.empty:
            print(f"✅ Found {len(response.data.df)} quotes")
            print(f"\nColumns available: {list(response.data.df.columns)}")
            print("\nFirst 5 rows:")
            print(response.data.df.head(5).to_string())
        else:
            print("❌ No results from EQUITY_DERIVATIVE_QUOTES search")
    except Exception as e:
        print(f"⚠️  EQUITY_DERIVATIVE_QUOTES search failed: {e}")

    # Test 4: Check what Views are available
    print("\n" + "="*80)
    print("TEST 4: AVAILABLE SEARCH VIEWS")
    print("="*80)

    print("\nAvailable search.Views:")
    views = [attr for attr in dir(search.Views) if not attr.startswith('_')]
    for i, view in enumerate(views, 1):
        print(f"  {i:2d}. {view}")

    # Check if EQUITY_DERIVATIVE exists
    if hasattr(search.Views, 'EQUITY_DERIVATIVE_INSTRUMENTS'):
        print("\n✅ EQUITY_DERIVATIVE_INSTRUMENTS exists")
    else:
        print("\n❌ EQUITY_DERIVATIVE_INSTRUMENTS not found")

    if hasattr(search.Views, 'EQUITY_DERIVATIVE_QUOTES'):
        print("✅ EQUITY_DERIVATIVE_QUOTES exists")
    else:
        print("❌ EQUITY_DERIVATIVE_QUOTES not found")

    # Test 5: Try raw universe parameter
    print("\n" + "="*80)
    print("TEST 5: HISTORICAL_PRICING WITH UNIVERSE=RIC FOR OPTIONS")
    print("="*80)

    try:
        # Try to get chain expansion (like options chains)
        print(f"\nTrying discover.chain_expansion for {ric}...")
        response = rd.discover.chain_expansion(universe=ric).get_data()

        if response.data.df is not None and not response.data.df.empty:
            print(f"✅ Chain expansion found {len(response.data.df)} contracts")
            print(f"\nColumns: {list(response.data.df.columns)}")
            print("\nFirst 5 rows:")
            print(response.data.df.head(5).to_string())
        else:
            print("❌ No results from chain_expansion")
    except Exception as e:
        print(f"⚠️  chain_expansion failed: {e}")

    print("\n" + "="*80)
    print("EXPLORATION COMPLETE")
    print("="*80)

    session.close()

except ImportError:
    print("❌ refinitiv.data not installed")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
