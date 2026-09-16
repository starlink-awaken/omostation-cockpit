"""Risk classification and high-risk confirmation for Console operations.

Security boundary: when COCKPIT_AUTH_REQUIRED=false (default),
X-Console-Confirm is the only real protection against accidental
dangerous operations.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    READ = "read"  # no side effects
    WRITE = "write"  # has side effects, reversible
    DANGEROUS = "dangerous"  # irreversible / circuit-break / external


# Action keywords that indicate dangerous operations
_DANGEROUS_ACTIONS = frozenset(
    {"enforce", "delete", "trip", "reset", "closeout", "sign", "sediment"}
)

# Action keywords that indicate write operations
_WRITE_ACTIONS = frozenset(
    {
        "write",
        "put",
        "create",
        "submit",
        "run",
        "infer",
        "compile",
        "trigger",
        "patch",
        "challenge",
        "inject",
    }
)

# Read-safe action keywords
_READ_ACTIONS = frozenset(
    {
        "health",
        "status",
        "list",
        "snapshot",
        "metrics",
        "query",
        "resolve",
        "check",
        "audit",
        "evaluate",
    }
)


def classify_risk(uri: str) -> RiskLevel:
    """Classify a BOS URI by risk level based on domain and action segments.

    Rules (longest suffix match wins):
    - dangerous: action contains any dangerous keyword, OR domain == "harness"
    - write: action contains any write keyword
    - read: everything else
    """
    try:
        # Parse bos://domain/subdomain/action
        rest = uri.removeprefix("bos://")
        parts = rest.split("/")
        if len(parts) < 2:
            return RiskLevel.READ
        domain = parts[0]
        action = parts[-1].lower()  # last segment is the action

        # Harness domain is always dangerous
        if domain == "harness":
            return RiskLevel.DANGEROUS

        # Check action against dangerous keywords
        for kw in _DANGEROUS_ACTIONS:
            if kw in action:
                return RiskLevel.DANGEROUS

        # Also check subdomain segments for dangerous keywords
        # (e.g. bos://resident/sediment/trigger — "sediment" in subdomain)
        for sub in parts[1:-1]:  # middle segments (exclude domain and action)
            for kw in _DANGEROUS_ACTIONS:
                if kw in sub.lower():
                    return RiskLevel.DANGEROUS

        # Check action against write keywords
        for kw in _WRITE_ACTIONS:
            if kw in action:
                return RiskLevel.WRITE

        # Check action against read keywords
        for kw in _READ_ACTIONS:
            if kw in action:
                return RiskLevel.READ

        # Default: read (safe by default)
        return RiskLevel.READ

    except Exception:
        return RiskLevel.READ


def confirm_token(uri: str, body_bytes: bytes) -> str:
    """Generate a confirmation token binding the URI and request body.

    Format: "{uri}:sha256(body)[:16]"
    The client must echo this exact value in X-Console-Confirm header.
    """
    digest = hashlib.sha256(body_bytes).hexdigest()[:16]
    return f"{uri}:{digest}"


def require_confirm(
    level: RiskLevel,
    uri: str,
    body_bytes: bytes,
    header_value: str | None,
) -> str | None:
    """Validate the confirmation header for high-risk operations.

    Returns None if the request is allowed to proceed, or a machine-readable
    rejection code otherwise.

    Rejection codes:
    - RISK_CONFIRM_REQUIRED: level is write/dangerous but header missing
    - RISK_CONFIRM_MISMATCH: header present but doesn't match expected token
    """
    if level == RiskLevel.READ:
        return None  # read operations never need confirmation

    if not header_value:
        return "RISK_CONFIRM_REQUIRED"

    expected = confirm_token(uri, body_bytes)
    if header_value != expected:
        return "RISK_CONFIRM_MISMATCH"

    return None
