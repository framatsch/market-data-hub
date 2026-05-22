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

import refinitiv.data as rd
from refinitiv.data.content import search
from dotenv import load_dotenv
import os

load_dotenv()
session = rd.session.platform.Definition(
    app_key=os.getenv("LSEG_APP_KEY"),
    grant=rd.session.platform.GrantPassword(
        username=os.getenv("LSEG_USERNAME"),
        password=os.getenv("LSEG_PASSWORD")
    ),
    signon_control=True
).get_session()

session.open()
rd.session.set_default(session)

print("=== Testing EQUITY_QUOTES with various field combinations ===\n")

# Test 1: Same fields as test_connect.py
print("[Test 1] EQUITY_QUOTES with filter (from test_connect.py)")
response = search.Definition(
    view=search.Views.EQUITY_QUOTES,
    query="AAPL",
    filter="TickerSymbol eq 'AAPL'",
    select="RIC, DisplayName, TickerSymbol, ExchCode",
    top=1
).get_data()

if response.data.df is not None and not response.data.df.empty:
    print("Columns:", response.data.df.columns.tolist())
    print("Data:\n", response.data.df)
else:
    print("No data")

# Test 2: Add price fields
print("\n[Test 2] EQUITY_QUOTES with price fields")
response = search.Definition(
    view=search.Views.EQUITY_QUOTES,
    query="AAPL",
    filter="TickerSymbol eq 'AAPL'",
    select="RIC, TRDPRC_1, BID, ASK, CLOSE, OPEN_PRC, HIGH_1, LOW_1, ACVOL_1",
    top=1
).get_data()

if response.data.df is not None and not response.data.df.empty:
    print("Columns:", response.data.df.columns.tolist())
    print("Data:\n", response.data.df)
    print("Data types:\n", response.data.df.dtypes)
else:
    print("No data")

# Test 3: All fields combined
print("\n[Test 3] EQUITY_QUOTES with all fields")
response = search.Definition(
    view=search.Views.EQUITY_QUOTES,
    query="AAPL",
    filter="TickerSymbol eq 'AAPL'",
    select="RIC, DisplayName, TickerSymbol, ExchCode, TRDPRC_1, BID, ASK, CLOSE, OPEN_PRC, HIGH_1, LOW_1, ACVOL_1",
    top=1
).get_data()

if response.data.df is not None and not response.data.df.empty:
    print("Columns:", response.data.df.columns.tolist())
    print("\nRow 0 values:")
    for col in response.data.df.columns:
        val = response.data.df[col].iloc[0]
        print(f"  {col}: {val} (type: {type(val).__name__})")
else:
    print("No data")

session.close()
