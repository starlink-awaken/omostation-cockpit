"""Proposals API routes — T10-122 HITL mutation contract."""

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from cockpit.compat import WORKSPACE_ROOT

_log = logging.getLogger("cockpit.hitl")

router = APIRouter()

try:
    from cockpit.adapters.omo import (
        append_hitl_override,  # pyright: ignore[reportAttributeAccessIssue]
        approve_hitl_proposal_async,  # pyright: ignore[reportAttributeAccessIssue]
        list_hitl_proposals,  # pyright: ignore[reportAttributeAccessIssue]
        record_hitl_proposal,  # pyright: ignore[reportAttributeAccessIssue]
        reject_hitl_proposal,  # pyright: ignore[reportAttributeAccessIssue]
    )

    _OMO_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # Optional adapter; keep proposal routes discoverable.
    append_hitl_override = approve_hitl_proposal_async = list_hitl_proposals = record_hitl_proposal = reject_hitl_proposal = None  # type: ignore[assignment]
    _OMO_IMPORT_ERROR = exc

ROUTER_DEGRADED = _OMO_IMPORT_ERROR is not None
ROUTER_DEGRADED_REASON = str(_OMO_IMPORT_ERROR) if _OMO_IMPORT_ERROR else None


def _proposals_unavailable() -> JSONResponse | None:
    if _OMO_IMPORT_ERROR is None:
        return None
    return JSONResponse(
        {
            "status": "degraded",
            "error": "OMO proposal adapter is unavailable",
            "error_type": type(_OMO_IMPORT_ERROR).__name__,
            "detail": str(_OMO_IMPORT_ERROR),
            "next_action": "安装并挂载 OMO 适配器依赖后重试。",
        },
        status_code=503,
    )


@router.get("/api/v1/proposals")
async def api_list_proposals():
    unavailable = _proposals_unavailable()
    if unavailable:
        return unavailable
    try:
        proposals = list_hitl_proposals(WORKSPACE_ROOT / ".omo")  # type: ignore[union-attr]
    except Exception:  # defensive fallback
        proposals = []
    return JSONResponse({"status": "ok", "proposals": proposals})


def _resolve_approver_identity(authorization: str | None = None) -> dict[str, Any]:
    """Resolve approver identity from Authorization header.

    Phase B: supports server-owned identity via service token.
    Format: "Bearer <token>" or "Service <service_token>"
    """
    if not authorization:
        return {
            "principal_ref": "operator://anonymous",
            "source_class": "anonymous",
            "credential_digest": "none",
        }

    if authorization.startswith("Service "):
        token = authorization[len("Service "):].strip()
        # In Phase B, service tokens are pre-shared secrets
        # TODO: validate against configured service tokens
        import hashlib
        digest = hashlib.sha256(token.encode()).hexdigest()[:16]
        return {
            "principal_ref": f"operator://service/{digest}",
            "source_class": "server_owned",
            "credential_digest": digest,
        }

    if authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
        import hashlib
        digest = hashlib.sha256(token.encode()).hexdigest()[:16]
        return {
            "principal_ref": f"operator://cockpit-api/{digest}",
            "source_class": "real_human",
            "credential_digest": digest,
        }

    return {
        "principal_ref": "operator://anonymous",
        "source_class": "anonymous",
        "credential_digest": "none",
    }


