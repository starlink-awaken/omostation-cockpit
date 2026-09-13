"""Resident Flight Deck — L1-L4 风险-置信度自适应授权网关 + 四维透明指挥舱.

BET-Y1Q4-T8-23: 建立 L1~L4 四阶梯自适应风险授权拦截网关;
在 Cockpit 前端集成 Resident Flight Deck 四维透明指挥舱,
实现心跳健康、任务 DAG 流水、算力显存遥测与人工熔断介入全景可见.

四阶梯授权模型:
  L1 (routine):  置信度 ≥ 0.9 → 自动执行, 无需人工确认
  L2 (assisted): 置信度 0.7-0.9 → 执行但标记待审查
  L3 (supervised): 置信度 0.5-0.7 → 需人工预批准后执行
  L4 (blocked):  置信度 < 0.5 或命中黑名单 → 阻断, 禁止执行
"""

from __future__ import annotations

import dataclasses
import enum
import time
from typing import Any


class RiskTier(enum.IntEnum):
    """四阶梯风险授权等级."""
    L1_ROUTINE = 1
    L2_ASSISTED = 2
    L3_SUPERVISED = 3
    L4_BLOCKED = 4


class ConfidenceBand(enum.Enum):
    """置信度分档."""
    HIGH = "high"       # ≥ 0.9
    MEDIUM = "medium"   # 0.7-0.9
    LOW = "low"         # 0.5-0.7
    CRITICAL = "critical"  # < 0.5


# ── 阈值常量 (可外部配置覆盖) ──
THRESHOLD_L1 = 0.9
THRESHOLD_L2 = 0.7
THRESHOLD_L3 = 0.5

# ── 黑名单: 命中即 L4 阻断 ──
BLACKLISTED_ACTIONS = frozenset({
    "git_push",
    "git_reset_hard",
    "git_clean",
    "force_push",
    "delete_branch",
    "cloud_deploy_prod",
    "send_email",
    "publish_public",
})


@dataclasses.dataclass(frozen=True)
class AuthorizationDecision:
    """单次授权决策结果."""
    action: str
    risk_tier: RiskTier
    confidence: float
    band: ConfidenceBand
    allowed: bool
    reason: str
    requires_human_approval: bool
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "risk_tier": self.risk_tier.value,
            "risk_tier_label": self.risk_tier.name,
            "confidence": round(self.confidence, 4),
            "band": self.band.value,
            "allowed": self.allowed,
            "reason": self.reason,
            "requires_human_approval": self.requires_human_approval,
            "timestamp": self.timestamp,
        }


def classify_confidence(confidence: float) -> ConfidenceBand:
    """将置信度值映射到分档."""
    if confidence >= THRESHOLD_L1:
        return ConfidenceBand.HIGH
    elif confidence >= THRESHOLD_L2:
        return ConfidenceBand.MEDIUM
    elif confidence >= THRESHOLD_L3:
        return ConfidenceBand.LOW
    else:
        return ConfidenceBand.CRITICAL


