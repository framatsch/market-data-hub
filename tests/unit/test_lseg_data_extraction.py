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

from decimal import Decimal
from unittest.mock import patch

import pandas as pd
import pytest

from app.providers.lseg import LSEGProvider


@pytest.fixture
def lseg_provider():
    with patch("app.providers.lseg.REFINITIV_AVAILABLE", True):
        with patch("app.providers.lseg.rd"):
            provider = LSEGProvider()
            yield provider

def test_validate_and_extract(lseg_provider):
    df = pd.DataFrame([{
        "TRDPRC_1": 150.0,
        "BID": 149.9,
        "ASK": 150.1,
        "ACVOL_UNS": 1000000
    }])
    
    result = lseg_provider._validate_and_extract(df, "AAPL.O")
    assert result.symbol == "AAPL.O"
    assert result.price == Decimal("150.0")
    assert result.bid == Decimal("149.9")
    assert result.ask == Decimal("150.1")

def test_validate_and_extract_empty(lseg_provider):
    from app.utils.errors import DataNotFoundError
    with pytest.raises(DataNotFoundError):
        lseg_provider._validate_and_extract(pd.DataFrame(), "AAPL.O")
