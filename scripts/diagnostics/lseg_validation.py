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

#!/usr/bin/env python
"""Quick validation script for LSEG provider implementation.
Run: python scripts/diagnostics/lseg_validation.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("✓ Testing imports...")
from app.providers.lseg import LSEGProvider
from app.config import settings
print("✓ All imports successful")

print("\n✓ Testing configuration...")
print(f"  LSEG_RATE_LIMIT_PER_SEC: {settings.LSEG_RATE_LIMIT_PER_SEC}")
print(f"  LSEG_CACHE_TTL_SECONDS: {settings.LSEG_CACHE_TTL_SECONDS}")
print(f"  LSEG_STRICT_VALIDATION: {settings.LSEG_STRICT_VALIDATION}")
print("✓ Configuration loaded")

print("\n✓ Testing provider instantiation...")
try:
    provider = LSEGProvider()
    print("✓ LSEGProvider created successfully")
    print(f"  - Session TTL: {provider._session_ttl}")
    print(f"  - RIC cache TTL: {provider._ric_cache_ttl}")
    print(f"  - Rate limit: {settings.LSEG_RATE_LIMIT_PER_SEC} req/sec")
except Exception as e:
    print(f"✗ Provider instantiation failed: {e}")
    sys.exit(1)

print("\n✓ Helper checks...")
print(f"  - _is_retryable_error(timeout): {provider._is_retryable_error(Exception('timeout'))}")
print(f"  - _is_retryable_error(500): {provider._is_retryable_error(Exception('500'))}")

print("\n" + "="*60)
print("✓ VALIDATION COMPLETE")
print("="*60)
