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
