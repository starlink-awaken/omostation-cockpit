"""Console Harness routes — run management + SSE stream.

Endpoints:
    GET  /api/console/harness/stages     — 8 stage definitions
    GET  /api/console/harness/profiles   — 19 agent profiles
    POST /api/console/harness/runs       — submit new run
    GET  /api/console/harness/runs       — list runs
    GET  /api/console/harness/runs/{id}  — run detail
    GET  /api/console/harness/runs/{id}/events — SSE event stream
    POST /api/console/harness/runs/{id}/cancel — cancel run
    POST /api/console/harness/runs/{id}/confirm — HITL gate approval
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cockpit.console.harness_runner import STAGES, get_runner
from cockpit.console.models import HarnessRunSpec
from cockpit.console.events import get_hub
from cockpit.console.risk import RiskLevel, require_confirm

router = APIRouter(prefix="/api/console/harness", tags=["console-harness"])

# 19 agent profiles from agent-workflows/profiles/_base.yaml
PROFILES = [
    "governance-agent", "engineering-agent", "docs-agent", "qa-agent",
    "state-sync-agent", "mof-agent", "c2g-agent", "strategy-agent",
    "adapter-agent", "release-agent", "observer-agent", "any-agent",
    "sage-planner", "builder-agent", "keeper-cartridge", "devil-challenger",
    "external-readonly-agent", "external-contributor-agent", "cognitive-agent",
]

STAGE_DESCRIPTIONS = {
    "admission": "BET 准入检查",
    "spec": "Spec 校验",
    "grill": "5Q 质量检查",
    "dispatch": "工作流调度",
    "execute": "任务执行",
    "verify": "验证 DAG",
    "audit": "审计报告",
    "accept": "分级验收",
}


def _envelope(ok: bool, data: Any = None, error_code: str | None = None, error: str | None = None) -> dict:
    return {"ok": ok, "error_code": error_code, "error": error, "data": data}


@router.get("/stages")
async def api_harness_stages():
    """Get 8 stage definitions."""
    stages = [
        {"id": s, "description": STAGE_DESCRIPTIONS.get(s, s)}
        for s in STAGES
    ]
    return JSONResponse(_envelope(True, data=stages))


@router.get("/profiles")
async def api_harness_profiles():
    """Get available agent profiles."""
    return JSONResponse(_envelope(True, data=PROFILES))


@router.post("/runs")
async def api_harness_submit(
    request: Request,
    x_console_confirm: str | None = Header(default=None, alias="X-Console-Confirm"),
):
    """Submit a new Harness run."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_envelope(False, error_code="MISSING_FIELD", error="Request body must be JSON"), status_code=400)

    bet_id = body.get("bet_id", "")
    profile = body.get("profile", "")
    objective = body.get("objective", "")
    worktree_path = body.get("worktree_path", "")
    dry_run = body.get("dry_run", False)

    if not bet_id or not profile or not objective or not worktree_path:
        return JSONResponse(
            _envelope(False, error_code="MISSING_FIELD", error="bet_id, profile, objective, and worktree_path are required"),
            status_code=400,
        )

    # Harness runs are always dangerous — verify confirm token against body
    body_bytes = json.dumps(
        {"bet_id": bet_id, "profile": profile, "objective": objective, "worktree_path": worktree_path, "dry_run": dry_run},
        sort_keys=True,
    ).encode()
    rejection = require_confirm(RiskLevel.DANGEROUS, f"harness/run/{bet_id}", body_bytes, x_console_confirm)
    if rejection:
        status = 400 if rejection == "RISK_CONFIRM_REQUIRED" else 403
        return JSONResponse(
            _envelope(False, error_code=rejection, error="Harness run requires X-Console-Confirm"),
            status_code=status,
        )

    spec = HarnessRunSpec(
        bet_id=bet_id,
        profile=profile,
        objective=objective,
        worktree_path=worktree_path,
        dry_run=dry_run,
    )

    runner = get_runner()
    run_id, error = await runner.submit(spec)

    if error:
        status = 409 if error in ("RUNNER_SATURATED", "WORKTREE_REQUIRED", "CIRCUIT_BREAKER_TRIPPED") else 500
        return JSONResponse(_envelope(False, error_code=error, error=error), status_code=status)

    run_data = runner.run_detail(run_id)
    return JSONResponse(_envelope(True, data=run_data), status_code=202)


