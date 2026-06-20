"""Cryptographic utilities for FinCLI v1.1.0.

Provides broker API key encryption using PBKDF2 key derivation
and XOR stream cipher with HMAC-SHA256 integrity verification.
No external dependencies required.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets


# PBKDF2 parameters
PBKDF2_ITERATIONS = 600_000  # OWASP recommendation for PBKDF2-SHA256
SALT_LENGTH = 16
KEY_LENGTH = 32  # 256 bits
HMAC_LENGTH = 32  # SHA-256


def _derive_key(master_password: str, salt: bytes) -> bytes:
    """Derive encryption key from master password using PBKDF2-SHA256."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        master_password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=KEY_LENGTH,
    )


def _generate_keystream(key: bytes, length: int) -> bytes:
    """Generate a keystream using HMAC-SHA256 in counter mode."""
    keystream = b""
    counter = 0
    while len(keystream) < length:
        counter_bytes = counter.to_bytes(8, "big")
        block = hmac.new(key, counter_bytes, hashlib.sha256).digest()
        keystream += block
        counter += 1
    return keystream[:length]


def encrypt_broker_key(plaintext: str, master_password: str) -> str:
    """Encrypt a broker API key with master password.

    Returns base64-encoded string with format: salt + ciphertext + hmac
    """
    if not plaintext:
        raise ValueError("Plaintext tidak boleh kosong.")
    if not master_password:
        raise ValueError("Master password tidak boleh kosong.")

    # Generate random salt
    salt = secrets.token_bytes(SALT_LENGTH)

    # Derive encryption key
    key = _derive_key(master_password, salt)

    # Generate keystream and encrypt
    plaintext_bytes = plaintext.encode("utf-8")
    keystream = _generate_keystream(key, len(plaintext_bytes))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext_bytes, keystream))

    # Compute HMAC for integrity
    mac = hmac.new(key, salt + ciphertext, hashlib.sha256).digest()

    # Combine: salt + ciphertext + hmac
    encrypted = salt + ciphertext + mac

    return base64.b64encode(encrypted).decode("ascii")


def decrypt_broker_key(encrypted_b64: str, master_password: str) -> str:
    """Decrypt a broker API key encrypted with encrypt_broker_key.

    Raises ValueError if decryption fails (wrong password or corrupted data).
    """
    if not encrypted_b64:
        raise ValueError("Encrypted data tidak boleh kosong.")
    if not master_password:
        raise ValueError("Master password tidak boleh kosong.")

    try:
        encrypted = base64.b64decode(encrypted_b64)
    except Exception as exc:
        raise ValueError("Data terenkripsi tidak valid.") from exc

    # Minimum length: salt + hmac (ciphertext can be empty but that's invalid)
    min_length = SALT_LENGTH + HMAC_LENGTH + 1
    if len(encrypted) < min_length:
        raise ValueError("Data terenkripsi terlalu pendek.")

    # Extract components
    salt = encrypted[:SALT_LENGTH]
    ciphertext = encrypted[SALT_LENGTH:-HMAC_LENGTH]
    stored_mac = encrypted[-HMAC_LENGTH:]

    # Derive key
    key = _derive_key(master_password, salt)

    # Verify HMAC
    computed_mac = hmac.new(key, salt + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(stored_mac, computed_mac):
        raise ValueError("Decryption gagal. Password salah atau data terkorupsi.")

    # Decrypt
    keystream = _generate_keystream(key, len(ciphertext))
    plaintext_bytes = bytes(a ^ b for a, b in zip(ciphertext, keystream))

    try:
        return plaintext_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Decryption gagal. Data terkorupsi.") from exc


def generate_master_password() -> str:
    """Generate a random master password for initial setup."""
    return secrets.token_urlsafe(32)


def hash_master_password(password: str) -> str:
    """Hash master password for verification (not for encryption)."""
    salt = secrets.token_bytes(SALT_LENGTH)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return base64.b64encode(salt + key).decode("ascii")


def verify_master_password(password: str, hashed: str) -> bool:
    """Verify master password against hash."""
    try:
        decoded = base64.b64decode(hashed)
        salt = decoded[:SALT_LENGTH]
        stored_key = decoded[SALT_LENGTH:]
        computed_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return hmac.compare_digest(stored_key, computed_key)
    except Exception:
        return False
