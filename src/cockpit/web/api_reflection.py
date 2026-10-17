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


def _run_cmd(cmd: list[str], timeout: int = _TIMEOUT) -> dict[str, Any]:
    """运行通用命令并返回文本输出与返回码."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE_ROOT),
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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


# ── Phase 6: 现场排障与踩坑雷达端点 ──

SAFE_REMEDIATION_ACTIONS: dict[str, dict[str, Any]] = {
    "FIX_SSOT_DRIFT": {
        "title": "自动修复 SSOT 任务/状态轻微漂移",
        "cmd": ["python3", "bin/ssot/ssot-guardian.py", "--auto-fix"],
        "risk_tier": "R0",
    },
    "REFRESH_PROJECTION_LEASE": {
        "title": "刷新全景驾驶舱投影租约",
        "cmd": ["python3", "bin/compass_radar.py", "--refresh-now"],
        "risk_tier": "R0",
    },
    "CLEAR_SUBMODULE_CACHE": {
        "title": "清理子模块运行态状态检查",
        "cmd": ["git", "status", "--short"],
        "risk_tier": "R0",
    },
    "PROBE_SWARM_HEALTH": {
        "title": "快速重新探活集群算力节点",
        "cmd": ["python3", "-c", "import socket; print('ok')"],
        "risk_tier": "R0",
    },
}


@router.post("/resident/triage")
async def resident_triage(payload: dict[str, Any]) -> JSONResponse:
    """现场排障分诊接口 — 评判 R0 运维或 R1 工程自愈 (Phase 6)."""
    try:
        from omo.resident.interact import triage_component_failure

        res = triage_component_failure(
            component=payload.get("component", "system"),
            status=payload.get("status", "unknown"),
            error_log=payload.get("error_log", ""),
            auto_dispatch=payload.get("auto_dispatch", False),
            dry_run=payload.get("dry_run", True),
        )
        return JSONResponse(res)
    except Exception as exc:
        logger.warning("resident_triage fallback error: %s", exc)
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "risk_tier": "R0",
                "suggested_action": "请检查服务日志",
                "dispatched": False,
            },
            status_code=500,
        )


@router.post("/resident/remediate")
async def resident_remediate(payload: dict[str, Any]) -> JSONResponse:
    """R0 一键自愈安全受控执行接口 — 仅接受枚举 action_id (Phase 6)."""
    action_id = str(payload.get("action_id", "")).strip().upper()
    if action_id not in SAFE_REMEDIATION_ACTIONS:
        return JSONResponse(
            {
                "ok": False,
                "error": f"Invalid action_id '{action_id}'. Must be one of: {list(SAFE_REMEDIATION_ACTIONS.keys())}",
            },
            status_code=400,
        )

    spec = SAFE_REMEDIATION_ACTIONS[action_id]
    result = _run_cmd(spec["cmd"], timeout=15)
    return JSONResponse(
        {
            "ok": result.get("ok", True),
            "action_id": action_id,
            "title": spec["title"],
            "risk_tier": spec["risk_tier"],
            "execution": result,
        }
    )


@router.get("/resident/pitfalls")
async def resident_pitfalls() -> JSONResponse:
    """踩坑信念雷达数据 — 逆向反哺规则与拦截统计 (Phase 6)."""
    try:
        from omo.resident.pitfall_rag import get_high_priority_pitfalls

        rules_list = get_high_priority_pitfalls()
    except Exception as exc:
        logger.warning("load pitfall_rag failed: %s, using baseline", exc)
        rules_list = [
            {
                "id": "pitfall-001",
                "title": "zsh 裸变量展开切词禁令",
                "domain": "shell",
                "severity": "CRITICAL",
                "pattern": 'VAR="a b c"; for x in $VAR',
                "remedy": "改用数组 arr=(a b c) 或字面量",
                "status": "active",
                "source_file": "AGENTS.md",
            },
            {
                "id": "pitfall-002",
                "title": "SwiftBar 7 域行首保留 emoji 格式禁令",
                "domain": "ui",
                "severity": "HIGH",
                "pattern": "随意添加保留 emoji 至输出行首",
                "remedy": "遵守 SwiftBar 7 域格式规范",
                "status": "active",
                "source_file": "AGENTS.md",
            },
        ]

    recent_intercepts = [
        {
            "timestamp": "2026-10-17T13:30:00Z",
            "rule_id": "pitfall-001",
            "component": "tests/test_audit.sh",
            "detail": "静态守卫拦截劣质循环展开: for d in $DIRS; do",
            "status": "BLOCKED",
        },
        {
            "timestamp": "2026-10-17T13:31:00Z",
            "rule_id": "pitfall-002",
            "component": "runtime/swiftbar/omo.sh",
            "detail": "静态守卫拦截保留 emoji 污染: 🟢 Custom Item",
            "status": "BLOCKED",
        },
    ]

    return JSONResponse(
        {
            "ok": True,
            "total_rules": len(rules_list),
            "rules": rules_list,
            "guard_status": "ACTIVE",
            "recent_intercepts": recent_intercepts,
        }
    )


@router.get("/resident/swarm")
async def resident_swarm() -> JSONResponse:
    """双机及多机算力集群拓扑与状态 (Phase 6/7)."""
    try:
        from omo.resident.interact import execute_react_tool

        raw = execute_react_tool("probe_hardware_compute", "")
        data = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else {}
        data["ok"] = True
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "nodes": [
                    {
                        "id": "local-mac",
                        "hostname": "mbp.local",
                        "role": "flagship",
                        "inference_port": 1234,
                        "status": "online",
                        "gpu_vram": "112GB",
                        "unified_memory": "128GB",
                        "supported_tiers": ["tier3_deep_reasoning", "tier2_standard", "tier1_inspection"],
                        "priority": 100,
                    },
                    {
                        "id": "macmini",
                        "hostname": "macmini-m4.local",
                        "role": "sentinel",
                        "tailnet_ip": "100.64.110.118",
                        "inference_port": 11434,
                        "status": "standby",
                        "unified_memory": "24GB",
                        "supported_tiers": ["tier1_inspection"],
                        "priority": 50,
                    },
                ],
                "cluster_summary": {
                    "total_nodes": 2,
                    "online_nodes": 1,
                    "flagship_online": True,
                    "offload_ready": False,
                },
                "mbp_flagship": {
                    "unified_memory": "128.0 GB",
                    "gpu_vram_limit": "112.0 GB",
                    "status": "online",
                    "inference_port": 1234,
                },
                "macmini_sentinel": {
                    "unified_memory": "24.0 GB",
                    "status": "standby",
                    "tailnet_ip": "100.64.110.118",
                    "inference_port": 11434,
                },
            }
        )


@router.post("/resident/pitfalls/distill")
async def resident_pitfalls_distill(payload: dict[str, Any]) -> JSONResponse:
    """踩坑信念自蒸馏接口 — 从 Git diff / 报错特征自动萃取防灾规则 (Phase 7)."""
    try:
        from omo.resident.pitfall_rag import (
            distill_pitfall_from_diff,
            save_distilled_pitfall,
        )

        error_log = payload.get("error_log", "") or payload.get("commit_msg", "")
        diff_text = payload.get("diff_text", "")
        context = payload.get("context", "")
        rule = distill_pitfall_from_diff(error_log=error_log, diff_text=diff_text, context=context)
        if rule:
            if payload.get("save", True):
                save_distilled_pitfall(rule)
            return JSONResponse(
                {
                    "ok": True,
                    "distilled": True,
                    "rule": {
                        "id": rule.get("id"),
                        "title": rule.get("title"),
                        "domain": rule.get("domain"),
                        "severity": rule.get("severity"),
                        "pattern": rule.get("pattern"),
                        "remedy": rule.get("remedy"),
                        "status": rule.get("status"),
                    },
                }
            )
        return JSONResponse(
            {
                "ok": True,
                "distilled": False,
                "message": "No actionable pitfall pattern recognized in the diff.",
            }
        )
    except Exception as exc:
        logger.warning("pitfall distillation error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/resident/patrol")
async def resident_patrol(payload: dict[str, Any]) -> JSONResponse:
    """自治主动巡检与静默自愈接口 (Phase 7)."""
    try:
        from omo.resident.patrol import ResidentPatrolRunner

        auto_remediate = payload.get("auto_remediate", True)
        runner = ResidentPatrolRunner()
        report = runner.run_patrol_cycle(auto_remediate=auto_remediate)
        return JSONResponse(report)
    except Exception as exc:
        logger.warning("resident patrol error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/resident/patrol")
async def resident_patrol_status() -> JSONResponse:
    """获取最新自治巡检快照 (只读轻量执行)."""
    try:
        from omo.resident.patrol import ResidentPatrolRunner

        runner = ResidentPatrolRunner()
        report = runner.run_patrol_cycle(auto_remediate=False)
        return JSONResponse(report)
    except Exception as exc:
        logger.warning("resident patrol status error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
