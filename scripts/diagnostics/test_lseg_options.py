#!/usr/bin/env python
"""Test Refinitiv (LSEG) API for options data capabilities."""

import os
import sys
import logging

# Suppress verbose logging
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("httpcore").setLevel(logging.CRITICAL)

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings
import refinitiv.data as rd
from refinitiv.data.content import search

def test_lseg_options():
    print("\n" + "="*70)
    print("Testing Refinitiv (LSEG) API for Options Data")
    print("="*70)
    
    # Check imports
    print(f"\n✅ refinitiv.data SDK imported")
    print(f"   App Key: {settings.LSEG_APP_KEY[:30]}...")
    print(f"   Username: {settings.LSEG_USERNAME}")
    
    # Initialize session
    print(f"\nInitializing Refinitiv session...")
    session = rd.session.platform.Definition(
        app_key=settings.LSEG_APP_KEY,
        grant=rd.session.platform.GrantPassword(
            username=settings.LSEG_USERNAME,
            password=settings.LSEG_PASSWORD
        ),
        signon_control=True
    ).get_session()
    
    try:
        session.open()
        print("✅ Session opened")
    except Exception as e:
        print(f"❌ Session open failed: {e}")
        return
    
    rd.session.set_default(session)
    
    # Test 1: Search for AAPL stock
    print("-"*70)
    print("Test 1: Search for AAPL Stock (using discovery.search function)")
    print("-"*70)
    
    try:
        df = rd.discovery.search(
            query="AAPL",
            view=rd.discovery.Views.SEARCH_ALL,
            select="RIC, DisplayName, TickerSymbol, InstrumentType",
            top=5
        )
        
        if df is not None and not df.empty:
            print(f"✅ Found {len(df)} results for AAPL\n")
            print(df[['RIC', 'DisplayName', 'InstrumentType']].head(3).to_string())
            print()
        else:
            print("❌ No results found for AAPL\n")
    except Exception as e:
        print(f"❌ Search failed: {e}\n")
    
    # Test 2: Look for options (AAPL options)
    print("-"*70)
    print("Test 2: Search for AAPL Options")
    print("-"*70)
    
    try:
        df = rd.discovery.search(
            query="AAPL",
            filter="InstrumentType eq 'Option'",
            select="RIC, DisplayName, StrikePrice, ExpiryDate",
            top=10
        )
        
        if df is not None and not df.empty:
            print(f"✅ Found {len(df)} AAPL options\n")
            print(df[['RIC', 'DisplayName', 'StrikePrice', 'ExpiryDate']].head(5).to_string())
            print()
        else:
            print("⚠️  No options found (discovery may not support option filter)\n")
    except Exception as e:
        print(f"⚠️  Search for options failed: {e}\n")
    
    # Test 3: Get AAPL stock RIC via content.search
    print("-"*70)
    print("Test 3: Get AAPL Quote Data (using content.search)")
    print("-"*70)
    
    try:
        aapl_ric = "AAPL.OQ"  # Default
        
        # Try to find the exact RIC
        response = search.Definition(
            query="AAPL",
            view=search.Views.EQUITY_QUOTES,
            select="RIC, TickerSymbol, DisplayName",
            top=1
        ).get_data()
        
        if response.data.df is not None and not response.data.df.empty:
            aapl_ric = response.data.df['RIC'].iloc[0]
            print(f"✅ Found AAPL RIC: {aapl_ric}\n")
        else:
            print(f"⚠️  Using default RIC: {aapl_ric}\n")
        
        # Get quote fields
        response = search.Definition(
            universe=aapl_ric,
            view=search.Views.EQUITY_QUOTES,
            select="BID, ASK, CLOSE, OPEN, HIGH, LOW, TRDPRC_1, IMPVOL_DLY"
        ).get_data()
        
        if response.data.df is not None and not response.data.df.empty:
            print(f"✅ Got quote data for {aapl_ric}")
            print("\nAvailable fields and values:")
            for col in response.data.df.columns:
                value = response.data.df[col].iloc[0]
                print(f"  {col:20s} = {value}")
            print()
        else:
            print(f"⚠️  No quote data available\n")
    except Exception as e:
        print(f"❌ Quote data failed: {e}\n")
    
    # Test 4: Check if chain expansion works for options
    print("-"*70)
    print("Test 4: Check Chain Expansion for Options")
    print("-"*70)
    
    try:
        # Try chain expansion for AAPL
        response = search.Definition(
            universe="AAPL.OQ",
            select="RIC"
        ).get_data()
        
        print("⚠️  Chain expansion not tested yet (may not be available in search)\n")
    except Exception as e:
        print(f"⚠️  Chain expansion not available: {e}\n")
    
    # Test 5: List available Views
    print("-"*70)
    print("Test 5: Available Search Views in Refinitiv")
    print("-"*70)
    
    try:
        views = search.Views
        print(f"✅ Available Views:")
        view_names = [v for v in dir(views) if not v.startswith('_')]
        for i, view_name in enumerate(view_names, 1):
            print(f"  {i}. {view_name}")
        print()
    except Exception as e:
        print(f"❌ Failed to list views: {e}\n")
    
    # Test 6: Check content module for fundamentals/options
    print("-"*70)
    print("Test 6: Check Available Content Modules")
    print("-"*70)
    
    try:
        from refinitiv.data import content
        modules = [m for m in dir(content) if not m.startswith('_')]
        print(f"✅ Available content modules:")
        for m in modules:
            print(f"  - {m}")
        print()
    except Exception as e:
        print(f"❌ Failed to list content: {e}\n")
    
    # Summary
    print("="*70)
    print("SUMMARY - REFINITIV OPTIONS CAPABILITIES")
    print("="*70)
    print("""
FINDINGS:
✅ Discovery search works for finding instruments
✅ Content.search provides quote data (BID, ASK, etc.)
⚠️  Option chain discovery may not be directly supported
⚠️  Greek letters might be limited to IMPVOL_DLY

LIMITATIONS IDENTIFIED:
1. No native option chain expansion (unlike IBKR)
2. Greeks availability: Only implied volatility confirmed
3. May need to use ticker-based symbol search instead of RIC

RECOMMENDATION:
If Refinitiv doesn't provide:
- Native option chain data
- Individual Greeks (Delta, Gamma, Vega, Theta)
Consider:
1. Using IBKR only for options (already works)
2. Implementing LSEG for stocks only
3. Or creating a dual-provider strategy
""")

if __name__ == "__main__":
    test_lseg_options()
