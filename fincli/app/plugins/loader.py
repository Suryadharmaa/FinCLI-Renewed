"""Local plugin discovery for FinCLI.

Plugins are intentionally manifest-first: FinCLI reads metadata and
exposes status, but does not execute plugin code yet. This keeps the plugin
surface useful without creating a security footgun.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from fincli.app.storage import config_paths


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    description: str
    commands: tuple[str, ...]
    capabilities: tuple[str, ...]
    hooks: tuple[str, ...]
    path: Path
    status: str = "available"


@dataclass(frozen=True, slots=True)
class PluginValidationError:
    field: str
    message: str


def validate_manifest(manifest: PluginManifest) -> list[PluginValidationError]:
    """Validate a plugin manifest. Returns list of errors (empty = valid)."""
    errors: list[PluginValidationError] = []
    if not manifest.name or not manifest.name.strip():
        errors.append(PluginValidationError("name", "Plugin name is required."))
    if manifest.name.startswith(".") or "/" in manifest.name or "\\" in manifest.name:
        errors.append(PluginValidationError("name", "Plugin name must not contain path separators or start with '.'."))
    if manifest.version == "unknown":
        errors.append(PluginValidationError("version", "Plugin version could not be parsed."))
    for cmd in manifest.commands:
        if not cmd.startswith("/"):
            errors.append(PluginValidationError("commands", f"Command '{cmd}' must start with '/'."))
    valid_hooks = {"on_startup", "on_shutdown", "on_command"}
    for hook in manifest.hooks:
        if hook not in valid_hooks:
            errors.append(PluginValidationError("hooks", f"Unknown hook '{hook}'. Valid: {', '.join(sorted(valid_hooks))}."))
    return errors


class PluginSandbox:
    """Restrict plugin file access to allowed paths."""

    def __init__(self, plugin_dir: Path) -> None:
        self.plugin_dir = plugin_dir.resolve()

    def validate_path(self, path: Path) -> bool:
        """Check that a path is within the plugin directory."""
        try:
            resolved = path.resolve()
            return resolved == self.plugin_dir or self.plugin_dir in resolved.parents
        except (ValueError, OSError):
            return False


class PluginLoader:
    """Discover plugin manifests from local plugin directories."""

    def __init__(self, search_paths: Iterable[Path] | None = None) -> None:
        self.search_paths = tuple(search_paths) if search_paths is not None else (config_paths.APP_DIR / "plugins",)

    def discover(self) -> list[PluginManifest]:
        plugins: list[PluginManifest] = []
        for root in self.search_paths:
            if not root.exists():
                continue
            for manifest_path in sorted(root.glob("*/plugin.json")):
                plugins.append(self._read_manifest(manifest_path))
        return plugins

    def _read_manifest(self, manifest_path: Path) -> PluginManifest:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            name = str(payload["name"]).strip()
            version = str(payload.get("version") or "0.0.0").strip()
            description = str(payload.get("description") or "").strip()
            commands = tuple(str(item) for item in payload.get("commands", []) if str(item).strip())
            capabilities = tuple(str(item) for item in payload.get("capabilities", []) if str(item).strip())
            hooks = tuple(str(item) for item in payload.get("hooks", []) if str(item).strip())
            if not name:
                raise ValueError("name is empty")
            return PluginManifest(
                name=name,
                version=version,
                description=description,
                commands=commands,
                capabilities=capabilities,
                hooks=hooks,
                path=manifest_path,
                status="available",
            )
        except Exception as exc:  # noqa: BLE001
            return PluginManifest(
                name=manifest_path.parent.name,
                version="unknown",
                description=f"Invalid plugin manifest: {exc}",
                commands=(),
                capabilities=(),
                hooks=(),
                path=manifest_path,
                status="invalid",
            )
