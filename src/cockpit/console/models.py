"""Data models for the Cockpit Console control plane.

Pure dataclasses — no pydantic dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InvokeRequest:
    """Request to invoke a BOS URI."""

    uri: str  # must start with bos://
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 30_000  # clamped to [500, 120_000] server-side
    actor: str = "console"


@dataclass(frozen=True)
class InvokeResult:
    """Result of a BOS invocation."""

    uri: str
    transport: str  # "http" | "in_process"
    route: str  # "agora_http" | "in_process_compat" | "agora_fallback_in_process"
    elapsed_ms: float
    result: Any
    risk: str  # "read" | "write" | "dangerous"
    confirmed: bool
    recorded_at: str  # ISO UTC
    error: str | None = None


@dataclass(frozen=True)
class MofViolation:
    """A single MOF constraint violation."""

    constraint_id: str
    family: str  # e.g. "X1-C*", "CR-SFOP-*"
    severity: str  # "error" | "warning" | "advisory"
    target: str
    message: str
    fix_hint: str | None = None


@dataclass(frozen=True)
class HarnessRunSpec:
    """Specification for a Harness run."""

    bet_id: str
    profile: str
    objective: str
    worktree_path: str
    dry_run: bool = False


@dataclass(frozen=True)
class HarnessStageEvent:
    """A single event from a Harness run stage."""

    run_id: str
    stage: str  # one of the 8 stages
    state: str  # "started" | "completed" | "failed" | "skipped" | "blocked"
    check: str | None = None  # verify stage check name
    blocking: bool = False
    detail: dict[str, Any] = field(default_factory=dict)
    ts: str = ""
