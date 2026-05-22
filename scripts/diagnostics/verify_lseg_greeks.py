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
Verify LSEG Greeks availability for production assessment.

Tests:
1. Field availability in pricing.Definition()
2. Field availability in search.Definition()
3. Greeks quality for liquid options (SPY)
4. Comparison between Search API vs Pricing API

Usage:
    python scripts/diagnostics/verify_lseg_greeks.py
"""
import os
import sys
from pathlib import Path
from datetime import date, timedelta, datetime
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

import refinitiv.data as rd
from refinitiv.data.content import search, pricing, historical_pricing


def create_session():
    """Create LSEG session."""
    print("\n" + "="*80)
    print("📡 Creating LSEG Session")
    print("="*80)

    try:
        session = rd.session.platform.Definition(
            app_key=os.getenv('LSEG_APP_KEY'),
            grant=rd.session.platform.GrantPassword(
                username=os.getenv('LSEG_USERNAME'),
                password=os.getenv('LSEG_PASSWORD')
            ),
            signon_control=True
        ).get_session()

        session.open()
        rd.session.set_default(session)

        print("✅ Session created successfully")
        print(f"   Username: {os.getenv('LSEG_USERNAME')}")
        print(f"   Session state: {session.open_state}")
        return session

    except Exception as e:
        print(f"❌ Session failed: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_pricing_api_greeks(ric_list: list):
    """Test 1: Pricing API Greeks availability."""
    print("\n" + "="*80)
    print("TEST 1: Pricing API - pricing.Definition()")
    print("="*80)

    try:
        print(f"\n📊 Requesting Greeks for {len(ric_list)} option RICs...")
        print(f"   Sample RICs: {ric_list[:3]}")

        # Request ALL possible Greek fields
        fields = [
            'RIC', 'BID', 'ASK', 'TRDPRC_1', 'LAST',
            # IV fields
            'IMPVOL_1', 'IMP_VOLT', 'IV', 'IMPLIED_VOL', 'IMPLIED_VOLATILITY',
            # Greek fields
            'DELTA', 'GREEK_DELTA', 'THEO_DELTA',
            'GAMMA', 'GREEK_GAMMA', 'THEO_GAMMA',
            'VEGA', 'GREEK_VEGA', 'THEO_VEGA',
            'THETA', 'GREEK_THETA', 'THEO_THETA',
            # Other
            'ACVOL_1', 'OPEN_INT'
        ]

        response = pricing.Definition(
            universe=ric_list,
            fields=fields
        ).get_data()

        df = getattr(response.data, 'df', None)

        if df is None or df.empty:
            print("❌ Pricing API returned empty DataFrame")
            return None

        print(f"\n✅ Pricing API returned {len(df)} rows")
        print(f"\n📋 Available columns ({len(df.columns)}):")
        print(f"   {list(df.columns)}")

        # Check Greek field presence
        print("\n🎯 Greek Field Analysis:")
        greek_fields = {
            'IV': ['IMPVOL_1', 'IMP_VOLT', 'IV', 'IMPLIED_VOL', 'IMPLIED_VOLATILITY'],
            'DELTA': ['DELTA', 'GREEK_DELTA', 'THEO_DELTA'],
            'GAMMA': ['GAMMA', 'GREEK_GAMMA', 'THEO_GAMMA'],
            'VEGA': ['VEGA', 'GREEK_VEGA', 'THEO_VEGA'],
            'THETA': ['THETA', 'GREEK_THETA', 'THEO_THETA']
        }

        results = {}
        for greek_name, possible_fields in greek_fields.items():
            found_fields = [f for f in possible_fields if f in df.columns]
            if found_fields:
                field = found_fields[0]
                non_null = df[field].notna().sum()
                total = len(df)
                pct = (non_null / total * 100) if total > 0 else 0
                results[greek_name] = {
                    'field': field,
                    'populated': non_null,
                    'total': total,
                    'percent': pct
                }
                print(f"  {greek_name:10s}: ✅ '{field}' - {non_null}/{total} ({pct:.1f}%) populated")

                # Show sample values
                sample = df[field].dropna().head(3)
                if not sample.empty:
                    print(f"              Sample values: {list(sample.values)}")
            else:
                results[greek_name] = None
                print(f"  {greek_name:10s}: ❌ No field found in columns")

        return df, results

    except Exception as e:
        print(f"\n❌ Pricing API failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None, {}


def test_search_api_greeks(symbol: str, expiry_date: date):
    """Test 2: Search API Greeks availability."""
    print("\n" + "="*80)
    print("TEST 2: Search API - search.Definition(EQUITY_DERIVATIVE_QUOTES)")
    print("="*80)

    try:
        expiry_iso = expiry_date.strftime('%Y-%m-%d')
        print(f"\n📊 Searching options for {symbol}, expiry {expiry_iso}")

        response = search.Definition(
            view=search.Views.EQUITY_DERIVATIVE_QUOTES,
            query=symbol,
            filter=f"ExpiryDate eq {expiry_iso}",
            select="RIC, DisplayName, StrikePrice, ExpiryDate, OptionType, BID, ASK, TRDPRC_1, IV, IMPVOL_1, DELTA, GAMMA, VEGA, THETA, ACVOL_1, OPEN_INT",
            top=20
        ).get_data()

        df = getattr(response.data, 'df', None)

        if df is None or df.empty:
            print("❌ Search API returned empty DataFrame")
            return None, []

        print(f"\n✅ Search API returned {len(df)} options")
        print(f"\n📋 Available columns ({len(df.columns)}):")
        print(f"   {list(df.columns)}")

        # Show sample data
        print("\n📄 Sample option data (first 3):")
        for idx, row in df.head(3).iterrows():
            ric = row.get('RIC', 'N/A')
            strike = row.get('StrikePrice', 'N/A')
            opt_type = row.get('OptionType', 'N/A')
            print(f"   {ric}: Strike={strike}, Type={opt_type}")

        # Check Greek field presence
        print("\n🎯 Greek Field Analysis:")
        greek_fields = ['IV', 'IMPVOL_1', 'DELTA', 'GAMMA', 'VEGA', 'THETA']

        results = {}
        for field in greek_fields:
            if field in df.columns:
                non_null = df[field].notna().sum()
                total = len(df)
                pct = (non_null / total * 100) if total > 0 else 0
                results[field] = {
                    'populated': non_null,
                    'total': total,
                    'percent': pct
                }
                print(f"  {field:10s}: {non_null}/{total} ({pct:.1f}%) populated")

                # Show sample values
                sample = df[field].dropna().head(3)
                if not sample.empty:
                    print(f"              Sample: {list(sample.values)}")
            else:
                results[field] = None
                print(f"  {field:10s}: ❌ Not in columns")

        # Extract RIC list for pricing API test
        ric_list = df['RIC'].tolist() if 'RIC' in df.columns else []

        return df, ric_list, results

    except Exception as e:
        print(f"\n❌ Search API failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None, [], {}


def compare_apis(search_df, pricing_df):
    """Test 3: Compare Search vs Pricing API data."""
    print("\n" + "="*80)
    print("TEST 3: API Comparison - Which source has better Greeks?")
    print("="*80)

    if search_df is None or pricing_df is None:
        print("⚠️ Cannot compare - one or both APIs failed")
        return

    # Check overlap
    search_rics = set(search_df['RIC'].tolist()) if 'RIC' in search_df.columns else set()
    pricing_rics = set(pricing_df['RIC'].tolist()) if 'RIC' in pricing_df.columns else set()
    overlap = search_rics & pricing_rics

    print(f"\n📊 Data Overlap:")
    print(f"  Search RICs:  {len(search_rics)}")
    print(f"  Pricing RICs: {len(pricing_rics)}")
    print(f"  Overlap:      {len(overlap)} ({len(overlap)/max(len(search_rics),1)*100:.1f}%)")

    if not overlap:
        print("⚠️ No overlapping RICs to compare")
        return

    # Compare Greeks for overlapping RICs
    print("\n🎯 Greeks Comparison (Search vs Pricing):")

    greek_map = {
        'IV': ('IV', 'IMPVOL_1'),
        'DELTA': ('DELTA', 'DELTA'),
        'GAMMA': ('GAMMA', 'GAMMA'),
        'VEGA': ('VEGA', 'VEGA'),
        'THETA': ('THETA', 'THETA')
    }

    for greek_name, (search_field, pricing_field) in greek_map.items():
        search_has = search_field in search_df.columns
        pricing_has = pricing_field in pricing_df.columns

        if search_has and pricing_has:
            # Count populated values
            search_pop = search_df[search_field].notna().sum()
            pricing_pop = pricing_df[pricing_field].notna().sum()

            print(f"\n  {greek_name}:")
            print(f"    Search:  {search_pop}/{len(search_df)} populated")
            print(f"    Pricing: {pricing_pop}/{len(pricing_df)} populated")

            # Winner
            if pricing_pop > search_pop:
                print(f"    ✅ Winner: Pricing API (+{pricing_pop - search_pop} more values)")
            elif search_pop > pricing_pop:
                print(f"    ✅ Winner: Search API (+{search_pop - pricing_pop} more values)")
            else:
                print(f"    ⚖️  Tie: Both have {search_pop} values")
        else:
            print(f"\n  {greek_name}:")
            print(f"    Search:  {'✅ Available' if search_has else '❌ Missing'}")
            print(f"    Pricing: {'✅ Available' if pricing_has else '❌ Missing'}")


def generate_summary(search_results, pricing_results):
    """Generate final summary and recommendation."""
    print("\n" + "="*80)
    print("📊 FINAL SUMMARY & RECOMMENDATION")
    print("="*80)

    print("\n🔍 Greeks Availability Assessment:")

    # Check if any API provides Greeks
    search_has_greeks = any(
        r and r.get('populated', 0) > 0
        for r in search_results.values()
        if r is not None
    )
    pricing_has_greeks = any(
        r and r.get('populated', 0) > 0
        for r in pricing_results.values()
        if r is not None
    )

    print(f"\n  Search API Greeks:  {'✅ Available' if search_has_greeks else '❌ Not Available'}")
    print(f"  Pricing API Greeks: {'✅ Available' if pricing_has_greeks else '❌ Not Available'}")

    # Calculate average population rate
    if pricing_has_greeks:
        avg_pop = sum(
            r['percent'] for r in pricing_results.values()
            if r is not None
        ) / len([r for r in pricing_results.values() if r is not None])
        print(f"\n  Average Greeks Population Rate: {avg_pop:.1f}%")

    # Recommendation
    print("\n💡 RECOMMENDATION:")

    if pricing_has_greeks and avg_pop > 80:
        print("\n  ✅ LSEG provides reliable Greeks (>80% populated)")
        print("     → Action: Remove Black-Scholes fallback code")
        print("     → Keep: Error handling for missing data")
        print("     → Simplify: LSEGProvider options implementation")
    elif pricing_has_greeks and avg_pop > 50:
        print("\n  ⚠️  LSEG provides Greeks but inconsistently (50-80% populated)")
        print("     → Action: Keep LSEG for options BUT add warning")
        print("     → Keep: Black-Scholes fallback for missing Greeks")
        print("     → Document: Data quality limitations")
    elif search_has_greeks:
        print("\n  ⚠️  LSEG provides Greeks only via Search API")
        print("     → Action: Use Search API as primary source")
        print("     → Remove: Pricing API calls for Greeks")
        print("     → Simplify: Single-source implementation")
    else:
        print("\n  ❌ LSEG does NOT provide reliable Greeks")
        print("     → Action: REMOVE LSEGProvider options support")
        print("     → Reason: Black-Scholes fallback too inaccurate (30-50% error)")
        print("     → Strategy: Use IBKR exclusively for options")
        print("     → Use LSEG: Only for stock prices, company data, news")

    print("\n" + "="*80)


def main():
    """Run all verification tests."""
    print("\n" + "="*80)
    print("🧪 LSEG Greeks Availability Verification")
    print("="*80)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # Create session
        session = create_session()

        # Test parameters: SPY options expiring in ~30 days (highly liquid)
        symbol = "SPY"
        expiry_date = date.today() + timedelta(days=30)
        # Round to next Friday (options typically expire on Fridays)
        days_ahead = (4 - expiry_date.weekday()) % 7
        expiry_date = expiry_date + timedelta(days=days_ahead)

        print(f"\n🎯 Test Parameters:")
        print(f"   Symbol: {symbol} (highly liquid)")
        print(f"   Expiry: {expiry_date} (~30 DTE)")

        # Test 1: Search API
        search_df, ric_list, search_results = test_search_api_greeks(symbol, expiry_date)

        if not ric_list:
            print("\n❌ Cannot proceed: No option RICs found")
            return

        # Test 2: Pricing API (use RICs from search)
        pricing_df, pricing_results = test_pricing_api_greeks(ric_list[:20])  # Limit to 20 for speed

        # Test 3: Compare APIs
        compare_apis(search_df, pricing_df)

        # Test 4: Generate summary
        generate_summary(search_results, pricing_results)

        # Close session
        if session:
            session.close()
            print("\n✅ Session closed")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
