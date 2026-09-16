"""Cockpit Console — interactive control plane for BOS, MOF, and Harness.

This package contains pure business logic (no FastAPI dependency).
Web route modules in cockpit.web import from here.
"""

from cockpit.console.bos_invoker import BosInvoker
from cockpit.console.models import (
    HarnessRunSpec,
    HarnessStageEvent,
    InvokeRequest,
    InvokeResult,
    MofViolation,
)
from cockpit.console.risk import RiskLevel, classify_risk, confirm_token, require_confirm

__all__ = [
    "BosInvoker",
    "HarnessRunSpec",
    "HarnessStageEvent",
    "InvokeRequest",
    "InvokeResult",
    "MofViolation",
    "RiskLevel",
    "classify_risk",
    "confirm_token",
    "require_confirm",
]
