"""Reflection API — 聚合运行时反射数据给 cockpit-ui.

提供:
  GET /api/resident     — 常驻 Agent 状态
  GET /api/bcos         — BCOS 北极星/信号/进化
  GET /api/p74          — P74 工作流沉默治理
  GET /api/decisions    — 决策提案待办卡片 (BET-Y1Q4-T8-21)
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from cockpit.compat import WORKSPACE_ROOT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reflection"])

_TIMEOUT = 30


def _run_json(cmd: list[str], timeout: int = _TIMEOUT) -> dict[str, Any]:
    """运行命令并解析 JSON 输出。统一契约: 成功含 ok=True, 失败含 ok=False (+available:false)。

    此前成功分支透传子命令 JSON (无 ok 键), 失败分支用 {available:false} 结构 —
    两个分支契约不一致导致 p74 测试在本地/CI 环境差异下此消彼长 (2026-09-24 实证)。
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE_ROOT),
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, dict) and "ok" not in data:
                data["ok"] = True
            return data
        return {"ok": False, "available": False, "error": f"exit={result.returncode}", "stderr": result.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "available": False, "error": "timeout"}
    except json.JSONDecodeError as exc:
        return {"ok": False, "available": False, "error": f"json_decode: {exc}"}
    except Exception as exc:
        return {"ok": False, "available": False, "error": str(exc)}


@router.get("/resident")
async def resident_status() -> JSONResponse:
    """常驻 Agent 状态."""
    data = _run_json(["uv", "run", "python", "bin/omo", "resident", "status", "--json"])
    return JSONResponse(data)


@router.get("/bcos")
async def bcos_status() -> JSONResponse:
    """BCOS 北极星/信号/进化."""
    data = _run_json(["uv", "run", "python", "bin/bc-os/north_star_meter_v2.py", "--json"])
    return JSONResponse(data)


@router.get("/p74")
async def p74_status() -> JSONResponse:
    """P74 工作流沉默治理."""
    data = _run_json(["uv", "run", "python", "bin/agent-workflow.py", "compliance", "--json"])
    return JSONResponse(data)


@router.get("/decisions")
async def decision_proposals() -> JSONResponse:
    """决策提案待办卡片 — 返回未处理提案摘要 (BET-Y1Q4-T8-21)."""
    from cockpit.commands.resident_decision import _scan_proposals

    proposals = _scan_proposals()
    unreviewed = [p for p in proposals if p["status"] not in ("reviewed", "promoted", "dismissed")]
    summary = {
        "total": len(proposals),
        "unreviewed": len(unreviewed),
        "reviewed": len(proposals) - len(unreviewed),
        "top_unreviewed": unreviewed[:5],
    }
    return JSONResponse(summary)
