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

from unittest.mock import patch

import pandas as pd
import pytest

from app.providers.lseg import LSEGProvider
from app.utils.errors import DataValidationError


@pytest.fixture
def lseg_provider():
    with patch("app.providers.lseg.REFINITIV_AVAILABLE", True):
        with patch("app.providers.lseg.rd"):
            provider = LSEGProvider()
            yield provider

def test_safe_decimal_strict_validation(lseg_provider):
    from app.config import settings
    original_strict = settings.LSEG_STRICT_VALIDATION
    settings.LSEG_STRICT_VALIDATION = True
    
    df = pd.DataFrame([{"OTHER_FIELD": 10.0}])
    try:
        with pytest.raises(DataValidationError):
            lseg_provider._validate_and_extract(df, "AAPL.O")
    finally:
        settings.LSEG_STRICT_VALIDATION = original_strict

def test_safe_decimal_nan_strict(lseg_provider):
    import numpy as np

    from app.config import settings
    original_strict = settings.LSEG_STRICT_VALIDATION
    settings.LSEG_STRICT_VALIDATION = True
    
    df = pd.DataFrame([{"TRDPRC_1": np.nan}])
    try:
        with pytest.raises(DataValidationError):
            lseg_provider._validate_and_extract(df, "AAPL.O")
    finally:
        settings.LSEG_STRICT_VALIDATION = original_strict
