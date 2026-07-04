import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_npm_package_exposes_fincli_binary() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["bin"]["fincli"] == "npm/bin/fincli.js"
    # postinstall removed to avoid socket.dev security alerts
    assert "postinstall" not in package["scripts"]
    assert "fincli/**/*.py" in package["files"]
    assert "pyproject.toml" in package["files"]


def test_npm_wrapper_files_exist_and_are_node_scripts() -> None:
    bin_file = ROOT / "npm" / "bin" / "fincli.js"
    setup = ROOT / "npm" / "setup.js"

    assert bin_file.exists()
    assert setup.exists()
    assert bin_file.read_text(encoding="utf-8").startswith("#!/usr/bin/env node")
    assert setup.read_text(encoding="utf-8").startswith("#!/usr/bin/env node")


def test_setup_enforces_minimum_python_version() -> None:
    """setup must reject Python older than pyproject's requires-python.

    Without a version gate, an old interpreter passes the --version probe, the
    venv is created, and `pip install .` fails with a cryptic setuptools error
    instead of a clear "needs Python 3.11+" message.
    """
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in pyproject

    setup = (ROOT / "npm" / "setup.js").read_text(encoding="utf-8")
    assert "MIN_PYTHON = [3, 11]" in setup
    assert "meetsMinimum" in setup
    # The probe must read the actual interpreter version, not just --version status.
    assert "sys.version_info" in setup


def test_update_notifier_helpers_detect_newer_versions() -> None:
    script = """
const notifier = require("./npm/bin/fincli.js");
const result = {
  parse: notifier.parseSemver("1.8.4"),
  newerPatch: notifier.shouldShowUpdate("1.8.4", "1.8.5"),
  newerMinor: notifier.shouldShowUpdate("1.8.4", "1.9.0"),
  older: notifier.shouldShowUpdate("1.8.4", "1.8.3"),
  same: notifier.shouldShowUpdate("1.8.4", "1.8.4"),
  invalid: notifier.shouldShowUpdate("1.8.4", "latest"),
};
console.log(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload == {
        "parse": [1, 8, 4],
        "newerPatch": True,
        "newerMinor": True,
        "older": False,
        "same": False,
        "invalid": False,
    }


def test_update_banner_is_ascii_and_actionable() -> None:
    script = """
const notifier = require("./npm/bin/fincli.js");
notifier.showUpdateBanner("1.8.4", "1.8.5");
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout == ""
    assert "Update available: 1.8.4 -> 1.8.5" in result.stderr
    assert "Run: npm i -g @drico2008/fincli" in result.stderr
    assert "â" not in result.stderr
