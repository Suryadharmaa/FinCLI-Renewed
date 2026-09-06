"""FastAPI application for local FinCLI web access."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from starlette.requests import Request  # noqa: TC002

from fincli import __version__
from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.manager import AI_PROVIDERS
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.secrets import save_secret
from fincli.app.web.bridge import (
    CommandExecutionContext,
    OutputMode,
    WebCommandResult,
    WebError,
    execute_command,
    infer_command,
    is_secret_command,
    redact_sensitive_command,
)
from fincli.app.web.desktop_actions import ACTION_BY_NAME, command_for_action, desktop_capabilities
from fincli.app.web.security import LocalRateLimiter, command_requires_confirmation, rotate_token, token_matches
from fincli.app.web.store import WebStore

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")
VALID_SECRET_KEYS: set[str] = {info.env_key for info in AI_PROVIDERS.values() if info.env_key} | {
    "FINNHUB_API_KEY", "TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY", "POLYGON_API_KEY", "IEX_CLOUD_API_KEY",
    "MARKET_DATA_API_KEY", "NEWS_DATA_API_KEY", "MARKETAUX_API_KEY", "NEWSAPI_API_KEY", "GNEWS_API_KEY",
    "STOCKNEWSAPI_API_KEY", "APITUBE_API_KEY", "BENZINGA_API_KEY", "TIINGO_API_KEY", "FMP_API_KEY", "EODHD_API_KEY",
    "CUSTOM_NEWS_API_KEY",
}


def create_app() -> Any:
    try:
        from fastapi import Depends, FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError('Web dependencies missing. Install with: pip install -e ".[web]"') from exc

    config = ConfigManager()
    desktop_mode = os.getenv("FINCLI_DESKTOP") == "1"
    db = FinCLIDatabase()
    store = WebStore(db)
    limiter = LocalRateLimiter()
    router: CommandRouter | None = None
    app = FastAPI(title="FinCLI Local API", version=__version__, docs_url=None, redoc_url=None)
    allowed_origins = list(config.settings.web.allowed_origins)
    if desktop_mode:
        allowed_origins.extend(["http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(dict.fromkeys(allowed_origins)),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-FinCLI-CSRF"],
    )

    def command_router() -> CommandRouter:
        nonlocal router
        if router is None:
            config.reload()
            router = CommandRouter(config=config, db=db)
        return router

    async def authorize(request: Request) -> None:
        client = request.client.host if request.client else "local"
        if client not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            logger.warning("Auth denied: non-local client %s", client)
            raise HTTPException(status_code=403, detail="Local access only")
        if not limiter.allow(client):
            logger.warning("Auth rate-limited: client=%s", client)
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        if config.settings.web.require_auth:
            authorization = request.headers.get("authorization", "")
            token = authorization.removeprefix("Bearer ").strip() if authorization else None
            logger.info("Auth attempt: token_len=%s, client=%s", len(token or ""), client)
            if not token_matches(token):
                logger.warning("Auth failed: invalid token, client=%s", client)
                raise HTTPException(status_code=401, detail="Invalid local access token")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf = request.headers.get("X-FinCLI-CSRF", "")
            if csrf != "local-web":
                raise HTTPException(status_code=403, detail="Missing CSRF header")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "local_only": desktop_mode or config.settings.web.host == "127.0.0.1"}

    @app.get("/api/status", dependencies=[Depends(authorize)])
    async def status() -> dict[str, Any]:
        settings = config.settings
        return {
            "version": __version__,
            "ai_provider": settings.ai_provider,
            "ai_model": settings.ai_model,
            "market_provider": settings.market_provider,
            "auth": settings.web.require_auth,
            "mode": "desktop" if desktop_mode else "browser",
            "desktop": desktop_mode,
            "api_contract": "2.0",
        }

    @app.get("/api/desktop/info", dependencies=[Depends(authorize)])
    async def desktop_info() -> dict[str, Any]:
        """Expose the stable capability contract used by the Tauri workspace."""
        return {
            "ok": True,
            "desktop": desktop_mode,
            "version": __version__,
            "backend": "fastapi",
            "router": "CommandRouter",
            "local_only": config.settings.web.host == "127.0.0.1",
            "capabilities": {
                "research": True,
                "portfolio": True,
                "watchlist": True,
                "provider_status": True,
                "secrets": True,
                "paper_trading": True,
                "live_trading": True,
            },
        }

    @app.get("/api/ai/status", dependencies=[Depends(authorize)])
    async def ai_status() -> dict[str, Any]:
        settings = config.settings
        provider_name = settings.ai_provider
        model_name = settings.ai_model
        info = AI_PROVIDERS.get(provider_name)
        has_key = bool(os.getenv(info.env_key)) if info else False
        available = []
        for name, pinfo in AI_PROVIDERS.items():
            available.append({
                "provider": name,
                "active": name == provider_name,
                "has_api_key": bool(os.getenv(pinfo.env_key)),
                "model": model_name if name == provider_name else pinfo.default_model,
            })
        return {
            "ok": True,
            "provider": provider_name,
            "model": model_name,
            "display_name": f"{provider_name} / {model_name}",
            "has_api_key": has_key,
            "source": "fincli-config",
            "available_providers": available,
        }

    @app.post("/api/ai/reload", dependencies=[Depends(authorize)])
    async def ai_reload() -> dict[str, Any]:
        nonlocal router
        config.reload()
        router = None
        return {"ok": True, "provider": config.settings.ai_provider, "model": config.settings.ai_model}

    @app.get("/api/config", dependencies=[Depends(authorize)])
    async def safe_config() -> dict[str, Any]:
        return {"web": config.settings.safe_dict()["web"], "theme": config.settings.theme}

    @app.get("/api/commands", dependencies=[Depends(authorize)])
    async def commands(query: str = "") -> dict[str, Any]:
        registry = CommandRegistry()
        specs = registry.suggest(query, limit=200) if query.strip() else list(registry.all())
        rows = [
            {
                "name": spec.name,
                "description": spec.description,
                "example": spec.example,
                "group": spec.group,
                "confirmation_required": command_requires_confirmation(spec.example),
                "terminal_only_secret": spec.name in {"/ai_model key", "/notification add"},
                "desktop_supported": spec.name not in {"/ai_model", "/news_model", "/ai_model key", "/notification add"},
            }
            for spec in specs
        ]
        return {"ok": True, "count": len(rows), "commands": rows}

    @app.get("/api/desktop/capabilities", dependencies=[Depends(authorize)])
    async def desktop_capability_contract() -> dict[str, Any]:
        """Return the complete command inventory plus GUI action forms."""
        capabilities = desktop_capabilities()
        return {
            "ok": True,
            "api_contract": "2.1",
            "command_count": len(capabilities["commands"]),
            "commands": capabilities["commands"],
            "actions": capabilities["actions"],
        }

    @app.get("/api/desktop/overview", dependencies=[Depends(authorize)])
    async def desktop_overview(symbol: str = "") -> dict[str, Any]:
        """Build a quick local workspace summary without inventing market data."""
        portfolio_rows = db.query("SELECT COUNT(*) AS count FROM portfolio_positions")
        watchlist_rows = db.query("SELECT COUNT(*) AS count FROM watchlist")
        alert_rows = db.query("SELECT COUNT(*) AS count FROM alerts WHERE active = 1")
        provider_rows = db.query(
            "SELECT provider, calls, successes, errors, last_status FROM provider_metrics ORDER BY provider"
        )
        market: dict[str, Any] = {
            "status": "idle",
            "message": "Select a symbol to load market data.",
            "symbol": "",
        }
        if symbol.strip():
            result = await asyncio.to_thread(execute_command, command_router(), f"/market {symbol.strip()} 1d")
            market = result.to_dict()
            market["symbol"] = symbol.strip().upper()
        return {
            "ok": True,
            "market": market,
            "portfolio": {"positions": int(portfolio_rows[0]["count"]) if portfolio_rows else 0},
            "watchlist": {"count": int(watchlist_rows[0]["count"]) if watchlist_rows else 0},
            "providers": [dict(row) for row in provider_rows],
            "provider_trust": {"status": "available" if provider_rows else "not_called", "count": len(provider_rows)},
            "alerts": {"active": int(alert_rows[0]["count"]) if alert_rows else 0},
        }

    @app.post("/api/desktop/action", dependencies=[Depends(authorize)])
    async def desktop_action(payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", "")).strip()
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        spec = ACTION_BY_NAME.get(action)
        if spec is None:
            raise HTTPException(status_code=422, detail=f"Unknown desktop action: {action}")
        if not spec.desktop_supported:
            raise HTTPException(status_code=422, detail=spec.terminal_only_reason or "Action is not supported on desktop.")
        try:
            built_command = command_for_action(action, params)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if spec.confirmation_required and not bool(payload.get("confirmed")):
            result = WebCommandResult(
                False,
                "error",
                redact_sensitive_command(built_command),
                "confirmation_required",
                title="Confirmation required",
                message="This action requires explicit confirmation before it can run.",
                errors=[WebError(
                    title="Confirmation required",
                    message="Review the action in the desktop confirmation dialog, then confirm it explicitly.",
                    code="CONFIRMATION_REQUIRED",
                )],
                metadata={"action": action},
            )
            response = result.to_dict()
            response["action"] = action
            response["conversation_id"] = str(payload.get("conversation_id", ""))
            return response
        result = await asyncio.to_thread(
            execute_command,
            command_router(),
            built_command,
            bool(payload.get("confirmed")),
            CommandExecutionContext(
                output_mode=OutputMode.WEB,
                source="desktop",
                user_confirmed=bool(payload.get("confirmed")),
            ),
        )
        conversation_id = str(payload.get("conversation_id", ""))
        if spec.history_safe and conversation_id and store.get_conversation(conversation_id):
            store.add_message(conversation_id, "user", f"{spec.label}: {built_command}", built_command)
            store.add_message(conversation_id, "assistant", result.content, built_command, {"action": action, "status": result.status})
        store.audit("desktop_action", action)
        response = result.to_dict()
        response["action"] = action
        response["conversation_id"] = conversation_id
        return response

    @app.get("/api/conversations", dependencies=[Depends(authorize)])
    async def conversations() -> list[dict[str, Any]]:
        return store.list_conversations()

    @app.post("/api/conversations", dependencies=[Depends(authorize)])
    async def create_conversation(payload: dict[str, Any]) -> dict[str, Any]:
        return store.create_conversation(
            str(payload.get("title", "New chat")), config.settings.ai_provider, config.settings.ai_model
        )

    @app.get("/api/conversations/{conversation_id}", dependencies=[Depends(authorize)])
    async def conversation(conversation_id: str) -> dict[str, Any]:
        item = store.get_conversation(conversation_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return item

    @app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(authorize)])
    async def delete_conversation(conversation_id: str) -> dict[str, bool]:
        return {"deleted": store.delete_conversation(conversation_id)}

    async def run_chat(payload: dict[str, Any]) -> dict[str, Any]:
        message = str(payload.get("message", "")).strip()
        if not message:
            raise HTTPException(status_code=422, detail="Message is required")
        conversation_id = str(payload.get("conversation_id", ""))
        command = infer_command(message)
        if is_secret_command(command):
            result = await asyncio.to_thread(execute_command, command_router(), command, bool(payload.get("confirmed")))
            store.audit("command_blocked", redact_sensitive_command(command))
            response = result.to_dict()
            response["conversation_id"] = conversation_id if store.get_conversation(conversation_id) else ""
            return response
        if not store.get_conversation(conversation_id):
            conversation_id = store.create_conversation(message[:60], config.settings.ai_provider, config.settings.ai_model)["id"]
        store.add_message(conversation_id, "user", message, command)
        result = await asyncio.to_thread(execute_command, command_router(), command, bool(payload.get("confirmed")))
        store.add_message(conversation_id, "assistant", result.content, command, {"status": result.status})
        store.audit("command", redact_sensitive_command(command))
        response = result.to_dict()
        response["conversation_id"] = conversation_id
        return response

    @app.post("/api/chat", dependencies=[Depends(authorize)])
    async def chat(payload: dict[str, Any]) -> dict[str, Any]:
        return await run_chat(payload)

    @app.post("/api/chat/stream", dependencies=[Depends(authorize)])
    async def chat_stream(payload: dict[str, Any]) -> StreamingResponse:
        async def events():
            yield "event: status\ndata: {\"status\":\"working\"}\n\n"
            result = await run_chat(payload)
            content = result.get("markdown") or result.get("text") or result.get("message") or ""
            for index in range(0, len(content), 80):
                data = json.dumps({"token": content[index : index + 80]})
                yield f"event: token\ndata: {data}\n\n"
                await asyncio.sleep(0)
            yield f"event: done\ndata: {json.dumps(result)}\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/command", dependencies=[Depends(authorize)])
    async def command(payload: dict[str, Any]) -> dict[str, Any]:
        raw = str(payload.get("command", ""))
        result = await asyncio.to_thread(execute_command, command_router(), raw, bool(payload.get("confirmed")))
        store.audit("command", redact_sensitive_command(raw))
        return result.to_dict()

    @app.get("/api/providers/status", dependencies=[Depends(authorize)])
    async def providers() -> dict[str, Any]:
        response: dict[str, Any] = await command({"command": "/provider trust"})
        return response

    @app.get("/api/portfolio", dependencies=[Depends(authorize)])
    async def portfolio() -> dict[str, Any]:
        response: dict[str, Any] = await command({"command": "/portfolio"})
        return response

    @app.get("/api/watchlist", dependencies=[Depends(authorize)])
    async def watchlist() -> dict[str, Any]:
        response: dict[str, Any] = await command({"command": "/watchlist"})
        return response

    @app.get("/api/research/{symbol}", dependencies=[Depends(authorize)])
    async def research(symbol: str) -> dict[str, Any]:
        response: dict[str, Any] = await command({"command": f"/research {symbol}"})
        return response

    @app.get("/api/logs", dependencies=[Depends(authorize)])
    async def logs() -> list[dict[str, Any]]:
        return store.logs()

    @app.post("/api/web/token/rotate", dependencies=[Depends(authorize)])
    async def token_rotate() -> dict[str, str]:
        token = rotate_token()
        store.audit("token_rotate", "Local web access token rotated")
        return {"token": token}

    @app.get("/api/secrets", dependencies=[Depends(authorize)])
    async def list_secrets() -> dict[str, Any]:
        ai_keys = {name: {"env_key": info.env_key, "has_key": bool(os.getenv(info.env_key))} for name, info in AI_PROVIDERS.items() if info.env_key}
        market_manager = MarketProviderManager()
        market_keys = []
        for row in market_manager.key_status():
            if row["key"] != "-":
                market_keys.append({"provider": row["provider"], "env_key": row["key"], "has_key": row["status"] == "set", "source": row["source"]})
        return {"ok": True, "ai_keys": ai_keys, "market_keys": market_keys}

    @app.post("/api/secrets", dependencies=[Depends(authorize)])
    async def set_secret(payload: dict[str, Any]) -> dict[str, Any]:
        key = str(payload.get("key", "")).strip().upper()
        value = str(payload.get("value", "")).strip()
        if not key or not value:
            raise HTTPException(status_code=422, detail="Both key and value are required.")
        if key not in VALID_SECRET_KEYS:
            raise HTTPException(status_code=422, detail=f"Unknown secret key: {key}")
        try:
            save_secret(key, value)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        store.audit("secret_set", f"Secret {key} updated via web UI")
        nonlocal router
        router = None
        return {"ok": True, "key": key, "message": f"{key} saved and loaded."}

    @app.exception_handler(Exception)
    async def unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
        store.audit("server_error", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Local server error"})

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/{path:path}")
    async def web_ui(path: str) -> FileResponse:
        target = STATIC_DIR / path
        return FileResponse(target if target.is_file() else STATIC_DIR / "index.html")

    return app
