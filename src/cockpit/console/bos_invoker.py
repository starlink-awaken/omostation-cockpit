"""BOS Invoker — dual-path BOS URI invocation.

Primary: Agora HTTP /v1/tools/call
Fallback: in-process resolve_bos_uri

Design constraints:
- No import from cockpit.web.* (prevents import cycles)
- agora endpoint logic inlined (only reads env var + port-registry)
- Never raises — errors go into InvokeResult.error
- Metrics recorded to .omo/_knowledge/bos-metrics.jsonl
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import replace as dc_replace
from datetime import UTC, datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any

import httpx

from cockpit.compat import WORKSPACE_ROOT
from cockpit.console.models import InvokeRequest, InvokeResult
from cockpit.console.risk import RiskLevel, classify_risk

logger = logging.getLogger("cockpit.console.bos_invoker")


# Inline agora endpoint resolution (no cockpit.web import)
def _agora_endpoint() -> str:
    env = os.environ.get("AGORA_HTTP_ENDPOINT", "").strip()
    if env:
        return env
    try:
        import yaml

        reg = WORKSPACE_ROOT / "protocols" / "port-registry.yaml"
        data = yaml.safe_load(reg.read_text(encoding="utf-8"))
        ports = data.get("ports", data) if isinstance(data, dict) else {}
        if isinstance(ports, dict):
            for p, meta in ports.items():
                if isinstance(meta, dict) and meta.get("name") == "agora-mcp-sse":
                    return f"http://127.0.0.1:{int(p)}"
    except (OSError, ValueError, TypeError):
        pass
    return "http://127.0.0.1:7431"


AGORA_ENDPOINT = _agora_endpoint()
METRICS_FILE = WORKSPACE_ROOT / ".omo" / "_knowledge" / "bos-metrics.jsonl"
MIN_TIMEOUT_MS = 500
MAX_TIMEOUT_MS = 120_000
READ_MAX_TIMEOUT_MS = 10_000


class BosInvoker:
    """Invoke BOS URIs via Agora HTTP with in-process fallback."""

    def __init__(self, agora_endpoint: str | None = None) -> None:
        self._agora_endpoint = agora_endpoint or AGORA_ENDPOINT

    async def invoke(self, req: InvokeRequest) -> InvokeResult:
        """Invoke a BOS URI. Never raises; errors in result.error."""
        # Clamp timeout
        timeout_ms = min(max(req.timeout_ms, MIN_TIMEOUT_MS), MAX_TIMEOUT_MS)
        risk = classify_risk(req.uri)
        if risk == RiskLevel.READ:
            timeout_ms = min(timeout_ms, READ_MAX_TIMEOUT_MS)

        start = asyncio.get_event_loop().time()

        try:
            result = await asyncio.wait_for(
                self._invoke_inner(req, timeout_ms),
                timeout=timeout_ms / 1000 + 1.0,  # +1s grace
            )
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            return dc_replace(result, elapsed_ms=round(elapsed, 1))
        except TimeoutError:
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            return InvokeResult(
                uri=req.uri,
                transport="http",
                route="timeout",
                elapsed_ms=round(elapsed, 1),
                result=None,
                risk=risk.value,
                confirmed=True,
                recorded_at=datetime.now(UTC).isoformat(),
                error="TIMEOUT",
            )
        except Exception as e:
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            return InvokeResult(
                uri=req.uri,
                transport="in_process",
                route="error",
                elapsed_ms=round(elapsed, 1),
                result=None,
                risk=risk.value,
                confirmed=True,
                recorded_at=datetime.now(UTC).isoformat(),
                error=str(e),
            )

    async def _invoke_inner(self, req: InvokeRequest, timeout_ms: int) -> InvokeResult:
        """Try Agora HTTP, then in-process fallback."""
        # 1. Agora HTTP
        try:
            async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
                resp = await client.post(
                    f"{self._agora_endpoint}/v1/tools/call",
                    json={
                        "tool": "bos_resolve",
                        "arguments": {"uri": req.uri, "payload": req.arguments},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok":
                        result = data.get("result", data)
                        _record_metrics(req.uri, "resolved", timeout_ms, "http")
                        return InvokeResult(
                            uri=req.uri,
                            transport="http",
                            route="agora_http",
                            elapsed_ms=0,
                            result=result,
                            risk=classify_risk(req.uri).value,
                            confirmed=True,
                            recorded_at=datetime.now(UTC).isoformat(),
                        )
        except Exception as e:
            logger.debug("Agora HTTP fallback to in-process: %s", e)

        # 2. In-process fallback
        from cockpit.adapters.agora import resolve_bos_uri

        try:
            res = resolve_bos_uri(req.uri, req.arguments)
            if isawaitable(res):
                res = await res
            _record_metrics(req.uri, "resolved", timeout_ms, "in_process")
            return InvokeResult(
                uri=req.uri,
                transport="in_process",
                route="in_process_compat",
                elapsed_ms=0,
                result=res,
                risk=classify_risk(req.uri).value,
                confirmed=True,
                recorded_at=datetime.now(UTC).isoformat(),
            )
        except Exception as e:
            return InvokeResult(
                uri=req.uri,
                transport="in_process",
                route="agora_unreachable_fallback_failed",
                elapsed_ms=0,
                result=None,
                risk=classify_risk(req.uri).value,
                confirmed=True,
                recorded_at=datetime.now(UTC).isoformat(),
                error=str(e),
            )

    @staticmethod
    def known_services(domain: str = "", query: str = "") -> list[dict]:
        """List known BOS services from POC_SERVICES registry."""
        try:
            from cockpit.adapters.agora import POC_SERVICES

            services = []
            for s in POC_SERVICES:
                if domain and s.domain != domain:
                    continue
                if query and query.lower() not in s.uri.lower():
                    continue
                services.append(
                    {
                        "uri": s.uri,
                        "domain": s.domain,
                        "action": s.action,
                        "transport": s.transport,
                        "description": getattr(s, "description", ""),
                    }
                )
            return services
        except Exception:
            return []

    @staticmethod
    def schema_for(uri: str) -> dict:
        """Extract parameter hints from POC_SERVICES for form rendering."""
        try:
            from cockpit.adapters.agora import POC_SERVICES

            for s in POC_SERVICES:
                if s.uri == uri:
                    return {
                        "uri": uri,
                        "domain": s.domain,
                        "action": s.action,
                        "transport": s.transport,
                        "risk": classify_risk(uri).value,
                        "parameters": [],  # V1: no parameter schema extraction
                        "example_arguments": {},
                    }
            return {
                "uri": uri,
                "domain": uri.removeprefix("bos://").split("/")[0] if "://" in uri else "",
                "action": "",
                "transport": "unknown",
                "risk": classify_risk(uri).value,
                "parameters": [],
                "example_arguments": {},
            }
        except Exception:
            return {
                "uri": uri,
                "domain": "",
                "action": "",
                "transport": "unknown",
                "risk": classify_risk(uri).value,
                "parameters": [],
                "example_arguments": {},
            }


def _record_metrics(uri: str, status: str, elapsed_ms: int, transport: str) -> None:
    """Append a metrics record to bos-metrics.jsonl."""
    try:
        from cockpit.omo_write_guard import append_jsonl

        append_jsonl(
            WORKSPACE_ROOT / ".omo",
            "_knowledge",
            "bos-metrics.jsonl",
            record={
                "uri": uri,
                "status": status,
                "elapsed_ms": float(elapsed_ms),
                "transport": transport,
            },
        )
    except Exception as e:
        logger.debug("Metrics recording failed (non-blocking): %s", e)


def aggregate_metrics(prefix: str = "", metrics_file: Path | None = None) -> dict:
    """Aggregate BOS metrics from JSONL file.

    Shared by api_bos.py and api_console_bos.py to avoid duplicate parsing.
    """
    import json as _json

    domain_stats: dict[str, dict] = {}
    total_calls = 0
    success_count = 0
    total_latency = 0.0
    latency_count = 0

    evidence_file = metrics_file or METRICS_FILE
    if not evidence_file.exists():
        return {
            "summary": {"total_calls": 0, "success_count": 0, "avg_latency": None},
            "domains": [],
            "data_quality": "unavailable",
        }

    try:
        for line in evidence_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = _json.loads(line)
            uri = entry.get("uri") or ""
            if not uri.startswith("bos://"):
                continue
            if prefix and not uri.startswith(prefix):
                continue

            domain = uri[6:].split("/", 1)[0]
            stats = domain_stats.setdefault(
                domain,
                {
                    "domain": domain,
                    "total": 0,
                    "success": 0,
                    "error": 0,
                    "_lat_sum": 0.0,
                    "_lat_cnt": 0,
                },
            )
            status = entry.get("status")
            elapsed = entry.get("elapsed_ms")

            stats["total"] += 1
            total_calls += 1
            if status == "resolved":
                stats["success"] += 1
                success_count += 1
            else:
                stats["error"] += 1
            if elapsed is not None:
                stats["_lat_sum"] += float(elapsed)
                stats["_lat_cnt"] += 1
                total_latency += float(elapsed)
                latency_count += 1
    except Exception:
        pass

    domains_list = []
    for d_data in domain_stats.values():
        avg_l = round(d_data["_lat_sum"] / d_data["_lat_cnt"], 1) if d_data["_lat_cnt"] else 0.0
        domains_list.append(
            {
                "domain": d_data["domain"],
                "total": d_data["total"],
                "success": d_data["success"],
                "error": d_data["error"],
                "avg_latency": avg_l,
            }
        )
    domains_list.sort(key=lambda x: x["total"], reverse=True)

    avg_overall = round(total_latency / latency_count, 1) if latency_count > 0 else None

    return {
        "summary": {
            "total_calls": total_calls,
            "success_count": success_count,
            "avg_latency": avg_overall,
        },
        "domains": domains_list,
        "data_quality": "ok" if domains_list else "unavailable",
    }