@router.get("/runs")
async def api_harness_list(limit: int = 50):
    """List run records."""
    runner = get_runner()
    runs = runner.list_runs(limit=limit)
    return JSONResponse(_envelope(True, data={"runs": runs}))


@router.get("/runs/{run_id}")
async def api_harness_detail(run_id: str):
    """Get run detail."""
    runner = get_runner()
    detail = runner.run_detail(run_id)
    if not detail:
        return JSONResponse(_envelope(False, error_code="RUN_NOT_FOUND", error=f"Run {run_id} not found"), status_code=404)
    return JSONResponse(_envelope(True, data=detail))


@router.get("/runs/{run_id}/events")
async def api_harness_events(run_id: str, request: Request):
    """SSE event stream for a Harness run."""
    hub = get_hub()
    queue = await hub.subscribe(run_id)

    # Check Last-Event-ID for replay
    last_event_id = request.headers.get("Last-Event-ID")

    async def event_generator():
        try:
            # Send connected event
            initial = {
                "event": "connected",
                "run_id": run_id,
                "seq": 0,
                "stages": list(STAGES),
            }
            yield f"id: 0\nevent: connected\ndata: {json.dumps(initial)}\n\n"

            # Replay missed events
            if last_event_id:
                try:
                    from_seq = int(last_event_id)
                    replay = hub.replay_from(run_id, from_seq)
                    for event in replay:
                        yield f"id: {event['seq']}\nevent: {event.get('event', 'run_progress')}\ndata: {json.dumps(event)}\n\n"
                except (ValueError, TypeError):
                    pass

            # Stream new events
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=2.0)
                    seq = msg.get("seq", 0)
                    event_name = msg.get("event", "run_progress")
                    yield f"id: {seq}\nevent: {event_name}\ndata: {json.dumps(msg)}\n\n"

                    if event_name == "run_complete":
                        # Send one final keepalive then close
                        yield ": keepalive\n\n"
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await hub.forget_if_empty(run_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel")
async def api_harness_cancel(
    run_id: str,
    x_console_confirm: str | None = Header(default=None, alias="X-Console-Confirm"),
):
    """Cancel a running Harness run."""
    if not x_console_confirm:
        return JSONResponse(_envelope(False, error_code="RISK_CONFIRM_REQUIRED", error="Cancellation requires confirmation"), status_code=400)

    runner = get_runner()
    success = await runner.cancel(run_id)
    if not success:
        return JSONResponse(_envelope(False, error_code="RUN_NOT_FOUND", error="Run not found or already finished"), status_code=404)

    return JSONResponse(_envelope(True, data={"cancelled": True}))


@router.post("/runs/{run_id}/confirm")
async def api_harness_confirm(
    run_id: str,
    request: Request,
    x_console_confirm: str | None = Header(default=None, alias="X-Console-Confirm"),
):
    """Approve a HITL gate."""
    if not x_console_confirm:
        return JSONResponse(_envelope(False, error_code="RISK_CONFIRM_REQUIRED", error="Gate approval requires confirmation"), status_code=400)

    try:
        body = await request.json()
    except Exception:
        body = {}

    approved = body.get("approved", True)
    note = body.get("note", "")

    # Publish confirmation event to the run
    hub = get_hub()
    await hub.publish(run_id, {
        "event": "gate_resolved",
        "gate": body.get("gate", ""),
        "approved": approved,
        "note": note,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    return JSONResponse(_envelope(True, data={"confirmed": approved}))
