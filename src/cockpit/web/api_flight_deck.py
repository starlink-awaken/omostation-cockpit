"""Resident Flight Deck API — L1-L4 授权网关 + 四维透明指挥舱端点.

BET-Y1Q4-T8-23:
  GET  /api/flight-deck/snapshot   — 全景快照 (心跳/DAG/算力/决策)
  POST /api/flight-deck/authorize  — 单次授权判定
  POST /api/flight-deck/circuit/trip   — 紧急熔断
  POST /api/flight-deck/circuit/reset  — 复位熔断器
  GET  /api/flight-deck/circuit/status — 熔断器状态
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cockpit.resident_flight_deck import (
    AuthorizationDecision,
    ComputeTelemetry,
    FlightDeckSnapshot,
    TaskDAGNode,
    authorize,
    get_circuit_breaker,
    get_heartbeat_monitor,
)

router = APIRouter(prefix="/api/flight-deck", tags=["flight-deck"])


# ── 内存中的最近决策环形缓冲 (上限 50 条) ──
_recent_decisions: list[AuthorizationDecision] = []
_MAX_DECISIONS = 50


def _record_decision(decision: AuthorizationDecision) -> None:
    """记录一次决策到环形缓冲."""
    _recent_decisions.append(decision)
    if len(_recent_decisions) > _MAX_DECISIONS:
        _recent_decisions.pop(0)


# ── 授权端点 ──

@router.post("/authorize")
async def flight_deck_authorize(payload: dict[str, Any]) -> dict[str, Any]:
    """执行一次风险-置信度授权判定.

    Request body:
      { "action": "git_commit", "confidence": 0.95, "extra_risk": 0.0 }
    """
    action = payload.get("action", "")
    confidence = float(payload.get("confidence", 0.0))
    extra_risk = float(payload.get("extra_risk", 0.0))

    if not action:
        return {"ok": False, "error": "action is required"}

    breaker = get_circuit_breaker()
    decision = breaker.check(action, confidence)
    # 如果熔断器未触发, 用 extra_risk 重新判定
    if not breaker.is_tripped:
        decision = authorize(action, confidence, extra_risk=extra_risk)

    _record_decision(decision)
    return {"ok": True, "decision": decision.to_dict()}


# ── 熔断器控制 ──

@router.post("/circuit/trip")
async def circuit_trip() -> dict[str, Any]:
    """紧急熔断 — 阻断一切后续写操作."""
    breaker = get_circuit_breaker()
    breaker.trip()
    return {"ok": True, "tripped": True, "tripped_at": breaker._tripped_at}


@router.post("/circuit/reset")
async def circuit_reset() -> dict[str, Any]:
    """复位熔断器 — 恢复正常授权流程."""
    breaker = get_circuit_breaker()
    breaker.reset()
    return {"ok": True, "tripped": False}


@router.get("/circuit/status")
async def circuit_status() -> dict[str, Any]:
    """查询熔断器当前状态."""
    breaker = get_circuit_breaker()
    return {
        "tripped": breaker.is_tripped,
        "tripped_at": breaker._tripped_at,
    }


# ── 心跳上报 ──

@router.post("/heartbeat")
async def flight_deck_heartbeat(payload: dict[str, Any]) -> dict[str, Any]:
    """Agent 心跳上报 — 驱动真实存活判定.

    Request body:
      { "agent_id": "governance-agent", "latency_ms": 12.5 }
    """
    agent_id = payload.get("agent_id", "")
    if not agent_id:
        return {"ok": False, "error": "agent_id is required"}
    try:
        latency_ms = float(payload.get("latency_ms", 0.0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "latency_ms must be a number"}
    monitor = get_heartbeat_monitor()
    status = monitor.beat(agent_id, latency_ms)
    return {"ok": True, "status": status.to_dict(), "degraded": monitor.degraded}


# ── 全景快照 ──

@router.get("/snapshot")
async def flight_deck_snapshot() -> dict[str, Any]:
    """Flight Deck 全景快照 — 四维透明数据聚合 (心跳来自真实监视器)."""
    breaker = get_circuit_breaker()
    monitor = get_heartbeat_monitor()

    # 心跳 — 真实监视器状态 (无上报时为空,不再填充示例数据)
    heartbeats = monitor.statuses()

    # 任务 DAG (示例 — 后续接真实任务队列)
    task_dag = [
        TaskDAGNode(task_id="t1", label="信号感知", status="done"),
        TaskDAGNode(task_id="t2", label="信号分类", status="done"),
        TaskDAGNode(task_id="t3", label="旅程执行", status="running", parent_ids=["t1", "t2"]),
        TaskDAGNode(task_id="t4", label="价值记录", status="pending", parent_ids=["t3"]),
    ]

    # 算力遥测 (示例 — 后续接 omlxc/真实 GPU 数据)
    compute = [
        ComputeTelemetry(
            device="mps",
            gpu_utilization=0.15,
            vram_used_mb=2048.0,
            vram_total_mb=16384.0,
            temperature_c=45.0,
        ),
    ]

    snapshot = FlightDeckSnapshot(
        heartbeats=heartbeats,
        task_dag=task_dag,
        compute=compute,
        recent_decisions=list(_recent_decisions),
    )

    return {
        "ok": True,
        "circuit_tripped": breaker.is_tripped,
        "degraded": monitor.degraded,
        "snapshot": snapshot.to_dict(),
    }
