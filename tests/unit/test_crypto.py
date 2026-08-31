import pytest
from ignis.infrastructure.auth.crypto import (
    generate_new_key,
    encrypt_credentials,
    decrypt_credentials,
)

def test_generate_new_key():
    key = generate_new_key()
    assert isinstance(key, str)
    assert len(key) == 44
    assert key.endswith("=")

def test_encrypt_decrypt_roundtrip():
    key = generate_new_key()
    sample_data = {
        "cookies": [
            {"name": "sessionid", "value": "secret_session_token_12345"},
            {"name": "tt_csrf_token", "value": "csrf_token_abc"},
        ],
        "user": {"id": "123", "username": "fioenix"},
    }

    # 1. Encrypt
    encrypted = encrypt_credentials(sample_data, secret_key=key)
    assert encrypted["_encrypted"] is True
    assert "ciphertext" in encrypted
    assert encrypted["algorithm"] == "AES-256-Fernet"
    # Ensure plaintext token is NOT visible in ciphertext
    assert "secret_session_token_12345" not in encrypted["ciphertext"]

    # 2. Decrypt
    decrypted = decrypt_credentials(encrypted, secret_key=key)
    assert decrypted == sample_data
    assert decrypted["cookies"][0]["value"] == "secret_session_token_12345"

def test_decrypt_plaintext_fallback():
    plaintext_data = {"cookies": [{"name": "mock", "value": "123"}]}
    res = decrypt_credentials(plaintext_data)
    assert res == plaintext_data

def test_decrypt_with_wrong_key_fails():
    key1 = generate_new_key()
    key2 = generate_new_key()
    sample_data = {"secret": "my_val"}

    encrypted = encrypt_credentials(sample_data, secret_key=key1)
    with pytest.raises(ValueError, match="Không thể giải mã"):
        decrypt_credentials(encrypted, secret_key=key2)