def authorize(action: str, confidence: float, *, extra_risk: float = 0.0) -> AuthorizationDecision:
    """核心授权判定函数.

    Args:
        action: 动作标识符
        confidence: 模型/引擎给出的置信度 [0, 1]
        extra_risk: 额外风险加成 [0, 1], 用于提升风险等级

    Returns:
        AuthorizationDecision — 是否允许执行及原因
    """
    # 黑名单硬拦截
    if action in BLACKLISTED_ACTIONS:
        return AuthorizationDecision(
            action=action,
            risk_tier=RiskTier.L4_BLOCKED,
            confidence=confidence,
            band=ConfidenceBand.CRITICAL,
            allowed=False,
            reason=f"Action '{action}' is blacklisted — requires explicit human override",
            requires_human_approval=True,
        )

    # 置信度 + 额外风险 → 有效置信度
    effective_confidence = max(0.0, min(1.0, confidence - extra_risk))
    band = classify_confidence(effective_confidence)

    if band == ConfidenceBand.HIGH:
        return AuthorizationDecision(
            action=action,
            risk_tier=RiskTier.L1_ROUTINE,
            confidence=effective_confidence,
            band=band,
            allowed=True,
            reason="High confidence — auto-execute",
            requires_human_approval=False,
        )
    elif band == ConfidenceBand.MEDIUM:
        return AuthorizationDecision(
            action=action,
            risk_tier=RiskTier.L2_ASSISTED,
            confidence=effective_confidence,
            band=band,
            allowed=True,
            reason="Medium confidence — execute with post-review flag",
            requires_human_approval=False,
        )
    elif band == ConfidenceBand.LOW:
        return AuthorizationDecision(
            action=action,
            risk_tier=RiskTier.L3_SUPERVISED,
            confidence=effective_confidence,
            band=band,
            allowed=False,
            reason="Low confidence — requires human pre-approval",
            requires_human_approval=True,
        )
    else:
        return AuthorizationDecision(
            action=action,
            risk_tier=RiskTier.L4_BLOCKED,
            confidence=effective_confidence,
            band=band,
            allowed=False,
            reason="Critical risk — blocked pending human review",
            requires_human_approval=True,
        )


# ── Flight Deck 遥测数据模型 ──

@dataclasses.dataclass
class HeartbeatStatus:
    """心跳健康状态."""
    agent_id: str
    last_heartbeat: float
    alive: bool
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class TaskDAGNode:
    """任务 DAG 节点."""
    task_id: str
    label: str
    status: str  # pending | running | done | failed | blocked
    parent_ids: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ComputeTelemetry:
    """算力显存遥测."""
    device: str
    gpu_utilization: float   # 0-1
    vram_used_mb: float
    vram_total_mb: float
    temperature_c: float

    @property
    def vram_usage_pct(self) -> float:
        if self.vram_total_mb <= 0:
            return 0.0
        return self.vram_used_mb / self.vram_total_mb

    def to_dict(self) -> dict[str, Any]:
        return {
            **dataclasses.asdict(self),
            "vram_usage_pct": round(self.vram_usage_pct, 4),
        }


@dataclasses.dataclass
class FlightDeckSnapshot:
    """Flight舱全景快照 — 四维透明."""
    heartbeats: list[HeartbeatStatus]
    task_dag: list[TaskDAGNode]
    compute: list[ComputeTelemetry]
    recent_decisions: list[AuthorizationDecision]

    def to_dict(self) -> dict[str, Any]:
        return {
            "heartbeats": [h.to_dict() for h in self.heartbeats],
            "task_dag": [t.to_dict() for t in self.task_dag],
            "compute": [c.to_dict() for c in self.compute],
            "recent_decisions": [d.to_dict() for d in self.recent_decisions],
        }


# ── 熔断器 ──

class CircuitBreaker:
    """紧急人工熔断器 — 1 秒内生效."""

    def __init__(self) -> None:
        self._tripped = False
        self._tripped_at: float | None = None

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    def trip(self) -> None:
        """触发熔断."""
        self._tripped = True
        self._tripped_at = time.time()

    def reset(self) -> None:
        """复位熔断器."""
        self._tripped = False
        self._tripped_at = None

    def check(self, action: str, confidence: float) -> AuthorizationDecision:
        """熔断状态下所有写操作一律阻断."""
        if self._tripped:
            return AuthorizationDecision(
                action=action,
                risk_tier=RiskTier.L4_BLOCKED,
                confidence=confidence,
                band=ConfidenceBand.CRITICAL,
                allowed=False,
                reason="Circuit breaker TRIPPED — all actions blocked",
                requires_human_approval=True,
            )
        return authorize(action, confidence)


# ── 全局单例 ──

_flight_deck_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    """获取全局熔断器单例."""
    return _flight_deck_breaker
