import json
import logging
import base64
import hashlib
from typing import Any, Dict, Optional
from cryptography.fernet import Fernet
from ignis.config import settings

logger = logging.getLogger(__name__)


_EPHEMERAL_KEY: Optional[str] = None


def _get_fernet_instance(secret_key: Optional[str] = None) -> Fernet:
    """Initialize Fernet cipher using configured secret key or a process-lifetime random ephemeral key."""
    global _EPHEMERAL_KEY
    raw_key = secret_key or settings.IGNIS_ENCRYPTION_KEY
    if not raw_key:
        if _EPHEMERAL_KEY is None:
            _EPHEMERAL_KEY = Fernet.generate_key().decode()
            logger.warning(
                "CRITICAL SECURITY WARNING: IGNIS_ENCRYPTION_KEY is not set in .env. "
                "Generated a random ephemeral in-memory key for this process lifetime. "
                "Stored encrypted credentials will NOT be decryptable across process restarts until IGNIS_ENCRYPTION_KEY is set."
            )
        raw_key = _EPHEMERAL_KEY
    else:
        # Ensure key is valid 32-byte urlsafe base64 for Fernet
        if len(raw_key) != 44 or not raw_key.endswith("="):
            derived = hashlib.sha256(raw_key.encode()).digest()
            raw_key = base64.urlsafe_b64encode(derived).decode()

    return Fernet(raw_key.encode() if isinstance(raw_key, str) else raw_key)



def generate_new_key() -> str:
    """Generate a new Fernet (AES-128-CBC + HMAC-SHA256) encryption key."""
    return Fernet.generate_key().decode()


def encrypt_credentials(data: Dict[str, Any], secret_key: Optional[str] = None) -> Dict[str, Any]:
    """Encrypt credentials payload into a secure ciphertext JSON structure."""
    if not data:
        return {}
    if data.get("_encrypted") is True:
        return data

    try:
        fernet = _get_fernet_instance(secret_key)
        json_str = json.dumps(data)
        encrypted_bytes = fernet.encrypt(json_str.encode("utf-8"))
        return {
            "_encrypted": True,
            "algorithm": "Fernet-AES128-CBC",
            "ciphertext": encrypted_bytes.decode("utf-8"),
        }

    except Exception as e:
        logger.error(f"Error encrypting credentials: {e}")
        raise ValueError(f"Failed to encrypt credentials: {e}") from e


def decrypt_credentials(data: Dict[str, Any], secret_key: Optional[str] = None) -> Dict[str, Any]:
    """Decrypt credentials payload back into original dictionary."""
    if not data:
        return {}
    if not data.get("_encrypted") or not data.get("ciphertext"):
        # No encryption flag present -> return plaintext as-is
        return data

    try:
        fernet = _get_fernet_instance(secret_key)
        ciphertext = data["ciphertext"]
        decrypted_bytes = fernet.decrypt(ciphertext.encode("utf-8"))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Error decrypting credentials (wrong key or corrupted data): {e}")
        raise ValueError(f"Failed to decrypt credentials: {e}") from e

