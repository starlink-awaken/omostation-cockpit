"""FastAPI endpoints for Cockpit Observatory unified data plane (BET-Y1Q4-T8-24A).

Routes:
    GET  /api/v1/observatory/snapshot  -> Full observable snapshot (with generation lock)
    GET  /api/v1/observatory/query     -> Query operation (search, entity, neighbors, brief, etc.)
    POST /api/v1/observatory/query     -> Query operation with complex params
    GET  /api/v1/observatory/catalogs  -> Catalog section
    GET  /api/v1/observatory/strategy  -> Strategy section
    GET  /api/v1/observatory/stream    -> SSE real-time incremental change stream
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cockpit.observatory.query_engine import QueryError
from cockpit.observatory.service import get_observatory_service

router = APIRouter(prefix="/api/v1/observatory", tags=["observatory"])


@router.get("/snapshot")
async def get_snapshot(
    generation: str | None = Query(None, description="Expected generation ID"),
    refresh: bool = Query(False, description="Force re-reading sources"),
) -> dict[str, Any]:
    """Retrieve the current observatory snapshot with generation locking."""
    service = get_observatory_service()
    try:
        snapshot = service.get_snapshot(force_refresh=refresh)
        if generation and snapshot.get("generation_id") != generation:
            raise HTTPException(
                status_code=409,
                detail=f"GENERATION_MISMATCH: requested {generation}, current {snapshot.get('generation_id')}",
            )
        return snapshot
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/query")
async def execute_get_query(
    operation: str = Query(..., description="Query operation (search, entity, brief, etc.)"),
    q: str | None = Query(None, description="Search query string"),
    kind: str | None = Query(None, description="Entity kind filter"),
    id: str | None = Query(None, description="Target entity ID"),
    lens: str | None = Query(None, description="Brief lens (overview, planner, executor, reviewer, operator)"),
    limit: int | None = Query(None, description="Max result count"),
    depth: int | None = Query(None, description="Graph traversal depth"),
    direction: str | None = Query(None, description="Graph traversal direction (in, out, both)"),
    cursor: str | None = Query(None, description="Pagination cursor"),
    generation: str | None = Query(None, description="Generation locking"),
) -> Any:
    """Execute a query against the in-memory observation index via GET."""
    service = get_observatory_service()
    params: dict[str, Any] = {}
    if q is not None:
        params["q"] = q
    if kind is not None:
        params["kind"] = kind
    if id is not None:
        params["id"] = id
    if lens is not None:
        params["lens"] = lens
    if limit is not None:
        params["limit"] = str(limit)
    if depth is not None:
        params["depth"] = str(depth)
    if direction is not None:
        params["direction"] = direction
    if cursor is not None:
        params["cursor"] = cursor
    if generation is not None:
        params["generation"] = generation

    try:
        return service.query(operation, params)
    except QueryError as e:
        raise HTTPException(status_code=e.status, detail=e.code) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/query")
async def execute_post_query(payload: dict[str, Any]) -> Any:
    """Execute a query against the in-memory observation index via POST."""
    service = get_observatory_service()
    operation = payload.get("operation")
    if not operation:
        raise HTTPException(status_code=400, detail="MISSING_OPERATION")
    params = payload.get("params", {})
    try:
        return service.query(operation, params)
    except QueryError as e:
        raise HTTPException(status_code=e.status, detail=e.code) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/catalogs")
async def get_catalogs() -> dict[str, Any]:
    """Retrieve raw catalog declarations (projects, capabilities, BOS services, MOF)."""
    service = get_observatory_service()
    return service.get_catalogs()


@router.get("/strategy")
async def get_strategy() -> dict[str, Any]:
    """Retrieve raw strategic ledger observations (BETs, milestones, metrics, evidence)."""
    service = get_observatory_service()
    return service.get_strategy()


@router.get("/stream")
async def stream_observatory_changes(
    request: Request,
    once: bool = Query(False, description="Send initial connected event and close"),
) -> StreamingResponse:
    """Server-Sent Events (SSE) stream for real-time observatory generation changes."""
    service = get_observatory_service()
    queue = await service.register_subscriber()

    async def event_generator() -> Any:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=2.0)
                    yield f"event: {msg['event']}\ndata: {msg['data']}\n\n"
                    if once:
                        break
                except asyncio.TimeoutError:
                    # Keepalive comment
                    yield ": keepalive\n\n"
        finally:
            service.unregister_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
