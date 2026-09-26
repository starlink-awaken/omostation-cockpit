"""Shared router loading registry for dashboard diagnostics and SystemMap."""

from __future__ import annotations

ROUTER_MODULES = (
    "cockpit.web.governance.api",
    "cockpit.web.api_compute",
    "cockpit.web.api_svc",
    "cockpit.web.api_domain_apps",
    "cockpit.web.api_system_map",
    "cockpit.web.api_omos",
    "cockpit.web.api_ecos",
    "cockpit.web.api_knowledge",
    "cockpit.web.api_memory",
    "cockpit.web.api_bos",
    "cockpit.web.api_proposals",
    "cockpit.web.mobile_api",
    "cockpit.web.api_metaos",
    "cockpit.web.api_agora",
    "cockpit.web.api_sandbox",
    "cockpit.web.api_l4",
    "cockpit.web.api_health",
    "cockpit.web.api_alerts",
    "cockpit.web.api_tasks",
    "cockpit.web.api_kems",
    "cockpit.web.api_logs",
    "cockpit.web.api_metrics",
    "cockpit.web.api_observability",
    "cockpit.web.api_observatory",
    "cockpit.web.api_hubs",
    "cockpit.web.api_delivery_journey",
    "cockpit.web.api_workflow_mesh_operations",
    "cockpit.web.api_knowledge_actions",
    "cockpit.web.api_external_resources",
    "cockpit.web.api_scene_cards",
    "cockpit.web.api_scene_lifecycle",
    "cockpit.web.api_decision_inbox",
    "cockpit.web.api_intake_pipeline",
    "cockpit.web.api_approval_flow",
    "cockpit.web.api_week4",
    "cockpit.web.api_swarm",
    "cockpit.web.api_outcomes",
    "cockpit.web.api_journeys",
    "cockpit.web.api_unified_inbox",
    "cockpit.web.api_commands",
    "cockpit.web.api_chains",
    "cockpit.web.api_command_audit",
    "cockpit.web.api_reflection",
    "cockpit.web.api_work_cases",
    "cockpit.web.api_console_bos",
    "cockpit.web.api_console_mof",
    "cockpit.web.api_console_harness",
    "cockpit.web.api_console_meta",
)

CRITICAL_ROUTERS = frozenset(
    {
        "cockpit.web.governance.api",
        "cockpit.web.api_memory",
        "cockpit.web.api_scene_cards",
        "cockpit.web.api_scene_lifecycle",
        "cockpit.web.api_workflow_mesh_operations",
        "cockpit.web.api_unified_inbox",
        "cockpit.web.api_flight_deck",
    }
)

ROUTER_LOAD_REPORT: list[dict[str, object]] = []


def router_health_snapshot() -> dict[str, object]:
    """Return a stable, read-only snapshot for SystemMap and operator views."""
    loaded = sum(1 for item in ROUTER_LOAD_REPORT if item.get("status") == "loaded")
    critical_failed = [
        item for item in ROUTER_LOAD_REPORT
        if item.get("status") != "loaded" and item.get("module") in CRITICAL_ROUTERS
    ]
    degraded = [
        item for item in ROUTER_LOAD_REPORT
        if item.get("status") != "loaded" and item.get("module") not in CRITICAL_ROUTERS
    ]
    status = "ready" if not critical_failed and ROUTER_LOAD_REPORT else "degraded" if critical_failed else "attention"
    return {
        "status": status,
        "summary": {
            "total": len(ROUTER_LOAD_REPORT),
            "loaded": loaded,
            "critical_failed": len(critical_failed),
            "unavailable": len(critical_failed),
            "degraded": len(degraded),
        },
        "critical_failed": [dict(item) for item in critical_failed],
        "degraded": [dict(item) for item in degraded],
        "items": [dict(item) for item in ROUTER_LOAD_REPORT],
    }
