"""Console meta routes — status, version, and environment info."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_CONSOLE_VERSION = "1.0.0"
_CONSOLE_STAGES = [
    "admission", "spec", "grill", "dispatch",
    "execute", "verify", "audit", "accept",
]
_CONSOLE_TABS = ["bos", "mof", "harness"]


@router.get("/api/console/meta")
async def api_console_meta():
    """Console 元信息 — 版本、阶段、标签页配置。"""
    try:
        from cockpit.compat import WORKSPACE_ROOT
        from cockpit.console.bos_invoker import known_services
        from cockpit.console.events import event_hub

        services = known_services()
        runs = event_hub.recent_runs()

        return JSONResponse(
            content={
                "version": _CONSOLE_VERSION,
                "harness_stages": _CONSOLE_STAGES,
                "tabs": _CONSOLE_TABS,
                "bos_services_count": len(services),
                "active_runs": len([r for r in runs if r.get("state") in ("running", "pending")]),
                "workspace": str(WORKSPACE_ROOT),
            }
        )
    except Exception as e:
        return JSONResponse(
            content={
                "version": _CONSOLE_VERSION,
                "harness_stages": _CONSOLE_STAGES,
                "tabs": _CONSOLE_TABS,
                "error": str(e),
            },
            status_code=500,
        )
