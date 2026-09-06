"""Reusable release and workspace security scanning helpers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

BLOCKED_FILE_NAMES = {".env", "secrets.env"}
BLOCKED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log"}
BLOCKED_PARTS = {
    ".agents",
    ".claude",
    ".codex",
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".npm-python",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp-home",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
}
TEXT_SUFFIXES = {
    "", ".cfg", ".css", ".env", ".html", ".ini", ".js", ".json", ".md",
    ".py", ".rs", ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml",
}
MAX_SCAN_BYTES = 2 * 1024 * 1024
SECRET_PATTERNS = (
    re.compile(r"(?m)^[ \t]*([A-Z0-9_]*(?:API|TOKEN|SECRET|KEY)[A-Z0-9_]*)[ \t]*=[ \t]*([^\s#\"']{12,})[ \t]*$"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),
)
PLACEHOLDER_VALUES = {"your_key_here", "changeme", "replace_me", "example", "none", "null"}


@dataclass(frozen=True, slots=True)
class SafetyIssue:
    path: Path
    kind: str
    detail: str


def find_secret_issues(root: Path) -> list[SafetyIssue]:
    """Scan a tree while pruning generated and dependency directories."""
    root = root.resolve()
    issues: list[SafetyIssue] = []
    for path in iter_scannable_files(root):
        rel = path.relative_to(root)
        if is_blocked_path(rel):
            issues.append(SafetyIssue(rel, "blocked_file", "sensitive/runtime file must not be published"))
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            issues.append(SafetyIssue(rel, "read_error", str(exc)))
            continue
        for pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match and len(match.groups()) >= 2 and is_placeholder_secret(match.group(2)):
                continue
            if match:
                issues.append(SafetyIssue(rel, "secret_pattern", redact_match(match.group(0))))
                break
    return issues


def validate_pack_file_list(files: list[str]) -> list[SafetyIssue]:
    issues: list[SafetyIssue] = []
    for value in files:
        path = Path(value.replace("\\", "/"))
        if is_blocked_path(path):
            issues.append(SafetyIssue(path, "pack_blocked_file", "sensitive package file"))
    return issues


def iter_scannable_files(root: Path) -> Iterator[Path]:
    for current, directories, files in os.walk(root):
        directories[:] = [
            name for name in directories
            if name not in BLOCKED_PARTS and not name.endswith(".egg-info") and not name.startswith(".tmp-")
        ]
        base = Path(current)
        for name in files:
            yield base / name


def is_blocked_path(path: Path) -> bool:
    parts = tuple(str(part) for part in path.parts)
    if any(part in BLOCKED_PARTS or part.startswith(".tmp-") for part in parts):
        return True
    if path.name in BLOCKED_FILE_NAMES:
        return True
    return path.suffix.lower() in BLOCKED_SUFFIXES


def redact_match(value: str) -> str:
    if "=" in value:
        key, _, _secret = value.partition("=")
        return f"{key.strip()}=***"
    return value[:16] + "..." if len(value) > 16 else "***"


def is_placeholder_secret(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized in PLACEHOLDER_VALUES
        or normalized.endswith("_here")
        or normalized.startswith("your_")
        or normalized.startswith("your-")
        or normalized.startswith("<")
    )
