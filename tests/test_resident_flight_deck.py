"""Resident Flight Deck 单元测试 — BET-Y1Q4-T8-23 收尾.

覆盖: L1~L4 风险-置信度授权矩阵边界、黑名单 100% 拦截、
紧急熔断 (<1s 生效)、真实心跳监视器 (存活判定/连续超时降级)、
算力遥测与全景快照序列化. 仅依赖标准库 + cockpit.resident_flight_deck.
"""

from __future__ import annotations

import time

import pytest

from cockpit.resident_flight_deck import (
    BLACKLISTED_ACTIONS,
    HEARTBEAT_MAX_MISSES,
    AuthorizationDecision,
    CircuitBreaker,
    ComputeTelemetry,
    ConfidenceBand,
    FlightDeckSnapshot,
    HeartbeatMonitor,
    HeartbeatStatus,
    RiskTier,
    TaskDAGNode,
    authorize,
    classify_confidence,
    get_circuit_breaker,
    get_heartbeat_monitor,
    reset_heartbeat_monitor,
)

# ── 置信度分档边界 ──

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, ConfidenceBand.HIGH),
        (0.9, ConfidenceBand.HIGH),
        (0.8999, ConfidenceBand.MEDIUM),
        (0.7, ConfidenceBand.MEDIUM),
        (0.6999, ConfidenceBand.LOW),
        (0.5, ConfidenceBand.LOW),
        (0.4999, ConfidenceBand.CRITICAL),
        (0.0, ConfidenceBand.CRITICAL),
    ],
)
def test_classify_confidence_boundaries(value: float, expected: ConfidenceBand) -> None:
    assert classify_confidence(value) is expected


# ── L1~L4 授权矩阵 ──

def test_authorize_l1_routine_auto_execute() -> None:
    d = authorize("git_commit", 0.95)
    assert d.risk_tier is RiskTier.L1_ROUTINE
    assert d.allowed is True
    assert d.requires_human_approval is False


def test_authorize_l2_assisted_post_review() -> None:
    d = authorize("file_write", 0.8)
    assert d.risk_tier is RiskTier.L2_ASSISTED
    assert d.allowed is True
    assert d.requires_human_approval is False


def test_authorize_l3_supervised_requires_approval() -> None:
    d = authorize("shell_exec", 0.6)
    assert d.risk_tier is RiskTier.L3_SUPERVISED
    assert d.allowed is False
    assert d.requires_human_approval is True


def test_authorize_l4_blocked_low_confidence() -> None:
    d = authorize("shell_exec", 0.2)
    assert d.risk_tier is RiskTier.L4_BLOCKED
    assert d.allowed is False
    assert d.requires_human_approval is True


def test_authorize_extra_risk_escalates_tier() -> None:
    d = authorize("file_write", 0.95, extra_risk=0.2)
    assert d.risk_tier is RiskTier.L2_ASSISTED
    assert d.confidence == pytest.approx(0.75)
    d2 = authorize("file_write", 0.95, extra_risk=0.3)
    assert d2.risk_tier is RiskTier.L3_SUPERVISED
    assert d2.confidence == pytest.approx(0.65)


def test_authorize_extra_risk_clamped() -> None:
    d = authorize("file_write", 0.1, extra_risk=0.9)
    assert d.risk_tier is RiskTier.L4_BLOCKED
    assert d.confidence == pytest.approx(0.0)


def test_blacklist_blocks_every_action_at_any_confidence() -> None:
    assert len(BLACKLISTED_ACTIONS) > 0
    for action in BLACKLISTED_ACTIONS:
        for confidence in (0.0, 0.5, 0.99, 1.0):
            d = authorize(action, confidence)
            assert d.risk_tier is RiskTier.L4_BLOCKED, action
            assert d.allowed is False, action
            assert d.requires_human_approval is True, action


def test_decision_to_dict_round_trip() -> None:
    d = authorize("git_commit", 0.95)
    payload = d.to_dict()
    assert payload["action"] == "git_commit"
    assert payload["risk_tier"] == 1
    assert payload["risk_tier_label"] == "L1_ROUTINE"
    assert payload["band"] == "high"
    assert payload["allowed"] is True
    assert isinstance(payload["timestamp"], float)


# ── 紧急熔断器 ──

def test_circuit_breaker_trip_blocks_all_writes() -> None:
    breaker = CircuitBreaker()
    assert breaker.is_tripped is False
    started = time.time()
    breaker.trip()
    elapsed = time.time() - started
    assert elapsed < 1.0, "紧急人工熔断必须在 1 秒内生效"
    assert breaker.is_tripped is True
    d = breaker.check("git_commit", 1.0)
    assert d.allowed is False
    assert d.risk_tier is RiskTier.L4_BLOCKED


