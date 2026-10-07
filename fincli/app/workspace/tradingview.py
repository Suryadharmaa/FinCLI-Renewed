"""Optional external TradingView CLI bridge; chart controls only, no scraped data feed."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from fincli.app.workspace.models import Instrument, result

# Deliberately exclude raw OHLCV extraction, scripting eval, broker/replay orders, and credential APIs.
READ_ACTIONS = {"status": ["status"], "chart": ["state"]}


class TradingViewBridge:
    def __init__(self, cli_path: str | None = None):
        self.cli_path = cli_path or os.getenv("FINCLI_TV_CLI", "")

    def capabilities(self) -> dict[str, Any]:
        return result(
            "tradingview_capabilities",
            {
                "configured": bool(self.cli_path),
                "bridge": "external tradesdontlie CLI",
                "actions": [
                    "status",
                    "chart",
                    "symbol",
                    "timeframe",
                    "indicator",
                    "draw",
                    "pine",
                    "replay",
                    "screenshot",
                ],
                "source_repo": "https://github.com/tradesdontlie/tradingview-mcp",
                "requires": "TradingView Desktop and user-enabled local debug interface",
                "data_provider": False,
                "orders": False,
            },
            warnings=[
                "Unofficial optional bridge. TradingView permissions and data terms apply. Internal UI APIs may change."
            ],
        )

    def execute(self, action: str, params: dict[str, Any] | None = None, confirmed: bool = False) -> dict[str, Any]:
        if params is not None and not isinstance(params, dict):
            raise ValueError("TradingView params must be an object.")
        params = params or {}
        if action == "capabilities":
            return self.capabilities()
        if not self.cli_path:
            raise ValueError(
                "Bridge not configured. Set FINCLI_TV_CLI to the absolute path of src/cli/index.js in a separately installed bridge."
            )
        path = Path(self.cli_path).expanduser()
        if not path.is_absolute() or not path.is_file() or path.name != "index.js":
            raise ValueError("FINCLI_TV_CLI must point to a local absolute CLI index.js path.")
        args = READ_ACTIONS.get(action)
        if args is None:
            if not confirmed:
                raise ValueError("TradingView changes require explicit --confirm or UI confirmation.")
            if action == "symbol":
                args = ["symbol", Instrument.parse(str(params.get("symbol", ""))).symbol]
            elif action == "timeframe":
                value = str(params.get("timeframe", ""))
                if value not in {"1", "5", "15", "30", "60", "240", "D", "W", "M"}:
                    raise ValueError("Unsupported TradingView timeframe.")
                args = ["timeframe", value]
            elif action == "indicator":
                name = str(params.get("name", ""))
                if not name or len(name) > 100 or name.startswith("-"):
                    raise ValueError("Provide a valid indicator name.")
                args = ["indicator", "add", name]
            elif action == "draw":
                from fincli.app.workspace.models import finite

                price = finite(params.get("price"))
                if price is None or price <= 0:
                    raise ValueError("Positive finite price required.")
                args = [
                    "draw",
                    "shape",
                    "--type",
                    "horizontal_line",
                    "--price",
                    str(price),
                    "--time",
                    str(int(time.time())),
                ]
            elif action == "pine":
                # Compile current editor content only; never inject arbitrary JS or cloud-save automatically.
                args = ["pine", "compile"]
            elif action == "replay":
                args = ["replay", "step"]
            elif action == "screenshot":
                args = ["screenshot", "-r", "chart"]
            else:
                raise ValueError("Unsupported TradingView action.")
        try:
            completed = subprocess.run(
                ["node", str(path), *args],
                shell=False,
                capture_output=True,
                timeout=25,
                text=True,
                env={**os.environ, "TV_CDP_HOST": "127.0.0.1", "CDP_HOST": "127.0.0.1"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("TradingView bridge unavailable or timed out.") from exc
        if completed.returncode:
            raise ValueError("Bridge failed. Check local TradingView connection and compatibility.")
        if len(completed.stdout) > 2_000_000:
            raise ValueError("Bridge output exceeds limit.")
        try:
            payload = json.loads(completed.stdout)
        except ValueError as exc:
            raise ValueError("Bridge returned invalid JSON.") from exc
        if isinstance(payload, dict) and payload.get("success") is False:
            raise ValueError("TradingView action did not succeed.")
        return result(
            "tradingview",
            payload,
            source="TradingView local UI",
            warnings=["UI observation only; not used by FinCLI valuation, backtest, portfolio risk, or order routing."],
        )
