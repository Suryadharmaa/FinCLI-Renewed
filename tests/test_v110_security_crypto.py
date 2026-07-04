"""Tests for v1.1.0 security features: broker key encryption, session security."""

from __future__ import annotations

import pytest

from fincli.app.utils.crypto import (
    decrypt_broker_key,
    encrypt_broker_key,
    generate_master_password,
    hash_master_password,
    verify_master_password,
)

# --- Encryption Tests ---


class TestBrokerKeyEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        """Encrypt then decrypt should return original plaintext."""
        plaintext = "test-key-1234567890abcdef"
        password = "my-secure-master-password"
        encrypted = encrypt_broker_key(plaintext, password)
        decrypted = decrypt_broker_key(encrypted, password)
        assert decrypted == plaintext

    def test_encrypt_different_passwords_different_output(self):
        """Same plaintext with different passwords should produce different ciphertext."""
        plaintext = "test-key-1234567890abcdef"
        encrypted1 = encrypt_broker_key(plaintext, "password1")
        encrypted2 = encrypt_broker_key(plaintext, "password2")
        assert encrypted1 != encrypted2

    def test_encrypt_produces_base64(self):
        """Encrypted output should be valid base64."""
        import base64
        plaintext = "test-key"
        password = "password"
        encrypted = encrypt_broker_key(plaintext, password)
        # Should not raise
        base64.b64decode(encrypted)

    def test_encrypt_empty_plaintext_raises(self):
        """Empty plaintext should raise ValueError."""
        with pytest.raises(ValueError, match="Plaintext must not be empty"):
            encrypt_broker_key("", "password")

    def test_encrypt_empty_password_raises(self):
        """Empty password should raise ValueError."""
        with pytest.raises(ValueError, match="Master password must not be empty"):
            encrypt_broker_key("test-key", "")

    def test_decrypt_wrong_password_raises(self):
        """Wrong password should raise ValueError."""
        encrypted = encrypt_broker_key("test-key", "correct-password")
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_broker_key(encrypted, "wrong-password")

    def test_decrypt_corrupted_data_raises(self):
        """Corrupted data should raise ValueError."""
        with pytest.raises(ValueError):
            decrypt_broker_key("not-valid-base64!!", "password")

    def test_decrypt_empty_data_raises(self):
        """Empty encrypted data should raise ValueError."""
        with pytest.raises(ValueError, match="Encrypted data must not be empty"):
            decrypt_broker_key("", "password")

    def test_decrypt_short_data_raises(self):
        """Data shorter than salt+hmac should raise ValueError."""
        import base64
        short_data = base64.b64encode(b"short").decode("ascii")
        with pytest.raises(ValueError, match="too short"):
            decrypt_broker_key(short_data, "password")

    def test_encrypt_long_key(self):
        """Should handle long API keys."""
        plaintext = "a" * 256
        password = "password"
        encrypted = encrypt_broker_key(plaintext, password)
        decrypted = decrypt_broker_key(encrypted, password)
        assert decrypted == plaintext

    def test_encrypt_special_characters(self):
        """Should handle special characters in key and password."""
        plaintext = "test-key_with-special!@#$%^&*()chars"
        password = "p@ssw0rd!#$%^&*()"
        encrypted = encrypt_broker_key(plaintext, password)
        decrypted = decrypt_broker_key(encrypted, password)
        assert decrypted == plaintext


# --- Master Password Tests ---


class TestMasterPassword:
    def test_generate_master_password(self):
        """Generated password should be non-empty and unique."""
        pw1 = generate_master_password()
        pw2 = generate_master_password()
        assert len(pw1) > 0
        assert pw1 != pw2

    def test_hash_and_verify(self):
        """Hash then verify should succeed."""
        password = "my-master-password"
        hashed = hash_master_password(password)
        assert verify_master_password(password, hashed) is True

    def test_verify_wrong_password(self):
        """Wrong password should fail verification."""
        hashed = hash_master_password("correct-password")
        assert verify_master_password("wrong-password", hashed) is False

    def test_hash_produces_base64(self):
        """Hash output should be valid base64."""
        import base64
        hashed = hash_master_password("password")
        base64.b64decode(hashed)

    def test_hash_different_each_time(self):
        """Same password should produce different hashes (random salt)."""
        hash1 = hash_master_password("password")
        hash2 = hash_master_password("password")
        assert hash1 != hash2
