"""Plugin lifecycle hooks for FinCLI.

Plugins declare hooks in their manifest. The lifecycle manager calls
hooks at appropriate times during FinCLI execution.

Supported hooks:
- on_startup: called when FinCLI TUI starts
- on_shutdown: called when FinCLI TUI exits
- on_command: called before a command is executed (can inspect, not modify)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fincli.app.plugins.loader import PluginManifest

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LifecycleEvent:
    """An event dispatched to plugin hooks."""

    name: str
    data: dict[str, object] = field(default_factory=dict)


class LifecycleManager:
    """Manage plugin lifecycle hooks."""

    def __init__(self, plugins: list[PluginManifest] | None = None) -> None:
        self.plugins = plugins or []
        self._hooks: dict[str, list[PluginManifest]] = {}
        for plugin in self.plugins:
            for hook in plugin.hooks:
                self._hooks.setdefault(hook, []).append(plugin)

    def has_hooks(self, hook_name: str) -> bool:
        return hook_name in self._hooks and bool(self._hooks[hook_name])

    def plugins_for_hook(self, hook_name: str) -> list[PluginManifest]:
        return list(self._hooks.get(hook_name, []))

    def fire(self, event: LifecycleEvent) -> list[str]:
        """Fire a lifecycle event. Returns list of plugin names that handled it.

        Currently this is a stub — plugins are manifest-only and do not execute code.
        The lifecycle manager tracks which plugins WOULD handle the event.
        """
        handlers = self._hooks.get(event.name, [])
        if not handlers:
            return []
        names = [p.name for p in handlers]
        logger.debug("Lifecycle event '%s' would be handled by: %s", event.name, ", ".join(names))
        return names

    def summary(self) -> dict[str, list[str]]:
        """Return a summary of registered hooks by hook name."""
        return {hook: [p.name for p in plugins] for hook, plugins in self._hooks.items()}
