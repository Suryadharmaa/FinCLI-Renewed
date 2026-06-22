"""Secret storage backed by the operating system credential store."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from fincli.app.storage.config_paths import APP_DIR
from fincli.app.utils.errors import ConfigError

try:
    import keyring as _keyring
except ImportError:  # pragma: no cover - exercised when optional dependency is absent
    _keyring = None


SECRETS_FILE = APP_DIR / "secrets.env"
_KEY_FILE = APP_DIR / ".secrets_key"
_MAGIC = b"FINCLI1:"
_SERVICE_NAME = "fincli.secrets"


def load_local_secrets(
    path: Path | None = None,
    *,
    override: bool = False,
    override_keys: set[str] | None = None,
) -> None:
    """Load OS-keyring secrets into the current process environment."""
    override_keys = override_keys or set()
    for key, value in read_secrets(path).items():
        if override or key in override_keys or not os.environ.get(key):
            os.environ[key] = value


def save_secret(env_key: str, value: str, path: Path | None = None) -> None:
    """Persist one secret in the OS credential store and expose it in-process."""
    key = _validate_env_key(env_key)
    secret = _sanitize_value(value)
    if not secret:
        raise ConfigError(f"Nilai {key} kosong.")

    secrets = read_secrets(path)
    secrets[key] = secret
    _write_secrets(path or SECRETS_FILE, secrets)
    os.environ[key] = secret


def clear_secrets(path: Path | None = None) -> int:
    """Clear the credential-store blob and matching process environment values."""
    target = path or SECRETS_FILE
    secrets = read_secrets(target)
    for key in secrets:
        os.environ.pop(key, None)
    if secrets:
        backend = _require_keyring()
        try:
            backend.delete_password(_SERVICE_NAME, _credential_account(target))
        except Exception as exc:  # noqa: BLE001 - keyring backends vary by OS
            raise ConfigError("Secret lokal gagal dihapus dari credential store.") from exc
    return len(secrets)


def read_secrets(path: Path | None = None) -> dict[str, str]:
    """Read the JSON blob for a path, migrating a legacy file exactly once."""
    target = path or SECRETS_FILE
    backend = _require_keyring()
    account = _credential_account(target)
    try:
        raw = backend.get_password(_SERVICE_NAME, account)
    except Exception as exc:  # noqa: BLE001 - report unavailable backends uniformly
        raise ConfigError("OS credential store tidak tersedia.") from exc
    if raw is not None:
        return _decode_blob(raw)
    if not target.exists():
        return {}
    return _migrate_legacy_file(target, backend, account)


def secret_source(env_key: str, path: Path | None = None) -> str:
    """Return a display-safe source without exposing a local file path."""
    current = os.getenv(env_key)
    if not current:
        return "-"
    if read_secrets(path).get(env_key) == current:
        return "OS credential store"
    return "environment/.env"


def _write_secrets(path: Path, secrets: dict[str, str]) -> None:
    backend = _require_keyring()
    payload = json.dumps(secrets, sort_keys=True, separators=(",", ":"))
    try:
        backend.set_password(_SERVICE_NAME, _credential_account(path), payload)
    except Exception as exc:  # noqa: BLE001 - keyring backends vary by OS
        raise ConfigError("Secret lokal gagal disimpan ke credential store.") from exc
    try:
        stored = backend.get_password(_SERVICE_NAME, _credential_account(path))
    except Exception as exc:  # noqa: BLE001
        raise ConfigError("Secret lokal gagal diverifikasi di credential store.") from exc
    if stored is None or _decode_blob(stored) != secrets:
        raise ConfigError("Secret lokal gagal diverifikasi di credential store.")


def _migrate_legacy_file(path: Path, backend: object, account: str) -> dict[str, str]:
    try:
        legacy = _parse_legacy(_decrypt_legacy(path.read_bytes()))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ConfigError("File secret lama tidak dapat dimigrasikan.", f"Path: {path}") from exc

    payload = json.dumps(legacy, sort_keys=True, separators=(",", ":"))
    try:
        backend.set_password(_SERVICE_NAME, account, payload)
        stored = backend.get_password(_SERVICE_NAME, account)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError("Migrasi secret ke OS credential store gagal.") from exc
    if stored is None or _decode_blob(stored) != legacy:
        raise ConfigError("Migrasi secret tidak dapat diverifikasi.")

    try:
        path.unlink()
        if path == SECRETS_FILE and _KEY_FILE.exists():
            _KEY_FILE.unlink()
    except OSError as exc:
        raise ConfigError("Migrasi secret berhasil tetapi file lama gagal dihapus.", f"Path: {path}") from exc
    return legacy


def _require_keyring() -> object:
    if _keyring is None:
        raise ConfigError("OS credential store tidak tersedia. Install dependency 'keyring'.")
    try:
        backend = _keyring.get_keyring()
        if getattr(backend, "priority", 0) <= 0:
            raise RuntimeError("no usable keyring backend")
    except Exception as exc:  # noqa: BLE001
        raise ConfigError("OS credential store tidak tersedia.") from exc
    return _keyring


def _credential_account(path: Path) -> str:
    normalized = str(path.expanduser().resolve())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _decode_blob(raw: str) -> dict[str, str]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("Data OS credential store tidak valid.") from exc
    if not isinstance(decoded, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in decoded.items()):
        raise ConfigError("Data OS credential store tidak valid.")
    return decoded


def _parse_legacy(plaintext: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in plaintext.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[_validate_env_key(key)] = _unquote(value.strip())
    return result


def _decrypt_legacy(raw: bytes) -> str:
    if not raw.startswith(_MAGIC):
        return raw.decode("utf-8")
    if not _KEY_FILE.exists():
        raise ConfigError("Legacy secret key tidak ditemukan; migrasi tidak dapat dilakukan.")
    encrypted = base64.b64decode(raw[len(_MAGIC):])
    key = base64.b64decode(_KEY_FILE.read_bytes())
    return _xorcrypt(encrypted, key).decode("utf-8")


def _xorcrypt(data: bytes, key: bytes) -> bytes:
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))


def _validate_env_key(env_key: str) -> str:
    key = env_key.strip().upper()
    if not key or not all(char.isalnum() or char == "_" for char in key):
        raise ConfigError(f"Nama environment key tidak valid: {env_key}")
    return key


def _sanitize_value(value: str) -> str:
    return value.strip().replace("\r", "").replace("\n", "")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value
