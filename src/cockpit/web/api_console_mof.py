"""Console MOF routes — POST /api/mof/audit + /evaluate + GET /rules + /dimensions + /value-loop."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from cockpit.console.mof_auditor import MofAuditor, value_loop_overview

router = APIRouter(tags=["console-mof"])
_auditor = MofAuditor()


def _envelope(ok: bool, data: Any = None, error_code: str | None = None, error: str | None = None) -> dict:
    return {"ok": ok, "error_code": error_code, "error": error, "data": data}


@router.post("/api/mof/audit")
async def api_mof_audit(request: Request):
    """Run full MOF audit via subprocess (wrapped in asyncio.to_thread)."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    family = body.get("family")
    max_rules = body.get("max_rules", 500)

    # Run in thread pool to avoid blocking the event loop
    result = await asyncio.to_thread(_auditor.full_audit, family, max_rules)

    if not result.get("ok"):
        status = 503 if result.get("degraded") else 500
        return JSONResponse(_envelope(False, error_code=result.get("error_code"), error=result.get("error")), status_code=status)

    return JSONResponse(_envelope(True, data=result))


@router.post("/api/mof/evaluate")
async def api_mof_evaluate(request: Request):
    """Evaluate a single MOF constraint in-process."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_envelope(False, error_code="MISSING_FIELD", error="Request body must be JSON"), status_code=400)

    constraint_id = body.get("constraint_id", "")
    target = body.get("target", "")
    target_kind = body.get("target_kind", "")
    caller_layer = body.get("caller_layer", "L3")
    caller_domain = body.get("caller_domain", "default")

    if not constraint_id:
        return JSONResponse(_envelope(False, error_code="MISSING_FIELD", error="constraint_id is required"), status_code=400)
    if not target:
        return JSONResponse(_envelope(False, error_code="MISSING_FIELD", error="target is required"), status_code=400)
    if target_kind not in ("python_code", "write", "command"):
        return JSONResponse(_envelope(False, error_code="INVALID_FIELD", error="target_kind must be python_code, write, or command"), status_code=400)

    result = _auditor.evaluate(
        constraint_id=constraint_id,
        target=target,
        target_kind=target_kind,
        caller_layer=caller_layer,
        caller_domain=caller_domain,
    )

    if not result.get("ok"):
        status = 503 if result.get("degraded") else 400
        return JSONResponse(_envelope(False, error_code=result.get("error_code"), error=result.get("error")), status_code=status)

    return JSONResponse(_envelope(True, data=result))


@router.get("/api/mof/rules")
async def api_mof_rules():
    """Get MOF rule catalog grouped by family."""
    result = _auditor.rule_catalog()
    if not result.get("ok"):
        return JSONResponse(_envelope(False, error_code=result.get("error_code"), error="MOF unavailable"), status_code=503)
    return JSONResponse(_envelope(True, data=result))


@router.get("/api/mof/dimensions")
async def api_mof_dimensions():
    """Get 12-dimension system targets."""
    result = value_loop_overview()
    return JSONResponse(_envelope(True, data={"dimensions": result.get("dimensions", [])}))


@router.get("/api/mof/value-loop")
async def api_mof_value_loop():
    """Get value loop overview (5 stages + north star + broken chains)."""
    result = value_loop_overview()
    return JSONResponse(_envelope(True, data=result))
