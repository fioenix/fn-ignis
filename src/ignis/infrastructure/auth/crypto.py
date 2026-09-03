import json
import logging
import base64
import hashlib
from typing import Any, Dict, Optional
from cryptography.fernet import Fernet
from ignis.config import settings
from ignis.domain.exceptions import EncryptionKeyMissingException

logger = logging.getLogger(__name__)


# Envelope key version. Bump when the derivation scheme or cipher changes so
# stored credentials can be migrated during token rotation.
CURRENT_KEY_VERSION = "v1"

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


def has_persistent_key(secret_key: Optional[str] = None) -> bool:
    """Report whether a durable encryption key is configured (i.e. not an ephemeral in-memory key)."""
    return bool(secret_key or settings.IGNIS_ENCRYPTION_KEY)


def assert_persistent_key(context: str, secret_key: Optional[str] = None) -> None:
    """
    Fail fast before persisting long-lived secrets (OAuth tokens, client secrets).

    An ephemeral process key would silently render the stored ciphertext
    undecryptable after a restart, so refuse the write instead of degrading.
    """
    if not has_persistent_key(secret_key):
        raise EncryptionKeyMissingException(
            f"{context} requires a persistent IGNIS_ENCRYPTION_KEY. "
            "Refusing to store long-lived credentials under an ephemeral in-memory key "
            "(they would be undecryptable after a process restart). "
            "Generate one with `python -c \"from ignis.infrastructure.auth.crypto import generate_new_key; print(generate_new_key())\"` "
            "and set IGNIS_ENCRYPTION_KEY in .env."
        )


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
            "key_version": CURRENT_KEY_VERSION,
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


class CryptoService:
    """
    Object-oriented facade over the credential encryption primitives.

    Lets auth managers depend on an injectable collaborator (and be tested with a
    fixed key) instead of reaching for module-level state.
    """

    key_version = CURRENT_KEY_VERSION

    def __init__(self, secret_key: Optional[str] = None):
        self._secret_key = secret_key

    def has_persistent_key(self) -> bool:
        return has_persistent_key(self._secret_key)

    def assert_persistent_key(self, context: str) -> None:
        assert_persistent_key(context, secret_key=self._secret_key)

    def encrypt(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return encrypt_credentials(data, secret_key=self._secret_key)

    def decrypt(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return decrypt_credentials(data, secret_key=self._secret_key)
