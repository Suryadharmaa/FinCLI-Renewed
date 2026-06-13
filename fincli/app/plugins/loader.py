"""Local plugin discovery for FinCLI.

Plugins are intentionally manifest-first in v0.2.2: FinCLI reads metadata and
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
    path: Path
    status: str = "available"


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
            if not name:
                raise ValueError("name is empty")
            return PluginManifest(
                name=name,
                version=version,
                description=description,
                commands=commands,
                capabilities=capabilities,
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
                path=manifest_path,
                status="invalid",
            )
