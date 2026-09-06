"""Prepublish safety checks for FinCLI releases."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fincli.app.utils.security_scan import (  # noqa: E402
    SafetyIssue,
    find_secret_issues,
    validate_pack_file_list,
)


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
        env={**os.environ, "npm_config_cache": str(root / ".tmp-npm-cache")},
        text=True,
    )

    payload = json.loads(completed.stdout)
    if not payload:
        return []
    return [str(item.get("path", "")) for item in payload[0].get("files", [])]


def release_checklist() -> list[str]:
    return [
        "pytest passes",
        "compileall passes",
        "pip-audit passes (no known vulnerabilities)",
        "no .env/secrets/log/db files in package",
        "npm pack --dry-run manifest validated",
        "API keys rotated if ever exposed",
    ]


def run_pip_audit() -> list[SafetyIssue]:
    """Run pip-audit and return any vulnerabilities found."""
    issues: list[SafetyIssue] = []
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--progress-spinner",
                "off",
                "-r",
                str(PROJECT_ROOT / "requirements.txt"),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 and "no known vulnerabilities" not in result.stdout.lower():
            combined = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
            # Parse output for vulnerability lines
            for line in result.stdout.strip().splitlines():
                if line.startswith("Name") or line.startswith("----") or not line.strip():
                    continue
                if "Found" in line and "vulnerability" in line:
                    issues.append(SafetyIssue(Path("pip-audit"), "vulnerability", line.strip()))
            if not issues:
                issues.append(SafetyIssue(Path("pip-audit"), "audit_error", combined or f"exit code {result.returncode}"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        issues.append(SafetyIssue(Path("pip-audit"), "audit_error", str(exc)))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinCLI prepublish safety checker")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--skip-pack", action="store_true", help="Skip npm pack --dry-run validation")
    parser.add_argument("--skip-audit", action="store_true", help="Skip pip-audit vulnerability check")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    issues = find_secret_issues(root)
    if not args.skip_pack:
        try:
            issues.extend(validate_pack_file_list(npm_pack_file_list(root)))
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            issues.append(SafetyIssue(Path("npm pack --dry-run"), "pack_error", str(exc)))
    if not args.skip_audit:
        issues.extend(run_pip_audit())

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


if __name__ == "__main__":
    sys.exit(main())
