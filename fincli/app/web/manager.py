"""Lifecycle management for the optional local web server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import webbrowser
from dataclasses import asdict
from typing import Any
from urllib.request import urlopen

from fincli.app.storage.config import ConfigManager
from fincli.app.storage.config_paths import APP_DIR
from fincli.app.web.security import get_or_create_token, rotate_token

STATE_FILE = APP_DIR / "web_server.json"
LOG_FILE = APP_DIR / "web_server.log"


class WebServerManager:
    def __init__(self, config: ConfigManager | None = None) -> None:
        self.config = config or ConfigManager()

    @property
    def url(self) -> str:
        host = self.config.settings.web.host
        display_host = "localhost" if host == "127.0.0.1" else host
        return f"http://{display_host}:{self.config.settings.web.port}"

    def status(self) -> dict[str, Any]:
        state = self._read_state()
        running = self._healthy()
        started = float(state.get("started_at", 0))
        return {
            "running": running,
            "host": self.config.settings.web.host,
            "port": self.config.settings.web.port,
            "url": self.url,
            "auth": self.config.settings.web.require_auth,
            "active_sessions": 0,
            "uptime_seconds": max(0, int(time.time() - started)) if running and started else 0,
            "pid": state.get("pid"),
        }

    def start(self, reload: bool = False) -> dict[str, Any]:
        if self._healthy():
            return self.status()
        get_or_create_token()
        APP_DIR.mkdir(parents=True, exist_ok=True)
        log = LOG_FILE.open("a", encoding="utf-8")
        command = [sys.executable, "-m", "uvicorn", "fincli.app.web.api:create_app", "--factory", "--host", self.config.settings.web.host, "--port", str(self.config.settings.web.port)]
        if reload:
            command.append("--reload")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
        finally:
            log.close()
        STATE_FILE.write_text(json.dumps({"pid": process.pid, "started_at": time.time()}), encoding="utf-8")
        self.config.settings.web.enabled = True
        self.config.save()
        return self.status()

    def stop(self) -> bool:
        state = self._read_state()
        pid = state.get("pid")
        if not isinstance(pid, int):
            return False
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
            else:
                os.kill(pid, 15)
        finally:
            STATE_FILE.unlink(missing_ok=True)
            self.config.settings.web.enabled = False
            self.config.save()
        return True

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    def open(self) -> str:
        webbrowser.open(self.url)
        return self.url

    def rotate_token(self) -> str:
        return rotate_token()

    def logs(self, lines: int = 50) -> str:
        if not LOG_FILE.exists():
            return "No web server logs yet."
        return "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

    def config_dict(self) -> dict[str, Any]:
        return asdict(self.config.settings.web)

    def set_config(self, key: str, value: str) -> None:
        web = self.config.settings.web
        if key not in web.__dataclass_fields__:
            raise ValueError(f"Unknown web setting: {key}")
        current = getattr(web, key)
        if isinstance(current, bool):
            parsed: Any = value.lower() in {"1", "true", "yes", "on"}
        elif isinstance(current, int):
            parsed = int(value)
        elif isinstance(current, list):
            parsed = [item.strip() for item in value.split(",") if item.strip()]
        else:
            parsed = value
        if key == "port" and not 1024 <= parsed <= 65535:
            raise ValueError("Port must be between 1024 and 65535.")
        setattr(web, key, parsed)
        self.config.save()

    def _healthy(self) -> bool:
        try:
            with urlopen(f"{self.url}/api/health", timeout=0.25) as response:
                return response.status == 200
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _read_state() -> dict[str, Any]:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
