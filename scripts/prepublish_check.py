"""Prepublish safety checks for FinCLI releases."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


BLOCKED_FILE_NAMES = {".env", "secrets.env"}
BLOCKED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log"}
BLOCKED_PARTS = {".git", ".venv", "venv", ".npm-python", "__pycache__", ".pytest_cache", "dist", "build"}
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
    """Scan working tree for blocked files and obvious token patterns."""
    issues: list[SafetyIssue] = []
    for path in _iter_scannable_files(root):
        rel = path.relative_to(root)
        if _is_blocked_path(rel):
            issues.append(SafetyIssue(rel, "blocked_file", "sensitive/runtime file must not be published"))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            issues.append(SafetyIssue(rel, "read_error", str(exc)))
            continue
        for pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match and len(match.groups()) >= 2 and _is_placeholder_secret(match.group(2)):
                continue
            if match:
                issues.append(SafetyIssue(rel, "secret_pattern", _redact(match.group(0))))
                break
    return issues


def validate_pack_file_list(files: list[str]) -> list[SafetyIssue]:
    """Validate npm pack file list lines from npm pack --dry-run --json."""
    issues: list[SafetyIssue] = []
    for value in files:
        path = Path(value.replace("\\", "/"))
        if _is_blocked_path(path):
            issues.append(SafetyIssue(path, "pack_blocked_file", "sensitive package file"))
    return issues


def npm_pack_file_list(root: Path) -> list[str]:
    """Return package file list from npm pack dry-run output."""
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        raise OSError("npm executable not found")
    completed = subprocess.run(
        [npm, "pack", "--dry-run", "--json"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    import json

    payload = json.loads(completed.stdout)
    if not payload:
        return []
    return [str(item.get("path", "")) for item in payload[0].get("files", [])]


def release_checklist() -> list[str]:
    return [
        "pytest passes",
        "compileall passes",
        "no .env/secrets/log/db files in package",
        "npm pack --dry-run manifest validated",
        "API keys rotated if ever exposed",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinCLI prepublish safety checker")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--skip-pack", action="store_true", help="Skip npm pack --dry-run validation")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    issues = find_secret_issues(root)
    if not args.skip_pack:
        try:
            issues.extend(validate_pack_file_list(npm_pack_file_list(root)))
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            issues.append(SafetyIssue(Path("npm pack --dry-run"), "pack_error", str(exc)))

    if issues:
        print("FinCLI prepublish safety check failed:")
        for issue in issues:
            print(f"- {issue.kind}: {issue.path} :: {issue.detail}")
        return 1

    print("FinCLI prepublish safety check passed.")
    print("Release checklist:")
    for item in release_checklist():
        print(f"- {item}")
    return 0


def _iter_scannable_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in BLOCKED_PARTS or part.endswith(".egg-info") for part in rel.parts[:-1]):
            continue
        yield path


def _is_blocked_path(path: Path) -> bool:
    normalized_parts = tuple(str(part) for part in path.parts)
    if any(part in BLOCKED_PARTS for part in normalized_parts):
        return True
    if path.name in BLOCKED_FILE_NAMES:
        return True
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        return True
    return False


def _redact(value: str) -> str:
    if "=" in value:
        key, _, _secret = value.partition("=")
        return f"{key.strip()}=***"
    return value[:16] + "..." if len(value) > 16 else "***"


def _is_placeholder_secret(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized in PLACEHOLDER_VALUES
        or normalized.endswith("_here")
        or normalized.startswith("your_")
        or normalized.startswith("your-")
        or normalized.startswith("<")
    )


if __name__ == "__main__":
    sys.exit(main())
