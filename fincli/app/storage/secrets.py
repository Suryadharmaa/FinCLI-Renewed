"""Local secret storage for globally installed FinCLI."""

from __future__ import annotations

import os
from pathlib import Path

from fincli.app.storage.config_paths import APP_DIR
from fincli.app.utils.errors import ConfigError


SECRETS_FILE = APP_DIR / "secrets.env"


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
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = _unquote(value.strip())
        if key and (override or key in override_keys or key not in os.environ or os.environ.get(key, "") == ""):
            os.environ[key] = value


def save_secret(env_key: str, value: str, path: Path | None = None) -> None:
    """Persist a secret locally and expose it to the current process."""
    path = path or SECRETS_FILE
    key = _validate_env_key(env_key)
    secret = _sanitize_value(value)
    if not secret:
        raise ConfigError(f"Nilai {key} kosong.")

    secrets = read_secrets(path)
    secrets[key] = secret

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# FinCLI local secrets. Do not commit or share this file."]
        lines.extend(f"{item_key}={_quote(item_value)}" for item_key, item_value in sorted(secrets.items()))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError as exc:
        raise ConfigError("Secret lokal gagal disimpan.", f"Path: {path}") from exc

    os.environ[key] = secret


def read_secrets(path: Path | None = None) -> dict[str, str]:
    """Read local secrets without printing or masking them."""
    path = path or SECRETS_FILE
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
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
