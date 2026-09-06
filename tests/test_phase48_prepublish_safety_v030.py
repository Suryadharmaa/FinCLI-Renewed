from __future__ import annotations

from pathlib import Path

from scripts.prepublish_check import SafetyIssue, find_secret_issues, run_pip_audit, validate_pack_file_list


def test_prepublish_secret_scan_flags_env_and_token_patterns(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-secret-key-12345\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("safe docs\n", encoding="utf-8")

    issues = find_secret_issues(tmp_path)

    assert any(issue.kind == "blocked_file" and ".env" in str(issue.path) for issue in issues)
    assert any(issue.kind == "secret_pattern" and "OPENAI_API_KEY" in issue.detail for issue in issues)


def test_prepublish_pack_validator_rejects_runtime_artifacts() -> None:
    issues = validate_pack_file_list(
        [
            "package/fincli/app/main.py",
            "package/README.md",
            "package/.env",
            "package/fincli.db",
            "package/.npm-python/pyvenv.cfg",
        ]
    )

    assert SafetyIssue(Path("package/.env"), "pack_blocked_file", "sensitive package file") in issues
    assert any(issue.kind == "pack_blocked_file" and "fincli.db" in str(issue.path) for issue in issues)
    assert any(issue.kind == "pack_blocked_file" and ".npm-python" in str(issue.path) for issue in issues)


def test_prepublish_pack_validator_accepts_expected_manifest() -> None:
    issues = validate_pack_file_list(
        [
            "package/fincli/app/main.py",
            "package/npm/bin/fincli.js",
            "package/npm/postinstall.js",
            "package/pyproject.toml",
            "package/README.md",
            "package/requirements.txt",
        ]
    )

    assert issues == []


def test_secret_scan_prunes_generated_target_directory(tmp_path: Path) -> None:
    generated = tmp_path / "desktop" / "src-tauri" / "target" / "release"
    generated.mkdir(parents=True)
    (generated / "generated.py").write_text("OPENAI_API_KEY=real-secret-value-12345", encoding="utf-8")
    (tmp_path / "safe.py").write_text("value = 'safe'", encoding="utf-8")

    assert find_secret_issues(tmp_path) == []


def test_pip_audit_missing_module_fails_closed(monkeypatch: object) -> None:
    from subprocess import CompletedProcess

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "scripts.prepublish_check.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 1, stdout="", stderr="No module named pip_audit"),
    )

    issues = run_pip_audit()
    assert len(issues) == 1
    assert issues[0].kind == "audit_error"
