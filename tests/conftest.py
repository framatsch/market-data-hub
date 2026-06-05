import base64
import os


_TEST_APP_ENCRYPTION_KEY = base64.urlsafe_b64encode(b"0" * 32).decode()
os.environ.setdefault("APP_ENCRYPTION_KEY", _TEST_APP_ENCRYPTION_KEY)

try:
    from app.config import settings

    if not settings.APP_ENCRYPTION_KEY:
        settings.APP_ENCRYPTION_KEY = _TEST_APP_ENCRYPTION_KEY
except ImportError:
    pass
