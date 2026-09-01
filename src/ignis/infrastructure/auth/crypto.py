import json
import logging
import base64
import hashlib
from typing import Any, Dict, Optional
from cryptography.fernet import Fernet
from ignis.config import settings

logger = logging.getLogger(__name__)


def _get_fernet_instance(secret_key: Optional[str] = None) -> Fernet:
    """Khởi tạo Fernet cipher với secret key từ config hoặc biến truyền vào."""
    raw_key = secret_key or settings.IGNIS_ENCRYPTION_KEY
    if not raw_key:
        logger.warning("SECURITY WARNING: IGNIS_ENCRYPTION_KEY is not set. Using ephemeral fallback key. Set IGNIS_ENCRYPTION_KEY in .env for production.")
        derived = hashlib.sha256((settings.DATABASE_URL or "fn-ignis-default-salt").encode()).digest()
        raw_key = base64.urlsafe_b64encode(derived).decode()
    else:
        # Đảm bảo key có định dạng 32-byte urlsafe base64 hợp lệ của Fernet
        if len(raw_key) != 44 or not raw_key.endswith("="):
            derived = hashlib.sha256(raw_key.encode()).digest()
            raw_key = base64.urlsafe_b64encode(derived).decode()

    return Fernet(raw_key.encode() if isinstance(raw_key, str) else raw_key)


def generate_new_key() -> str:
    """Sinh một key mã hóa Fernet (AES-128-CBC + HMAC-SHA256) mới."""
    return Fernet.generate_key().decode()


def encrypt_credentials(data: Dict[str, Any], secret_key: Optional[str] = None) -> Dict[str, Any]:
    """Mã hóa payload credentials thành ciphertext JSONB an toàn."""
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
        logger.error(f"Lỗi khi mã hóa credentials: {e}")
        raise ValueError(f"Không thể mã hóa credentials: {e}") from e


def decrypt_credentials(data: Dict[str, Any], secret_key: Optional[str] = None) -> Dict[str, Any]:
    """Giải mã payload credentials từ ciphertext JSONB về dictionary nguyên bản."""
    if not data:
        return {}
    if not data.get("_encrypted") or not data.get("ciphertext"):
        # Không có cờ mã hóa (dữ liệu plaintext) -> trả về trực tiếp
        return data

    try:
        fernet = _get_fernet_instance(secret_key)
        ciphertext = data["ciphertext"]
        decrypted_bytes = fernet.decrypt(ciphertext.encode("utf-8"))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Lỗi khi giải mã credentials (sai key hoặc dữ liệu bị hỏng): {e}")
        raise ValueError(f"Không thể giải mã credentials: {e}") from e