@router.post("/api/v1/proposals")
async def api_create_proposal(
    request: dict,
    authorization: str | None = Header(None),
):
    """Create a new HITL proposal (called from Dashboard)."""
    unavailable = _proposals_unavailable()
    if unavailable:
        return unavailable

    try:
        # Record proposal via OMO broker
        proposal = record_hitl_proposal(  # type: ignore[union-attr]
            WORKSPACE_ROOT / ".omo",
            request,
        )
        _log.info("[HITL] Proposal created: %s (type=%s)", proposal.get("proposal_id"), proposal.get("type"))
        return JSONResponse({
            "status": "ok",
            "proposal_id": proposal.get("proposal_id"),
            "proposal": proposal,
        }, status_code=202)
    except ValueError as e:
        _log.warning("[HITL] Proposal creation failed: %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=400)
    except Exception as e:
        _log.error("[HITL] Unexpected error creating proposal: %s", e)
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


async def _execute_mutation(proposal: dict) -> bool:
    import logging

    _log = logging.getLogger("cockpit.hitl")

    p_type = proposal.get("type")
    debt_id = proposal.get("debt_id", "unknown")
    _log.info("[HITL] Executing mutation: %s for %s", p_type, debt_id)

    if p_type == "budget_increase":
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "debt_id": debt_id,
            "action": "increase_limit",
            "amount_usd": 0.10,
            "status": "applied",
        }
        append_hitl_override(WORKSPACE_ROOT / ".omo", "budget_overrides.jsonl", record)  # type: ignore[union-attr]
        return True
    elif p_type == "model_swap":
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "debt_id": debt_id,
            "action": "swap_model",
            "target_model": proposal.get("target_model", "claude-3-haiku"),
            "status": "applied",
        }
        append_hitl_override(WORKSPACE_ROOT / ".omo", "model_overrides.jsonl", record)  # type: ignore[union-attr]
        return True
    elif p_type == "quota_reset":
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "debt_id": debt_id,
            "action": "reset_quota",
            "scope": proposal.get("scope", "global"),
            "status": "applied",
        }
        append_hitl_override(WORKSPACE_ROOT / ".omo", "quota_resets.jsonl", record)  # type: ignore[union-attr]
        return True

    # Plugin Mechanism (BOS URI Hook)
    try:
        from cockpit.adapters.agora import resolve_bos_uri  # pyright: ignore[reportAttributeAccessIssue]

        res = await resolve_bos_uri(f"bos://governance/hitl/execute/{p_type}", proposal)
        if res and res.get("status") == "ok":
            return True
    except Exception as e:  # defensive fallback
        _log.debug("[HITL] Plugin dispatch not found or failed for %s: %s", p_type, e)

    return False


@router.post("/api/v1/proposals/{proposal_id}/approve")
async def api_approve_proposal(
    proposal_id: str,
    authorization: str | None = Header(None),
):
    unavailable = _proposals_unavailable()
    if unavailable:
        return unavailable

    # Resolve approver identity
    approver = _resolve_approver_identity(authorization)
    _log.info("[HITL] Approving %s by %s (%s)", proposal_id, approver["principal_ref"], approver["source_class"])

    success, error = await approve_hitl_proposal_async(  # type: ignore[union-attr]
        WORKSPACE_ROOT / ".omo",
        proposal_id,
        execute_mutation=_execute_mutation,
    )
    if success:
        # Generate receipt
        receipt = {
            "proposal_id": proposal_id,
            "status": "approved",
            "approver": approver["principal_ref"],
            "source_class": approver["source_class"],
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        _log.info("[HITL] Proposal %s approved: %s", proposal_id, receipt)
        return JSONResponse({"status": "ok", "message": f"Proposal {proposal_id} approved and executed.", "receipt": receipt})
    if error and "not found" in error:
        return JSONResponse({"status": "error", "error": error}, status_code=404)
    if error and "already being processed" in error:
        return JSONResponse({"status": "error", "error": error}, status_code=409)
    if error and "No execution logic" in error:
        _log.warning("[HITL] %s", error)
        return JSONResponse({"status": "error", "error": error}, status_code=400)
    return JSONResponse({"status": "error", "error": error or "unknown error"}, status_code=500)


@router.post("/api/v1/proposals/{proposal_id}/reject")
async def api_reject_proposal(proposal_id: str):
    unavailable = _proposals_unavailable()
    if unavailable:
        return unavailable
    reject_hitl_proposal(WORKSPACE_ROOT / ".omo", proposal_id)  # type: ignore[union-attr]
    return JSONResponse({"status": "ok"})


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
