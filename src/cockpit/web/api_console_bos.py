"""Console BOS routes — POST /api/bos/invoke + GET /schema + /catalog + /history."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from cockpit.console.bos_invoker import BosInvoker, aggregate_metrics
from cockpit.console.models import InvokeRequest
from cockpit.console.risk import classify_risk, require_confirm

router = APIRouter(tags=["console-bos"])
_invoker = BosInvoker()


def _envelope(ok: bool, data: Any = None, error_code: str | None = None, error: str | None = None) -> dict:
    return {"ok": ok, "error_code": error_code, "error": error, "data": data}


@router.post("/api/bos/invoke")
async def api_bos_invoke(
    request: Request,
    x_console_confirm: str | None = Header(default=None, alias="X-Console-Confirm"),
):
    """Invoke a BOS URI via Agora with in-process fallback."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_envelope(False, error_code="MISSING_FIELD", error="Request body must be JSON"), status_code=400)

    uri = body.get("uri", "")
    arguments = body.get("arguments", {})
    timeout_ms = body.get("timeout_ms", 30_000)

    if not uri:
        return JSONResponse(_envelope(False, error_code="MISSING_FIELD", error="uri is required"), status_code=400)
    if not uri.startswith("bos://"):
        return JSONResponse(_envelope(False, error_code="INVALID_URI", error="URI must start with bos://"), status_code=400)

    # Risk classification and confirmation check
    risk = classify_risk(uri)
    body_bytes = json.dumps({"uri": uri, "arguments": arguments, "timeout_ms": timeout_ms}, sort_keys=True).encode()
    rejection = require_confirm(risk, uri, body_bytes, x_console_confirm)
    if rejection:
        status = 400 if rejection == "RISK_CONFIRM_REQUIRED" else 403
        return JSONResponse(
            _envelope(False, error_code=rejection, error=f"Risk level {risk.value} requires X-Console-Confirm"),
            status_code=status,
        )

    req = InvokeRequest(uri=uri, arguments=arguments, timeout_ms=timeout_ms)
    result = await _invoker.invoke(req)

    if result.error:
        return JSONResponse(_envelope(False, error_code=result.error, error=result.error, data=result.__dict__), status_code=502)

    return JSONResponse(_envelope(True, data=result.__dict__))


@router.get("/api/bos/invoke/schema")
async def api_bos_schema(uri: str = ""):
    """Get parameter schema for a BOS URI."""
    if not uri:
        return JSONResponse(_envelope(False, error_code="MISSING_FIELD", error="uri query param required"), status_code=400)
    schema = _invoker.schema_for(uri)
    return JSONResponse(_envelope(True, data=schema))


@router.get("/api/bos/catalog")
async def api_bos_catalog(domain: str = "", query: str = ""):
    """Browse BOS service catalog."""
    services = _invoker.known_services(domain=domain, query=query)
    return JSONResponse(_envelope(True, data={"total": len(services), "services": services}))


@router.get("/api/bos/history")
async def api_bos_history(prefix: str = "", limit: int = 50):
    """Get recent BOS call history from metrics file."""
    metrics = aggregate_metrics(prefix=prefix)
    return JSONResponse(_envelope(True, data=metrics))
