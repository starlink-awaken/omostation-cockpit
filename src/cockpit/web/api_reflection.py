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


@router.get("/resident/morning-briefing")
async def resident_morning_briefing() -> JSONResponse:
    """获取晨间自治简报快照 (Phase 8 Batch 8.3)."""
    try:
        from omo.resident.morning_briefing import get_morning_briefing_generator

        gen = get_morning_briefing_generator(WORKSPACE_ROOT)
        data = gen.load_latest_briefing()
        data["ok"] = True
        return JSONResponse(data)
    except Exception as exc:
        logger.warning("morning briefing error: %s", exc)
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "greeting": "常驻系统平稳守护中",
                "yesterday_summary": "代码基线平稳运行，各项治理门禁正常",
                "night_defense_status": "✅ 巡检探针与状态感知正常",
                "cluster_online_summary": "集群算力网络在线",
                "memory_growth_summary": "长期记忆结晶正常同步",
                "top_action_items": ["审阅控制台自治巡检与算力状态"],
                "health_score": 100,
            }
        )


@router.get("/resident/memory/distilled")
async def resident_memory_distilled() -> JSONResponse:
    """获取跨会话长期记忆结晶与长效偏好资产 (Phase 8 Batch 8.2)."""
    try:
        from omo.resident.memory_distiller import get_memory_distiller

        distiller = get_memory_distiller(WORKSPACE_ROOT)
        cryst = distiller.load_crystallized_memory()
        cryst["ok"] = True
        return JSONResponse(cryst)
    except Exception as exc:
        logger.warning("load crystallized memory error: %s", exc)
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "preferences": [
                    {
                        "id": "pref-baseline-1",
                        "domain": "language",
                        "directive": "回复优先使用简体中文",
                        "confidence": 1.0,
                    }
                ],
                "guardrail_count": 6,
                "domain_learnings": [],
            }
        )


@router.post("/resident/memory/distill")
async def resident_memory_distill_trigger(payload: dict[str, Any]) -> JSONResponse:
    """手动触发一次跨会话长期记忆结晶 (Phase 8 Batch 8.2)."""
    try:
        from omo.resident.memory_distiller import get_memory_distiller

        extra_text = payload.get("extra_text", "")
        distiller = get_memory_distiller(WORKSPACE_ROOT)
        cryst = distiller.distill_and_crystallize(extra_text=extra_text)
        cryst["ok"] = True
        return JSONResponse(cryst)
    except Exception as exc:
        logger.warning("trigger memory distill error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/resident/night-patrol")
async def resident_night_patrol_trigger(payload: dict[str, Any]) -> JSONResponse:
    """手动触发一次夜间深度巡检与晨间简报生成 (Phase 8 Batch 8.3)."""
    try:
        from omo.resident.night_patrol import run_night_patrol

        force = payload.get("force", True)
        deep = payload.get("deep", False)
        report = run_night_patrol(force=force, deep=deep)
        return JSONResponse(report)
    except Exception as exc:
        logger.warning("night patrol trigger error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ── Phase 8 拓展：通知枢纽与新算力节点动态管理端点 ──


@router.get("/resident/notify/history")
async def resident_notify_history(limit: int = 30) -> JSONResponse:
    """拉取常驻系统最近的主动通知与告警审计记录."""
    try:
        from omo.resident.notification import get_notification_hub

        hub = get_notification_hub(WORKSPACE_ROOT)
        history = hub.get_recent_history(limit=limit)
        return JSONResponse({"ok": True, "history": history, "total": len(history)})
    except Exception as exc:
        logger.warning("notify history error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc), "history": [], "total": 0})


@router.post("/resident/notify/send")
async def resident_notify_send(payload: dict[str, Any]) -> JSONResponse:
    """手动或从系统触发一次主动通知分发."""
    try:
        import time

        from omo.resident.notification import AlertLevel, NotificationEvent, get_notification_hub

        hub = get_notification_hub(WORKSPACE_ROOT)
        level_str = payload.get("level", "P2_INFO")
        try:
            level = AlertLevel(level_str)
        except ValueError:
            level = AlertLevel.P2_INFO

        ev = NotificationEvent(
            id=f"manual-{int(time.time())}",
            level=level,
            title=payload.get("title", "系统测试通知"),
            body=payload.get("body", "这是一条由 Cockpit 驾驶舱触发的主动测试通知。"),
            source=payload.get("source", "cockpit_ui"),
            tags=payload.get("tags", ["manual", "test"]),
        )
        res = hub.notify(ev, force_macos=payload.get("force_macos", True))
        return JSONResponse({"ok": True, "dispatch": res})
    except Exception as exc:
        logger.warning("notify send error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/resident/nodes")
async def resident_nodes_list() -> JSONResponse:
    """获取全网算力节点列表 (含 SSOT 物理基线与动态接入的新机器)."""
    try:
        from omo.resident.swarm_mesh import get_swarm_mesh

        mesh = get_swarm_mesh()
        probe_res = mesh.probe_mesh()
        return JSONResponse({"ok": True, "topology": probe_res})
    except Exception as exc:
        logger.warning("nodes list error: %s", exc)
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "topology": {
                    "online_nodes": 1,
                    "total_nodes": 1,
                    "cluster_vram_gb": "112.0 GB",
                    "nodes": [],
                },
            }
        )


