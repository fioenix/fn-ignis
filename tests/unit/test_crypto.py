import pytest
from ignis.config import settings
from ignis.domain.exceptions import EncryptionKeyMissingException
from ignis.infrastructure.auth.crypto import (
    CURRENT_KEY_VERSION,
    CryptoService,
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
    assert encrypted["algorithm"] == "Fernet-AES128-CBC"
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
    with pytest.raises(ValueError, match="Failed to decrypt credentials"):
        decrypt_credentials(encrypted, secret_key=key2)


def test_encrypted_envelope_carries_key_version_for_rotation():
    key = generate_new_key()
    encrypted = encrypt_credentials({"access_token": "long_lived_token"}, secret_key=key)
    assert encrypted["key_version"] == CURRENT_KEY_VERSION
    # Envelopes written before key versioning must still decrypt.
    legacy = {k: v for k, v in encrypted.items() if k != "key_version"}
    assert decrypt_credentials(legacy, secret_key=key) == {"access_token": "long_lived_token"}


def test_crypto_service_roundtrip_with_injected_key():
    service = CryptoService(secret_key=generate_new_key())
    assert service.has_persistent_key() is True
    assert service.key_version == CURRENT_KEY_VERSION

    payload = {"access_token": "tok", "client_secret": "sec"}
    encrypted = service.encrypt(payload)
    assert "sec" not in encrypted["ciphertext"]
    assert service.decrypt(encrypted) == payload


def test_assert_persistent_key_raises_when_only_ephemeral_key_available(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "")
    service = CryptoService()
    assert service.has_persistent_key() is False
    with pytest.raises(EncryptionKeyMissingException, match="IGNIS_ENCRYPTION_KEY"):
        service.assert_persistent_key("Threads OAuth 2.0 credential storage")


def test_assert_persistent_key_passes_with_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", generate_new_key())
    CryptoService().assert_persistent_key("Threads OAuth 2.0 credential storage")
