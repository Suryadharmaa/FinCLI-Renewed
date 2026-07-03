"""Local plugin discovery for FinCLI.

Plugins are intentionally manifest-first: FinCLI reads metadata and
exposes status, but does not execute plugin code yet. This keeps the plugin
surface useful without creating a security footgun.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fincli.app.storage import config_paths

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# ---------------------------------------------------------------------------
# Plugin Security: Import Whitelist (v1.2.0)
# ---------------------------------------------------------------------------

# Modules plugins ARE allowed to import
ALLOWED_IMPORTS: set[str] = {
    # Standard library (safe)
    "json",
    "math",
    "datetime",
    "typing",
    "dataclasses",
    "collections",
    "itertools",
    "functools",
    "re",
    "string",
    "enum",
    "abc",
    "copy",
    "decimal",
    "fractions",
    "statistics",
    "textwrap",
    "unicodedata",
    "uuid",
    # FinCLI public API only
    "fincli.plugins.api",
}

# Modules plugins are NOT allowed to import (security risk)
BLOCKED_IMPORTS: set[str] = {
    # Filesystem access
    "os",
    "sys",
    "pathlib",
    "shutil",
    "glob",
    "tempfile",
    "io",
    # Network access
    "socket",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    # Subprocess/code execution
    "subprocess",
    "shlex",
    "code",
    "codeop",
    "compile",
    "exec",
    "eval",
    # Import manipulation
    "importlib",
    "pkgutil",
    "zipimport",
    # System
    "ctypes",
    "signal",
    "mmap",
    "threading",
    "multiprocessing",
    "asyncio",
    "concurrent",
}


@dataclass(frozen=True, slots=True)
class PluginCodeViolation:
    """A security violation found in plugin code."""
    line: int
    violation_type: str
    detail: str


def validate_plugin_code(code: str) -> list[PluginCodeViolation]:
    """Validate plugin code for security violations.

    Checks:
    1. Import whitelist (only ALLOWED_IMPORTS)
    2. Blocked modules (BLOCKED_IMPORTS)
    3. Dangerous builtins (exec, eval, compile, __import__)
    4. Filesystem access (open, file operations)

    Returns list of violations (empty = safe).
    """
    violations: list[PluginCodeViolation] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        violations.append(PluginCodeViolation(
            line=exc.lineno or 0,
            violation_type="syntax_error",
            detail=f"Syntax error: {exc.msg}",
        ))
        return violations

    for node in ast.walk(tree):
        # Check import statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                full_module = alias.name
                if module in BLOCKED_IMPORTS:
                    violations.append(PluginCodeViolation(
                        line=node.lineno,
                        violation_type="blocked_import",
                        detail=f"Import of '{alias.name}' is blocked (security risk).",
                    ))
                elif module not in ALLOWED_IMPORTS and not full_module.startswith("fincli."):
                    violations.append(PluginCodeViolation(
                        line=node.lineno,
                        violation_type="unknown_import",
                        detail=f"Import of '{alias.name}' is not in allowed list.",
                    ))

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module.split(".")[0]
                full_module = node.module
                if module in BLOCKED_IMPORTS:
                    violations.append(PluginCodeViolation(
                        line=node.lineno,
                        violation_type="blocked_import",
                        detail=f"Import from '{node.module}' is blocked (security risk).",
                    ))
                elif module not in ALLOWED_IMPORTS and not full_module.startswith("fincli."):
                    violations.append(PluginCodeViolation(
                        line=node.lineno,
                        violation_type="unknown_import",
                        detail=f"Import from '{node.module}' is not in allowed list.",
                    ))

        # Check for dangerous function calls
        if isinstance(node, ast.Call):
            func_name = _get_call_name(node)
            if func_name in {"exec", "eval", "compile", "__import__", "globals", "locals"}:
                violations.append(PluginCodeViolation(
                    line=node.lineno,
                    violation_type="dangerous_call",
                    detail=f"Call to '{func_name}()' is blocked (security risk).",
                ))
            elif func_name == "open":
                violations.append(PluginCodeViolation(
                    line=node.lineno,
                    violation_type="filesystem_access",
                    detail="Direct file access via 'open()' is blocked. Use plugin API instead.",
                ))

        # Check for attribute access to dangerous modules
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                if node.value.id in {"os", "sys", "subprocess"}:
                    violations.append(PluginCodeViolation(
                        line=node.lineno,
                        violation_type="blocked_attribute",
                        detail=f"Access to '{node.value.id}.{node.attr}' is blocked.",
                    ))

    return violations


def _get_call_name(node: ast.Call) -> str:
    """Extract function name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def is_plugin_code_safe(code: str) -> bool:
    """Check if plugin code is safe to execute.

    Returns True if no violations found.
    """
    return len(validate_plugin_code(code)) == 0


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
