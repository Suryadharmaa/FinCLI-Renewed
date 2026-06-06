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
