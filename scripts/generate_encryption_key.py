import base64
import os
import secrets

def generate_encryption_key():
    """
    Generates a URL-safe base64-encoded 32-byte key suitable for AES-256.
    This matches the requirements of the Market Data Hub admin service.
    """
    key = secrets.token_bytes(32)
    encoded_key = base64.urlsafe_b64encode(key).decode('utf-8')
    return encoded_key

if __name__ == "__main__":
    print(f"Generated APP_ENCRYPTION_KEY: {generate_encryption_key()}")
    print("\nAdd this key to your Bitwarden Secrets Manager and reference it in market-data-hub-secret.yaml")
