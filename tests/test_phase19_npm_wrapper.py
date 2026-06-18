import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_npm_package_exposes_fincli_binary() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["bin"]["fincli"] == "npm/bin/fincli.js"
    assert package["scripts"]["postinstall"] == "node npm/postinstall.js"
    assert "fincli/**/*.py" in package["files"]
    assert "pyproject.toml" in package["files"]


def test_npm_wrapper_files_exist_and_are_node_scripts() -> None:
    bin_file = ROOT / "npm" / "bin" / "fincli.js"
    postinstall = ROOT / "npm" / "postinstall.js"

    assert bin_file.exists()
    assert postinstall.exists()
    assert bin_file.read_text(encoding="utf-8").startswith("#!/usr/bin/env node")
    assert postinstall.read_text(encoding="utf-8").startswith("#!/usr/bin/env node")


def test_postinstall_enforces_minimum_python_version() -> None:
    """postinstall must reject Python older than pyproject's requires-python.

    Without a version gate, an old interpreter passes the --version probe, the
    venv is created, and `pip install .` fails with a cryptic setuptools error
    instead of a clear "needs Python 3.11+" message.
    """
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in pyproject

    postinstall = (ROOT / "npm" / "postinstall.js").read_text(encoding="utf-8")
    assert "MIN_PYTHON = [3, 11]" in postinstall
    assert "meetsMinimum" in postinstall
    # The probe must read the actual interpreter version, not just --version status.
    assert "sys.version_info" in postinstall