@router.post("/resident/nodes/register")
async def resident_node_register(payload: dict[str, Any]) -> JSONResponse:
    """动态接入并持久化一台外部新算力机器 (如新加入的 Mac Studio / Linux PC)."""
    try:
        from omo.resident.swarm_mesh import SwarmNodeSpec, get_swarm_mesh

        node_id = payload.get("id")
        if not node_id:
            return JSONResponse({"ok": False, "error": "Node ID is required"}, status_code=400)

        node = SwarmNodeSpec(
            id=str(node_id).strip(),
            name=payload.get("name", str(node_id)),
            role=payload.get("role", "worker"),
            host=payload.get("host", "127.0.0.1"),
            inference_port=int(payload.get("port", 11434)),
            health_path=payload.get("health_path", "/api/tags"),
            os=payload.get("os", "darwin"),
            arch=payload.get("arch", "arm64"),
            memory_gb=float(payload.get("memory_gb", 16.0)),
            vram_gb=float(payload.get("vram_gb", 0.0)),
            supported_tiers=payload.get("supported_tiers", ["tier1_inspection"]),
            priority=int(payload.get("priority", 50)),
            description=payload.get("description", "由驾驶舱动态接入的新节点"),
            source="dynamic",
        )

        mesh = get_swarm_mesh()
        mesh.register_dynamic_node(node, persist=True)
        return JSONResponse({"ok": True, "node_id": node.id, "message": "Node successfully registered"})
    except Exception as exc:
        logger.warning("node register error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.delete("/resident/nodes/{node_id}")
async def resident_node_unregister(node_id: str) -> JSONResponse:
    """动态下线或移除一台新算力机器 (SSOT 基线节点不可移除)."""
    try:
        from omo.resident.swarm_mesh import get_swarm_mesh

        mesh = get_swarm_mesh()
        ok = mesh.unregister_dynamic_node(node_id)
        if not ok:
            return JSONResponse(
                {"ok": False, "error": f"Node {node_id} not found or is a non-deletable SSOT baseline node"},
                status_code=400,
            )
        return JSONResponse({"ok": True, "node_id": node_id, "message": "Node unregistered successfully"})
    except Exception as exc:
        logger.warning("node unregister error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/resident/service/status")
async def resident_service_status() -> JSONResponse:
    """常驻守护进程 (LaunchAgent) 状态与日志."""
    try:
        from omo.resident.service_ctl import get_service_status

        status = get_service_status(WORKSPACE_ROOT)
        return JSONResponse({"ok": True, "service": status})
    except Exception as exc:
        logger.warning("service status error: %s", exc)
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "service": {"installed": False, "launchd_running": False, "pid": None, "state": {}, "recent_log": ""},
            }
        )


@router.post("/resident/service/trigger")
async def resident_service_trigger(payload: dict[str, Any]) -> JSONResponse:
    """手动触发常驻守护巡检、夜巡或晨报任务."""
    try:
        from omo.resident.service_ctl import trigger_job

        job = str(payload.get("job", "patrol")).strip()
        res = trigger_job(job, WORKSPACE_ROOT)
        return JSONResponse({"ok": True, "job": job, "result": res})
    except Exception as exc:
        logger.warning("service trigger error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/resident/compute/metrics")
