"""Tests for Resident Flight Deck — L1-L4 风险-置信度自适应授权网关.

BET-Y1Q4-T8-23: 覆盖四阶梯授权判定、黑名单阻断、熔断器、遥测序列化.
"""

from __future__ import annotations

import pytest

from cockpit.resident_flight_deck import (
    BLACKLISTED_ACTIONS,
    AuthorizationDecision,
    CircuitBreaker,
    ConfidenceBand,
    ComputeTelemetry,
    HeartbeatStatus,
    RiskTier,
    TaskDAGNode,
    authorize,
    classify_confidence,
)


# ── 置信度分档 ──

class TestConfidenceBand:
    def test_high(self):
        assert classify_confidence(0.95) == ConfidenceBand.HIGH

    def test_medium(self):
        assert classify_confidence(0.75) == ConfidenceBand.MEDIUM

    def test_low(self):
        assert classify_confidence(0.55) == ConfidenceBand.LOW

    def test_critical(self):
        assert classify_confidence(0.3) == ConfidenceBand.CRITICAL

    def test_boundary_l1_l2(self):
        assert classify_confidence(0.9) == ConfidenceBand.HIGH

    def test_boundary_l2_l3(self):
        assert classify_confidence(0.7) == ConfidenceBand.MEDIUM

    def test_boundary_l3_l4(self):
        assert classify_confidence(0.5) == ConfidenceBand.LOW


# ── 授权判定核心 ──

class TestAuthorize:
    def test_l1_routine_auto_execute(self):
        d = authorize("read_file", 0.95)
        assert d.allowed is True
        assert d.risk_tier == RiskTier.L1_ROUTINE
        assert d.requires_human_approval is False

    def test_l2_assisted_execute_with_review(self):
        d = authorize("write_file", 0.8)
        assert d.allowed is True
        assert d.risk_tier == RiskTier.L2_ASSISTED
        assert d.requires_human_approval is False

    def test_l3_supervised_requires_approval(self):
        d = authorize("refactor_code", 0.6)
        assert d.allowed is False
        assert d.risk_tier == RiskTier.L3_SUPERVISED
        assert d.requires_human_approval is True

    def test_l4_blocked(self):
        d = authorize("deploy_staging", 0.3)
        assert d.allowed is False
        assert d.risk_tier == RiskTier.L4_BLOCKED
        assert d.requires_human_approval is True

    def test_blacklist_always_blocked(self):
        for action in BLACKLISTED_ACTIONS:
            d = authorize(action, 0.99)
            assert d.allowed is False, f"Blacklisted action {action} should be blocked"
            assert d.risk_tier == RiskTier.L4_BLOCKED

    def test_extra_risk_downgrade(self):
        d = authorize("write_file", 0.95, extra_risk=0.3)
        # 0.95 - 0.3 = 0.65 → L3
        assert d.risk_tier == RiskTier.L3_SUPERVISED
        assert d.allowed is False

    def test_extra_risk_clamped_to_zero(self):
        d = authorize("read_file", 0.5, extra_risk=1.0)
        # 0.5 - 1.0 = clamped to 0.0 → L4
        assert d.risk_tier == RiskTier.L4_BLOCKED

    def test_decision_to_dict(self):
        d = authorize("test_action", 0.95)
        result = d.to_dict()
        assert result["action"] == "test_action"
        assert result["allowed"] is True
        assert result["risk_tier"] == 1
        assert "risk_tier_label" in result
        assert result["band"] == "high"


# ── 熔断器 ──

class TestCircuitBreaker:
    def test_init_not_tripped(self):
        cb = CircuitBreaker()
        assert cb.is_tripped is False

    def test_trip_blocks_all(self):
        cb = CircuitBreaker()
        cb.trip()
        d = cb.check("anything", 0.99)
        assert d.allowed is False
        assert "TRIPPED" in d.reason

    def test_reset_restores(self):
        cb = CircuitBreaker()
        cb.trip()
        cb.reset()
        assert cb.is_tripped is False
        d = cb.check("read_file", 0.95)
        assert d.allowed is True

    def test_trip_fast_response(self):
        """熔断触发在 1 秒内生效 (轻量操作, 实际 ms 级)."""
        import time
        cb = CircuitBreaker()
        start = time.monotonic()
        cb.trip()
        cb.check("test", 0.9)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0


# ── 遥测模型 ──

class TestTelemetryModels:
    def test_heartbeat_to_dict(self):
        hb = HeartbeatStatus("agent-1", 1000.0, True, 50.0)
        d = hb.to_dict()
        assert d["agent_id"] == "agent-1"
        assert d["alive"] is True

    def test_task_dag_node_to_dict(self):
        node = TaskDAGNode("t1", "测试", "running", parent_ids=["t0"])
        d = node.to_dict()
        assert d["task_id"] == "t1"
        assert d["parent_ids"] == ["t0"]

    def test_compute_vram_usage_pct(self):
        c = ComputeTelemetry("gpu0", 0.5, 8192.0, 16384.0, 60.0)
        assert c.vram_usage_pct == 0.5

    def test_compute_vram_zero_total(self):
        c = ComputeTelemetry("cpu", 0.0, 0.0, 0.0, 40.0)
        assert c.vram_usage_pct == 0.0

    def test_compute_to_dict_includes_pct(self):
        c = ComputeTelemetry("mps", 0.2, 4096.0, 16384.0, 50.0)
        d = c.to_dict()
        assert "vram_usage_pct" in d
        assert d["vram_usage_pct"] == 0.25
