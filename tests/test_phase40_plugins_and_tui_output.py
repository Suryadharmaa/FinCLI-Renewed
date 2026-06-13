from __future__ import annotations

import json
from pathlib import Path

from fincli.app.tui.theme import APP_CSS


class FakeLog:
    def __init__(self) -> None:
        self.items: list[object] = []

    def write(self, renderable: object) -> None:
        self.items.append(renderable)


def test_plugin_loader_discovers_manifest_files(tmp_path: Path) -> None:
    from fincli.app.plugins.loader import PluginLoader

    plugin_dir = tmp_path / "plugins" / "macro-kit"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "macro-kit",
                "version": "0.1.0",
                "description": "Macro research helpers",
                "commands": ["/macro liquidity"],
                "capabilities": ["macro", "research"],
            }
        ),
        encoding="utf-8",
    )

    plugins = PluginLoader([tmp_path / "plugins"]).discover()

    assert len(plugins) == 1
    assert plugins[0].name == "macro-kit"
    assert plugins[0].commands == ("/macro liquidity",)
    assert plugins[0].status == "available"


def test_plugin_command_routes_list_and_status(tmp_path: Path, monkeypatch) -> None:
    from fincli.app.cli.router import CommandRouter
    from fincli.app.storage.config import ConfigManager
    from fincli.app.storage.database import FinCLIDatabase
    from fincli.app.storage import config_paths

    plugin_dir = tmp_path / "plugins" / "news-kit"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        '{"name":"news-kit","version":"0.1.0","description":"News helpers","commands":["/news"],"capabilities":["news"]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_paths, "APP_DIR", tmp_path)

    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    assert router.route("/plugin list").status == "ready"
    assert router.route("/plugin status").status == "ready"


def test_output_entry_spacing_uses_single_blank_line_without_barriers() -> None:
    from fincli.app.tui.components import write_output_entry

    log = FakeLog()
    write_output_entry(log, "first")
    write_output_entry(log, "second")

    assert log.items == ["first", "", "second"]
    assert all("<<<" not in str(item) and ">>>" not in str(item) for item in log.items)


def test_tui_css_has_professional_financial_terminal_surface() -> None:
    assert "#top_strip" in APP_CSS
    assert "#output_frame" in APP_CSS
    assert "#command_line" in APP_CSS
    assert "border: heavy #15803d" in APP_CSS
