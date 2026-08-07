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

from datetime import datetime
from decimal import Decimal

from app.models.price import PriceBar, PriceQuote
from app.utils.csv_export import to_csv


def test_to_csv_single_object():
    quote = PriceQuote(
        symbol="AAPL", price=Decimal("150.00"), currency="USD", 
        timestamp=datetime(2024, 1, 1, 12, 0), provider="test"
    )
    content_type, csv_bytes = to_csv(quote, "test.csv")
    
    assert content_type == "text/csv"
    assert b"AAPL" in csv_bytes
    assert b"150.00" in csv_bytes
    assert b"symbol,price" in csv_bytes

def test_to_csv_list_objects():
    bars = [
        PriceBar(symbol="AAPL", start=datetime(2024, 1, 1), end=datetime(2024, 1, 1), 
                 open=Decimal("149.00"), high=Decimal("151.00"), 
                 low=Decimal("148.00"), close=Decimal("150.00"), 
                 volume=1000, provider="test")
    ]
    content_type, csv_bytes = to_csv(bars, "test.csv")
    
    assert content_type == "text/csv"
    assert b"AAPL" in csv_bytes
    assert b"149.00" in csv_bytes
    assert b"symbol,start,end" in csv_bytes

def test_to_csv_none():
    _content_type, csv_bytes = to_csv(None, "test.csv")
    assert csv_bytes == b""