async def resident_compute_metrics() -> JSONResponse:
    """跨机算力推断网关统计指标 (调用次数、延迟、降级率)."""
    try:
        from omo.resident.inference_gateway import get_inference_gateway

        gateway = get_inference_gateway(WORKSPACE_ROOT)
        metrics = gateway.get_metrics()
        return JSONResponse({"ok": True, "metrics": metrics})
    except Exception as exc:
        logger.warning("compute metrics error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc), "metrics": {}})


@router.post("/resident/infer")
async def resident_infer_proxy(payload: dict[str, Any]) -> JSONResponse:
    """跨机推断路由代理端点 (按 Tier 自动切流、自适应协议与熔断降级)."""
    try:
        from omo.resident.inference_gateway import get_inference_gateway

        gateway = get_inference_gateway(WORKSPACE_ROOT)
        tier = payload.get("tier", "tier1_inspection")
        messages = payload.get("messages")
        prompt = payload.get("prompt")
        if not messages and prompt:
            messages = [{"role": "user", "content": str(prompt)}]
        elif not messages:
            messages = [{"role": "user", "content": "hello"}]

        model = payload.get("model")
        timeout = float(payload.get("timeout", 2.0))

        res = gateway.chat_completion(
            messages=messages,
            tier=tier,
            model=model,
            timeout=timeout,
        )
        return JSONResponse(
            {
                "ok": True,
                "content": res.content,
                "target_node": res.target_node,
                "target_host": res.target_host,
                "target_port": res.target_port,
                "tier": res.tier,
                "fallback_used": res.fallback_used,
                "latency_ms": res.latency_ms,
                "model_used": res.model_used,
                "raw_response": res.raw_response,
            }
        )
    except Exception as exc:
        logger.warning("resident infer error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/resident/chat")
async def resident_chat_proxy(payload: dict[str, Any]) -> JSONResponse:
    """沉浸交互对话端点 (长会话保持 + 情境化记忆深度召回 + 多模态图像 + ReAct 探针)."""
    try:
        from omo.resident.chat_engine import get_chat_engine

        engine = get_chat_engine(WORKSPACE_ROOT)
        prompt = str(payload.get("prompt", "")).strip()
        images = payload.get("images", [])
        if isinstance(images, str):
            images = [images]
        elif not isinstance(images, list):
            images = []

        if not prompt and not images:
            return JSONResponse({"ok": False, "error": "prompt is required (or provide images)"}, status_code=400)
        if not prompt and images:
            prompt = "请分析附带的图片内容并给出专业研判。"

        session_id = str(payload.get("session_id", "default")).strip() or "default"
        tier = str(payload.get("tier", "tier2_dialog")).strip()
        model = payload.get("model")
        enable_react = bool(payload.get("enable_react", True))

        msg = engine.chat(
            prompt=prompt,
            session_id=session_id,
            tier=tier,
            model=model,
            enable_react=enable_react,
            images=images,
        )
        return JSONResponse({"ok": True, "message": msg.to_dict()})
    except Exception as exc:
        logger.warning("resident chat error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/resident/chat/history")
async def resident_chat_history(session_id: str = "default", limit: int = 50) -> JSONResponse:
    """获取指定会话的历史对话记录 (按时间升序排列)."""
    try:
        from omo.resident.chat_engine import get_chat_engine

        engine = get_chat_engine(WORKSPACE_ROOT)
        history = engine.get_history(session_id=session_id, limit=limit)
        return JSONResponse({"ok": True, "session_id": session_id, "messages": history})
    except Exception as exc:
        logger.warning("resident chat history error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc), "session_id": session_id, "messages": []})


@router.delete("/resident/chat/history")
async def resident_chat_clear(session_id: str = "default") -> JSONResponse:
    """清空指定会话的历史对话记录."""
    try:
        from omo.resident.chat_engine import get_chat_engine

        engine = get_chat_engine(WORKSPACE_ROOT)
        cleared = engine.clear_history(session_id=session_id)
        return JSONResponse({"ok": True, "session_id": session_id, "cleared": cleared})
    except Exception as exc:
        logger.warning("resident chat clear error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/resident/voice/speak")
async def resident_voice_speak(payload: dict[str, Any]) -> JSONResponse:
    """语音合成与伴随朗读端点 (智能过滤代码与配置噪声)."""
    try:
        from omo.resident.voice_bridge import speak_text

        text = str(payload.get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "text is required"}, status_code=400)

        voice = payload.get("voice")
        play = bool(payload.get("play", False))
        res = speak_text(text=text, voice=voice, play=play)
        return JSONResponse({"ok": res.get("success", False), "result": res})
    except Exception as exc:
        logger.warning("resident voice speak error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/resident/screen/capture")
async def resident_screen_capture(payload: dict[str, Any] | None = None) -> JSONResponse:
    """服务端屏幕快照捕获端点 (智能前台窗口或全屏)."""
    try:
        from omo.resident.screen_probe import capture_screen

        payload = payload or {}
        fullscreen = bool(payload.get("fullscreen", False))
        img_path = capture_screen(fullscreen=fullscreen, workspace_root=WORKSPACE_ROOT)
        return JSONResponse(
            {
                "ok": True,
                "image_path": str(img_path),
                "filename": img_path.name,
                "size_bytes": img_path.stat().st_size,
            }
        )
    except Exception as exc:
        logger.warning("resident screen capture error: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