def test_circuit_breaker_reset_restores_flow() -> None:
    breaker = CircuitBreaker()
    breaker.trip()
    breaker.reset()
    assert breaker.is_tripped is False
    d = breaker.check("git_commit", 0.95)
    assert d.allowed is True
    assert isinstance(d, AuthorizationDecision)


def test_global_breaker_singleton() -> None:
    assert get_circuit_breaker() is get_circuit_breaker()


# ── 真实心跳监视器 ──

def test_monitor_beat_marks_alive() -> None:
    monitor = HeartbeatMonitor()
    status = monitor.beat("agent-a", 12.5, now=1000.0)
    assert isinstance(status, HeartbeatStatus)
    assert status.agent_id == "agent-a"
    assert status.alive is True
    assert monitor.is_alive("agent-a", now=1005.0) is True


def test_monitor_unknown_agent_not_alive() -> None:
    monitor = HeartbeatMonitor()
    assert monitor.is_alive("ghost", now=1000.0) is False
    assert monitor.consecutive_misses("ghost") == 0


def test_monitor_stale_beat_not_alive() -> None:
    monitor = HeartbeatMonitor(stale_after_s=30.0)
    monitor.beat("agent-a", now=1000.0)
    assert monitor.is_alive("agent-a", now=1029.9) is True
    assert monitor.is_alive("agent-a", now=1030.1) is False
    statuses = monitor.statuses(now=1031.0)
    assert statuses[0].alive is False


def test_monitor_miss_counts_and_degrades() -> None:
    monitor = HeartbeatMonitor()
    monitor.beat("agent-a", now=1000.0)
    assert monitor.degraded is False
    for _ in range(HEARTBEAT_MAX_MISSES):
        monitor.miss("agent-a", now=1100.0)
    assert monitor.consecutive_misses("agent-a") == HEARTBEAT_MAX_MISSES
    assert monitor.degraded is True


def test_monitor_beat_clears_degrade() -> None:
    monitor = HeartbeatMonitor()
    monitor.beat("agent-a", now=1000.0)
    for _ in range(HEARTBEAT_MAX_MISSES):
        monitor.miss("agent-a", now=1100.0)
    assert monitor.degraded is True
    monitor.beat("agent-a", now=1200.0)
    assert monitor.consecutive_misses("agent-a") == 0
    assert monitor.degraded is False
    assert monitor.is_alive("agent-a", now=1201.0) is True


def test_global_monitor_singleton_and_reset() -> None:
    first = get_heartbeat_monitor()
    first.beat("agent-a", now=1000.0)
    assert get_heartbeat_monitor() is first
    fresh = reset_heartbeat_monitor()
    assert fresh is not first
    assert get_heartbeat_monitor() is fresh
    assert fresh.is_alive("agent-a", now=1001.0) is False
    # 恢复干净全局状态,避免污染其他测试
    reset_heartbeat_monitor()


# ── 算力遥测 ──

def test_compute_telemetry_vram_pct() -> None:
    tel = ComputeTelemetry(
        device="mps",
        gpu_utilization=0.15,
        vram_used_mb=2048.0,
        vram_total_mb=16384.0,
        temperature_c=45.0,
    )
    assert tel.vram_usage_pct == pytest.approx(0.125)
    payload = tel.to_dict()
    assert payload["vram_usage_pct"] == pytest.approx(0.125)
    assert payload["device"] == "mps"


def test_compute_telemetry_zero_total_guarded() -> None:
    tel = ComputeTelemetry(
        device="cpu",
        gpu_utilization=0.0,
        vram_used_mb=0.0,
        vram_total_mb=0.0,
        temperature_c=40.0,
    )
    assert tel.vram_usage_pct == 0.0


# ── 全景快照 ──

def test_flight_deck_snapshot_serialization() -> None:
    monitor = HeartbeatMonitor()
    monitor.beat("agent-a", 5.0, now=1000.0)
    snapshot = FlightDeckSnapshot(
        heartbeats=monitor.statuses(now=1001.0),
        task_dag=[TaskDAGNode(task_id="t1", label="信号感知", status="done")],
        compute=[
            ComputeTelemetry(
                device="mps",
                gpu_utilization=0.1,
                vram_used_mb=1024.0,
                vram_total_mb=8192.0,
                temperature_c=44.0,
            )
        ],
        recent_decisions=[authorize("git_commit", 0.95)],
    )
    payload = snapshot.to_dict()
    assert set(payload) == {"heartbeats", "task_dag", "compute", "recent_decisions"}
    assert payload["heartbeats"][0]["agent_id"] == "agent-a"
    assert payload["heartbeats"][0]["alive"] is True
    assert payload["task_dag"][0]["status"] == "done"
    assert payload["recent_decisions"][0]["allowed"] is True
