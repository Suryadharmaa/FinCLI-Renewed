"""Authenticated v3 API; background work keeps the local UI responsive."""

from __future__ import annotations

import asyncio
import base64
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from fincli.app.workspace.service import WorkspaceService

from fastapi import Depends, HTTPException

from fincli.app.workspace.documents import MAX_BYTES


def register_workspace_routes(app, authorize, command_router) -> None:
    def service() -> WorkspaceService:
        return cast("WorkspaceService", command_router().workspace_service)

    @app.get("/api/workspace/job-status", dependencies=[Depends(authorize)])
    async def job_status(ids: str = "") -> dict[str, Any]:
        selected = ids.split(",") if ids else []
        if len(selected) > 12:
            raise HTTPException(status_code=422, detail="At most 12 job statuses per request")
        states = {}
        for job_id in selected:
            try:
                states[job_id] = service().jobs.get(job_id)
            except ValueError:
                states[job_id] = {"status": "failed", "error": "Job expired or not found"}
        return {"jobs": states}

    @app.get("/api/workspace/watchlist", dependencies=[Depends(authorize)])
    async def watchlist() -> dict[str, Any]:
        return {"items": command_router().watchlist.list()}

    @app.get("/api/workspace/runs/{run_id}/export", dependencies=[Depends(authorize)])
    async def export_run(run_id: str):
        from fastapi.responses import Response

        try:
            content = await asyncio.to_thread(service().excel_bytes, run_id)
            return Response(
                content,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="fincli-screen.xlsx"'},
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/workspace/layouts", dependencies=[Depends(authorize)])
    async def layouts() -> dict[str, Any]:
        return {"layouts": service().store.layouts()}

    @app.post("/api/workspace/layouts", dependencies=[Depends(authorize)])
    async def save_layout(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return service().store.save_layout(str(payload.get("name", "research")), payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/workspace/jobs", dependencies=[Depends(authorize)])
    async def start_job(payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", ""))
        if action not in {
            "market",
            "company",
            "peers",
            "news",
            "portfolio",
            "documents",
            "screen",
            "valuation",
            "workflow",
            "backtest",
        }:
            raise HTTPException(status_code=422, detail="Unsupported workspace action")
        params = payload.get("params", {})
        if not isinstance(params, dict):
            raise HTTPException(status_code=422, detail="params must be an object")
        import json

        if len(json.dumps(params)) > 20000:
            raise HTTPException(status_code=422, detail="Job input exceeds limit")
        workspace = service()
        try:
            return workspace.jobs.submit(lambda context: workspace.request(action, params, context), action)
        except ValueError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc

    @app.get("/api/workspace/jobs/{job_id}", dependencies=[Depends(authorize)])
    async def get_job(job_id: str) -> dict[str, Any]:
        try:
            return service().jobs.get(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/workspace/jobs/{job_id}", dependencies=[Depends(authorize)])
    async def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return service().jobs.cancel(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/workspace/documents", dependencies=[Depends(authorize)])
    async def documents(symbol: str = "") -> dict[str, Any]:
        try:
            return {"documents": service().documents.list(symbol)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/workspace/documents", dependencies=[Depends(authorize)])
    async def import_document(payload: dict[str, Any]) -> dict[str, Any]:
        encoded = payload.get("content", "")
        if not isinstance(encoded, str) or len(encoded) > (MAX_BYTES * 4 // 3 + 4):
            raise HTTPException(status_code=413, detail="Document exceeds 8 MiB")
        try:
            raw = base64.b64decode(encoded, validate=True)
            return await asyncio.to_thread(
                service().documents.import_bytes,
                str(payload.get("title", "document.txt")),
                raw,
                str(payload.get("symbol", "")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/workspace/documents/{document_id}/{page}", dependencies=[Depends(authorize)])
    async def document_page(document_id: str, page: int) -> dict[str, Any]:
        try:
            return service().documents.page(document_id, page)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/workspace/runs", dependencies=[Depends(authorize)])
    async def runs() -> dict[str, Any]:
        return {"runs": service().store.runs()}

    @app.get("/api/workspace/runs/{run_id}", dependencies=[Depends(authorize)])
    async def run(run_id: str) -> dict[str, Any]:
        try:
            return service().store.get_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/workspace/tradingview", dependencies=[Depends(authorize)])
    async def tradingview(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                service().tradingview.execute,
                str(payload.get("action", "capabilities")),
                payload.get("params", {}),
                payload.get("confirmed") is True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
