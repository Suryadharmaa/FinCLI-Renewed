"""Local secret storage for globally installed FinCLI."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from fincli.app.storage.config_paths import APP_DIR
from fincli.app.utils.errors import ConfigError


SECRETS_FILE = APP_DIR / "secrets.env"
_KEY_FILE = APP_DIR / ".secrets_key"
_MAGIC = b"FINCLI1:"


def load_local_secrets(
    path: Path | None = None,
    *,
    override: bool = False,
    override_keys: set[str] | None = None,
) -> None:
    """Load persisted secrets into process environment."""
    path = path or SECRETS_FILE
    override_keys = override_keys or set()
    if not path.exists():
        return
    raw_bytes = path.read_bytes()
    plaintext = _decrypt(raw_bytes)
    for line in plaintext.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = _unquote(value.strip())
        if key and (override or key in override_keys or key not in os.environ or os.environ.get(key, "") == ""):
            os.environ[key] = value


def save_secret(env_key: str, value: str, path: Path | None = None) -> None:
    """Persist a secret locally (encrypted at rest) and expose it to the current process."""
    path = path or SECRETS_FILE
    key = _validate_env_key(env_key)
    secret = _sanitize_value(value)
    if not secret:
        raise ConfigError(f"Nilai {key} kosong.")

    secrets = read_secrets(path)
    secrets[key] = secret

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _serialize_secrets(secrets)
        encrypted = _encrypt(raw)
        path.write_bytes(encrypted)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        raise ConfigError("Secret lokal gagal disimpan.", f"Path: {path}") from exc

    os.environ[key] = secret


def clear_secrets(path: Path | None = None) -> int:
    """Clear persisted local secrets and remove them from the current process."""
    path = path or SECRETS_FILE
    secrets = read_secrets(path)
    for key in secrets:
        os.environ.pop(key, None)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _serialize_secrets({})
        encrypted = _encrypt(raw)
        path.write_bytes(encrypted)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        raise ConfigError("Secret lokal gagal dibersihkan.", f"Path: {path}") from exc
    return len(secrets)


def read_secrets(path: Path | None = None) -> dict[str, str]:
    """Read local secrets (auto-decrypts if encrypted)."""
    path = path or SECRETS_FILE
    if not path.exists():
        return {}
    raw_bytes = path.read_bytes()
    plaintext = _decrypt(raw_bytes)
    result: dict[str, str] = {}
    for line in plaintext.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = _unquote(value.strip())
    return result


def secret_source(env_key: str, path: Path | None = None) -> str:
    """Return a display-safe source for a secret."""
    path = path or SECRETS_FILE
    current = os.getenv(env_key)
    if not current:
        return "-"
    if env_key in os.environ:
        if read_secrets(path).get(env_key) == current:
            return "~/.fincli/secrets.env"
        return "environment/.env"
    return "-"


def _validate_env_key(env_key: str) -> str:
    key = env_key.strip().upper()
    if not key or not all(char.isalnum() or char == "_" for char in key):
        raise ConfigError(f"Nama environment key tidak valid: {env_key}")
    return key


def _sanitize_value(value: str) -> str:
    return value.strip().replace("\r", "").replace("\n", "")


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _serialize_secrets(secrets: dict[str, str]) -> str:
    lines = ["# FinCLI local secrets. Do not commit or share this file."]
    lines.extend(f"{k}={_quote(v)}" for k, v in sorted(secrets.items()))
    return "\n".join(lines) + "\n"


def _get_or_create_key() -> bytes:
    if _KEY_FILE.exists():
        return base64.b64decode(_KEY_FILE.read_bytes())
    key = os.urandom(32)
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_bytes(base64.b64encode(key))
    try:
        os.chmod(_KEY_FILE, 0o600)
    except OSError:
        pass
    return key


def _xorcrypt(data: bytes, key: bytes) -> bytes:
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def _encrypt(plaintext: str) -> bytes:
    key = _get_or_create_key()
    encrypted = _xorcrypt(plaintext.encode("utf-8"), key)
    return _MAGIC + base64.b64encode(encrypted)


def _decrypt(raw: bytes) -> str:
    if raw.startswith(_MAGIC):
        encrypted_b64 = raw[len(_MAGIC):]
        key = _get_or_create_key()
        encrypted = base64.b64decode(encrypted_b64)
        return _xorcrypt(encrypted, key).decode("utf-8")
    # Legacy plaintext — backward compatible
    return raw.decode("utf-8")
