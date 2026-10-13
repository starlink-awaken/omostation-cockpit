"""Contract tests for the Cockpit read-only Zhixing projection adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpit.dashboard import panorama_adapter
from cockpit.dashboard import routes as dashboard_routes

NOW = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)
FETCHED_AT = "2026-10-05T14:00:00Z"
REVISION = "revision-123"
GENERATED_AT = "2026-10-05T13:59:30Z"


def _health(*, projection_status: str = "BOUND_FRESH", code_drift: bool = False, projection_fresh_until: str = "2026-10-05T14:05:00Z", state_revision: str = REVISION) -> dict[str, Any]:
    return {"read_only": True, "code_drift": code_drift, "projection_status": projection_status, "projection_fresh_until": projection_fresh_until, "state_revision": state_revision}


def _full_projection(
    *,
    generated_at: str = GENERATED_AT,
    revision_id: str = REVISION,
    gate_provenance: bool = True,
) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "generated_at": generated_at,
        "generation_id": "generation-123",
        "gates": [{"id": "A1", "title": "A1", "verdict": "PASS", "detail": "observed", "live": True}],
        "alerts": {"alerts": [{"id": "full-alert", "severity": "high", "msg": "observed failure"}]},
        "knowledge_health": _compact_projection()["knowledge_health"],
        "experience_graph": _compact_projection()["experience_graph"],
        "connectors": _compact_projection()["connectors"],
    }
    if gate_provenance:
        projection["field_provenance"] = {
            name: {
                "revision_id": revision_id,
                "observed_at": generated_at,
                "source_digest": panorama_adapter._canonical_digest(projection[name]),
                "source_ref": f"bin/panorama/panorama-collect.py::collect_{name}",
            }
            for name in ("gates", "alerts", "knowledge_health", "experience_graph", "connectors")
        }
    return projection


def _compact_projection(*, generated_at: str = GENERATED_AT, source: str = REVISION) -> dict[str, Any]:
    """The actual ``/__panorama_data__`` shape, without full gates or alerts."""
    return {
        "generated_at": generated_at,
        "generation_id": "generation-123",
        "source": source,
        "bos_verifier": {"last_run_errors": 3, "last_run_ok": 226},
        "connectors": {"total": 2, "available": ["github"], "wired_to_scenes": ["github"], "unwired_available": []},
        "knowledge_health": {"total": 12, "fresh": 10, "stale": 2, "orphaned": 0, "freshness_pct": 83.3, "coverage_pct": 100.0, "orphan_pct": 0.0, "stale_docs": [{"path": "docs/old.md", "age_days": 9}]},
        "experience_graph": {"nodes_by_type": {"decision": 4}, "internal_refs": 7, "hotspots": [{"type": "decision", "count": 4}], "connectivity_pct": 68},
    }


def _brief(*, generated_at: str = GENERATED_AT) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "health": {
            "gates_total": 11,
            "gates_pass": 3,
            "gates_failing": ["A2", "A4", "RF0"],
            "reference_cell": {"id": "RC-DL", "verdict": "PASS"},
        },
        "objective_coverage": {"items": [{"id": "OBJECTIVE", "status": "PARTIAL"}]},
        "work_state": {"alerts": {"total": 0, "recent": []}},
    }


def _observation(
    *,
    status: str = "OBSERVED",
    observed_at: str = "2026-10-05T13:59:45Z",
    error_class: str | None = None,
    source_digest: str | None = None,
    source_ref: str = "bin/panorama/panorama-collect.py::collect_knowledge_health",
) -> dict[str, Any]:
    value = {
        "total": 20, "fresh": 19, "stale": 1, "orphaned": 0,
        "freshness_pct": 95.0, "coverage_pct": 100.0, "orphan_pct": 0.0,
    }
    return {
        "schema": panorama_adapter.PANORAMA_OBSERVATION_SCHEMA,
        "facets": {
            "knowledge_health": {
                "status": status,
                "observation_status": status,
                "value": value,
                "source_digest": source_digest or panorama_adapter._canonical_digest(value),
                "observed_at": observed_at,
                "last_attempt_at": "2026-10-05T13:59:50Z",
                "last_success_at": observed_at,
                "error_class": error_class,
                "duration_ms": 42,
                "overrun": False,
                "provenance": {
                    "kind": "direct-read",
                    "source_ref": source_ref,
                    "collector_sha256": panorama_adapter._current_observation_collector_digest(),
                    "source_digest": source_digest or panorama_adapter._canonical_digest(value),
                },
            }
        },
    }


def _launchd_observation(*, registry_digest: str = "c" * 64) -> dict[str, Any]:
    value = {
        "schema": "launchd-health-observation/v1", "available": True,
        "facet_state": "LIVE", "verdict": "PASS", "loaded": 1, "failed": 0,
        "registry_sha256": registry_digest,
        "jobs": [{
            "name": "demo", "label": "com.omostation.demo", "uid": 501,
            "schedule": "every-4m", "observed_at": GENERATED_AT,
            "command_result_class": "loaded", "command_exit_code": 0,
            "stdout": "state = running", "stderr": "", "parsed": {"state": "running"},
            "semantic_verdict": "PASS",
        }],
    }
    digest = panorama_adapter._canonical_digest(value)
    return {
        "schema": panorama_adapter.PANORAMA_OBSERVATION_SCHEMA,
        "facets": {
            "launchd_health": {
                "status": "OBSERVED", "observation_status": "OBSERVED", "value": value,
                "source_digest": digest, "observed_at": GENERATED_AT,
                "last_attempt_at": GENERATED_AT, "last_success_at": GENERATED_AT,
                "error_class": None, "duration_ms": 17, "overrun": False,
                "provenance": {
                    "kind": "direct-read",
                    "source_ref": "bin/panorama/panorama-collect.py::collect_launchd_health",
                    "collector_sha256": panorama_adapter._current_observation_collector_digest(),
                    "source_digest": digest, "registry_sha256": registry_digest,
                },
            },
        },
    }


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _response(request: httpx.Request, *, health: object, full: object | None = None, compact: object | None = None, brief: object | None = None) -> httpx.Response:
    paths: dict[str, object | None] = {"/health": health, "/data.json": full, "/__panorama_data__": compact, "/agent-brief.json": brief}
    body = paths.get(request.url.path)
    if body is None:
        return httpx.Response(404, json={"error": "not_found"})
    return httpx.Response(200, json=body)


def test_full_bound_projection_is_preferred_when_readable() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return _response(request, health=_health(), full=_full_projection(), compact=_compact_projection())

    payload = asyncio.run(panorama_adapter.fetch_panorama_projection(transport=_transport(handler), now=NOW, fetched_at=FETCHED_AT))

    assert seen == ["/health", "/data.json", "/__panorama_data__"]
    assert payload["data_state"] == "PARTIAL"
    assert payload["source"]["url"] == panorama_adapter.PANORAMA_FULL_DATA_URL
    assert payload["gates"] == [{"id": "A1", "title": "A1", "verdict": "PASS", "detail": "observed", "live": True, "last_checked_at": None}]
    assert payload["alerts"][0]["id"] == "full-alert"
    assert "gates" not in payload["source"]["partial_facets"]


def test_full_projection_binds_agent_visibility_to_generation_and_revision() -> None:
    projection = _full_projection()
    visibility = {
        "schema": "agent-visibility/v1",
        "available": True,
        "generated_at": GENERATED_AT,
        "generation_id": projection["generation_id"],
        "input_sources": {"claims": {"status": "UNPROVABLE", "source_ref": "claims"}},
    }
    projection["agent_visibility"] = visibility

    payload = panorama_adapter.project_full_projection(
        projection, _health(), compact_binding=_compact_projection(), observation=_observation(),
        now=NOW, fetched_at=FETCHED_AT,
    )

    observed = payload["source"]["facet_observations"]["agent_visibility"]
    assert observed["state"] == "LIVE"
    assert observed["source_generation_id"] == projection["generation_id"]
    assert observed["source_revision_id"] == REVISION
    assert observed["duration_ms"] is None
    assert observed["source_digest"] == panorama_adapter._canonical_digest(visibility)
    assert payload["agent_visibility"]["input_sources"]["claims"]["status"] == "UNPROVABLE"
    assert payload["source"]["facet_observations"]["knowledge_health"]["state"] == "LIVE"


def test_full_projection_agent_visibility_generation_mismatch_stays_unverified() -> None:
    projection = _full_projection()
    projection["agent_visibility"] = {
        "schema": "agent-visibility/v1", "available": True, "generated_at": GENERATED_AT,
        "generation_id": "older-generation", "input_sources": {},
    }

    payload = panorama_adapter.project_full_projection(
        projection, _health(), compact_binding=_compact_projection(), now=NOW, fetched_at=FETCHED_AT,
    )

    assert "agent_visibility" not in payload["source"].get("facet_observations", {})
    assert "agent_visibility" in payload["source"]["partial_facets"]


def test_unknown_defaults_never_masquerade_as_zero_offline_or_empty_success() -> None:
    payload = panorama_adapter._unknown_payload("upstream_unavailable", FETCHED_AT)

    assert payload["posture"] == {
        "health_score": None,
        "compliance_rate": None,
        "active_agents_count": None,
    }
    assert payload["guardian"] == {
        "interval_seconds": None,
        "status": "UNKNOWN",
        "last_heartbeat": None,
        "healthy_count": None,
        "warning_count": None,
        "danger_count": None,
    }
    assert payload["topology"] is None
    assert payload["evolution"] is None


def test_full_projection_revision_or_gate_evidence_mismatch_never_promotes_gates() -> None:
    bad_binding = _compact_projection(source="wrong-revision")
    try:
        panorama_adapter.project_full_projection(
            _full_projection(),
            _health(),
            compact_binding=bad_binding,
            now=NOW,
            fetched_at=FETCHED_AT,
        )
    except panorama_adapter.PanoramaSourceError as exc:
        assert str(exc) == "projection_revision_mismatch"
    else:
        raise AssertionError("a full projection must bind to health.state_revision")

    missing_evidence = _full_projection(gate_provenance=False)
    payload = panorama_adapter.project_full_projection(
        missing_evidence,
        _health(),
        compact_binding=_compact_projection(),
        now=NOW,
        fetched_at=FETCHED_AT,
    )
    assert payload["gates"] == panorama_adapter._unknown_gates()
    assert "gates" in payload["source"]["partial_facets"]
    assert payload["alerts"] == []
    assert "alerts" in payload["source"]["partial_facets"]

    digest_mismatch = _full_projection()
    digest_mismatch["field_provenance"]["gates"]["source_digest"] = "0" * 64
    payload = panorama_adapter.project_full_projection(
        digest_mismatch,
        _health(),
        compact_binding=_compact_projection(),
        now=NOW,
        fetched_at=FETCHED_AT,
    )
    assert payload["gates"] == panorama_adapter._unknown_gates()
    assert "gates" in payload["source"]["partial_facets"]

    missing_source_ref = _full_projection()
    missing_source_ref["field_provenance"]["gates"].pop("source_ref")
    payload = panorama_adapter.project_full_projection(
        missing_source_ref,
        _health(),
        compact_binding=_compact_projection(),
        now=NOW,
        fetched_at=FETCHED_AT,
    )
    assert payload["gates"] == panorama_adapter._unknown_gates()
    assert "gates" in payload["source"]["partial_facets"]


def test_full_projection_uses_fresh_direct_facet_without_refreshing_projection_age(tmp_path: Path) -> None:
    observation_path = tmp_path / "compact-observation.json"
    observation_path.write_text(json.dumps(_observation()))

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            request,
            health=_health(),
            full=_full_projection(generated_at="2026-10-05T13:50:00Z"),
            compact=_compact_projection(generated_at="2026-10-05T13:50:00Z"),
        )

    payload = asyncio.run(
        panorama_adapter.fetch_panorama_projection(
            transport=_transport(handler),
            observation_path=observation_path,
            now=NOW,
            fetched_at=FETCHED_AT,
        )
    )

    assert payload["data_state"] == "STALE"
    assert payload["knowledge_health"]["total"] == 20
    assert payload["source"]["facet_observations"]["knowledge_health"]["state"] == "LIVE"
    assert payload["source"]["observed_at"] == "2026-10-05T13:50:00Z"


def test_direct_evolution_and_workspace_facets_require_bounded_source_contract() -> None:
    values = {
        "evolution": {
            "total": 1,
            "proposal_paths": [".omo/state/evolution-proposals/a.yaml"],
            "recent_proposals": ["a"],
        },
        "workspace": {
            "worktrees": [{"path": "/tmp/worktree", "branch": "main"}],
            "total_worktrees": 1,
            "lock_files": [".omo/_delivery/agent-workflows/locks/example.yaml"],
            "total_lock_files": 1,
        },
    }
    source_refs = {
        "evolution": "bin/panorama/panorama-collect.py::collect_evolution",
        "workspace": "bin/panorama/panorama-collect.py::collect_workspace_hygiene",
    }
    facets = {}
    for name, value in values.items():
        digest = panorama_adapter._canonical_digest(value)
        facets[name] = {
            "status": "OBSERVED",
            "observation_status": "OBSERVED",
            "value": value,
            "source_digest": digest,
            "observed_at": "2026-10-05T13:59:45Z",
            "last_attempt_at": "2026-10-05T13:59:50Z",
            "last_success_at": "2026-10-05T13:59:45Z",
            "error_class": None,
            "duration_ms": 24,
            "overrun": False,
            "provenance": {
                "kind": "direct-read",
                "source_ref": source_refs[name],
                "collector_sha256": panorama_adapter._current_observation_collector_digest(),
                "source_digest": digest,
            },
        }
    observation = {"schema": panorama_adapter.PANORAMA_OBSERVATION_SCHEMA, "facets": facets}

    payload = panorama_adapter.project_full_projection(
        _full_projection(),
        _health(),
        compact_binding=_compact_projection(),
        observation=observation,
        now=NOW,
        fetched_at=FETCHED_AT,
    )

    assert payload["evolution"] == values["evolution"]
    assert payload["workspace"] == values["workspace"]
    assert "evolution" not in payload["source"]["partial_facets"]
    assert "workspace" not in payload["source"]["partial_facets"]
    assert payload["source"]["facet_observations"]["workspace"]["provenance"]["source_digest"] == facets["workspace"]["source_digest"]


def test_workspace_orphan_locks_legacy_field_does_not_promote_facet() -> None:
    value = {
        "worktrees": [],
        "total_worktrees": 0,
        "orphan_locks": [],
        "total_locks": 0,
    }
    digest = panorama_adapter._canonical_digest(value)
    observation = {
        "schema": panorama_adapter.PANORAMA_OBSERVATION_SCHEMA,
        "facets": {
            "workspace": {
                "status": "OBSERVED",
                "observation_status": "OBSERVED",
                "value": value,
                "source_digest": digest,
                "observed_at": "2026-10-05T13:59:45Z",
                "last_attempt_at": "2026-10-05T13:59:50Z",
                "last_success_at": "2026-10-05T13:59:45Z",
                "error_class": None,
                "duration_ms": 24,
                "overrun": False,
                "provenance": {
                    "kind": "direct-read",
                    "source_ref": "bin/panorama/panorama-collect.py::collect_workspace_hygiene",
                    "collector_sha256": panorama_adapter._current_observation_collector_digest(),
                    "source_digest": digest,
                },
            }
        },
    }

    payload = panorama_adapter.project_full_projection(
        _full_projection(), _health(), compact_binding=_compact_projection(),
        observation=observation, now=NOW, fetched_at=FETCHED_AT,
    )

    assert "workspace" not in payload
    assert "workspace" in payload["source"]["partial_facets"]


def test_full_projection_normalizes_known_nonterminal_gate_states() -> None:
    gates = panorama_adapter._project_gates([
        {"id": "A6", "title": "Orca R0 准入", "verdict": "NOT_ADMITTED", "detail": "R0 evidence incomplete"},
        {"id": "A8", "title": "OMO 外部执行事务", "verdict": "ABSENT", "detail": "merge evidence missing"},
        {"id": "A9", "title": "ASD 与 Cockpit 可观测", "verdict": "PARTIAL", "detail": "some checks unavailable"},
        {"id": "A9", "title": "Awaiting review", "verdict": "PENDING", "detail": "review is running"},
    ])

    assert [gate["verdict"] for gate in gates] == ["BLOCKED", "UNKNOWN", "WARN", "PENDING"]
    assert "NOT_ADMITTED" in gates[0]["detail"]
    assert "ABSENT" in gates[1]["detail"]
    assert "PARTIAL" in gates[2]["detail"]
    assert gates[3]["detail"] == "review is running"


def test_full_projection_rejects_unrecognized_gate_state() -> None:
    try:
        panorama_adapter._project_gates([
            {"id": "A1", "title": "A1", "verdict": "MAYBE"},
        ])
    except panorama_adapter.PanoramaSourceError as exc:
        assert str(exc) == "schema_invalid:gates[0].verdict"
    else:
        raise AssertionError("unrecognized gate states must remain fail-closed")


def test_known_bound_reader_failure_uses_compact_and_agent_brief_without_promoting_objectives() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/data.json":
            return httpx.Response(503, json={"error": "agent_projection_unavailable", "read_only": True})
        return _response(request, health=_health(), compact=_compact_projection(), brief=_brief())

    payload = asyncio.run(panorama_adapter.fetch_panorama_projection(transport=_transport(handler), now=NOW, fetched_at=FETCHED_AT))

    assert seen == ["/health", "/data.json", "/__panorama_data__", "/agent-brief.json"]
    assert payload["data_state"] == "PARTIAL"
    assert payload["source"]["url"] == panorama_adapter.PANORAMA_COMPACT_DATA_URL
    assert payload["source"]["error"] == "bound_reader_unavailable"
    assert payload["source"]["source_paths"] == {"full": panorama_adapter.PANORAMA_FULL_DATA_URL, "compact": panorama_adapter.PANORAMA_COMPACT_DATA_URL, "agent_brief": panorama_adapter.PANORAMA_AGENT_BRIEF_URL}
    assert "gate_summary" not in payload["source"]
    verdicts = {item["id"]: item["verdict"] for item in payload["gates"]}
    assert set(verdicts.values()) == {"UNKNOWN"}
    assert "OBJECTIVE" not in verdicts
    assert "knowledge_health" not in payload
    assert "experience_graph" not in payload
    assert "connectors" not in payload
    assert payload["alerts"] == []
    assert {"gates", "alerts", "knowledge_health", "experience_graph", "connectors"} <= set(payload["source"]["partial_facets"])
    assert {"alerts", "posture", "guardian", "topology", "evolution"} <= set(payload["source"]["partial_facets"])


def test_complete_compact_fallback_chain_fits_total_timeout_budget() -> None:
    class SlowLocalSource(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.9)
            path = urlparse(str(request.url)).path
            if path == "/health":
                return httpx.Response(200, json=_health(), request=request)
            if path == "/data.json":
                return httpx.Response(503, json={"error": "agent_projection_unavailable"}, request=request)
            if path == "/__panorama_data__":
                return httpx.Response(200, json=_compact_projection(), request=request)
            if path == "/agent-brief.json":
                return httpx.Response(200, json=_brief(), request=request)
            return httpx.Response(404, json={"error": "not_found"}, request=request)

    payload = asyncio.run(
        panorama_adapter.fetch_panorama_projection(
            transport=SlowLocalSource(),
            now=NOW,
            fetched_at=FETCHED_AT,
        )
    )

    assert payload["data_state"] == "PARTIAL"
    assert payload["source"]["url"] == panorama_adapter.PANORAMA_COMPACT_DATA_URL
    assert payload["source"]["error"] == "bound_reader_unavailable"


def test_unknown_full_route_error_does_not_fall_back_as_success() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/data.json":
            return httpx.Response(503, json={"error": "different_failure"})
        return _response(request, health=_health())

    payload = asyncio.run(panorama_adapter.fetch_panorama_projection(transport=_transport(handler), now=NOW, fetched_at=FETCHED_AT))

    assert seen == ["/health", "/data.json"]
    assert payload["data_state"] == "UNKNOWN"
    assert payload["source"]["error"] == "upstream_request_failed:full_projection:HTTPStatusError"


def test_upstream_read_timeout_is_reported_as_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/data.json":
            raise httpx.ReadTimeout("projection read exceeded request budget", request=request)
        return _response(request, health=_health())

    payload = asyncio.run(
        panorama_adapter.fetch_panorama_projection(
            transport=_transport(handler), now=NOW, fetched_at=FETCHED_AT
        )
    )

    assert payload["data_state"] == "UNKNOWN"
    assert payload["source"]["error"] == "upstream_timeout:full_projection"


def test_stale_compact_projection_remains_visible_with_stale_state() -> None:
    compact = _compact_projection(generated_at="2026-10-05T13:50:00Z")
    brief = _brief(generated_at="2026-10-05T13:50:00Z")

    payload = panorama_adapter.project_compact_projection(compact, brief, _health(), now=NOW, fetched_at=FETCHED_AT)

    assert payload["data_state"] == "STALE"
    assert payload["source"]["status"] == "STALE"
    assert payload["source"]["error"] == "projection_stale"
    assert "knowledge_health" not in payload
    assert "experience_graph" not in payload
    assert {item["id"]: item["verdict"] for item in payload["gates"]}["A2"] == "UNKNOWN"


def test_stale_full_projection_remains_visible_with_stale_state() -> None:
    payload = panorama_adapter.project_full_projection(
        _full_projection(generated_at="2026-10-05T13:50:00Z"),
        _health(),
        compact_binding=_compact_projection(generated_at="2026-10-05T13:50:00Z"),
        now=NOW,
        fetched_at=FETCHED_AT,
    )

    assert payload["data_state"] == "STALE"
    assert payload["source"]["status"] == "STALE"
    assert payload["source"]["error"] == "projection_stale"
    assert payload["gates"][0]["verdict"] == "UNKNOWN"


def test_provenance_mismatched_compact_projection_fails_closed() -> None:
    cases = [
        (_compact_projection(source="wrong-revision"), _brief(), _health(), "projection_revision_mismatch"),
        (_compact_projection(), _brief(generated_at="2026-10-05T13:59:29Z"), _health(), "projection_generation_mismatch"),
    ]
    for compact, brief, health, expected in cases:
        def handler(request: httpx.Request, c: dict[str, Any] = compact, b: dict[str, Any] = brief, h: dict[str, Any] = health) -> httpx.Response:
            if request.url.path == "/data.json":
                return httpx.Response(503, json={"error": "agent_projection_unavailable"})
            return _response(request, health=h, compact=c, brief=b)

        payload = asyncio.run(panorama_adapter.fetch_panorama_projection(transport=_transport(handler), now=NOW, fetched_at=FETCHED_AT))
        assert payload["data_state"] == "UNKNOWN"
        assert payload["source"]["error"] == expected


def test_missing_compact_optional_sections_stay_partial_without_synthesizing_data() -> None:
    compact = _compact_projection()
    compact["connectors"] = {"total": 2, "available": ["github"]}
    compact.pop("knowledge_health")
    compact["experience_graph"] = {"nodes_by_type": {"decision": "four"}}
    compact["bos_verifier"] = {"last_run_errors": "unknown"}

    payload = panorama_adapter.project_compact_projection(compact, _brief(), _health(), now=NOW, fetched_at=FETCHED_AT)

    assert "connectors" not in payload
    assert "knowledge_health" not in payload
    assert "experience_graph" not in payload
    assert payload["alerts"] == []
    assert {"connectors", "knowledge_health", "experience_graph", "alerts"} <= set(payload["source"]["partial_facets"])


def test_direct_observation_refreshes_only_its_facet_and_lease_does_not_advance_it() -> None:
    compact = _compact_projection(generated_at="2026-10-05T13:50:00Z")
    brief = _brief(generated_at="2026-10-05T13:50:00Z")
    observation = _observation()

    first = panorama_adapter.project_compact_projection(
        compact,
        brief,
        _health(projection_fresh_until="2026-10-05T14:05:00Z"),
        observation=observation,
        now=NOW,
        fetched_at=FETCHED_AT,
    )
    renewed = panorama_adapter.project_compact_projection(
        compact,
        brief,
        _health(projection_fresh_until="2026-10-05T14:09:00Z"),
        observation=observation,
        now=NOW,
        fetched_at=FETCHED_AT,
    )

    assert first["data_state"] == "STALE"
    assert first["knowledge_health"]["total"] == 20
    facet = first["source"]["facet_observations"]["knowledge_health"]
    assert facet["state"] == "LIVE"
    assert facet["observed_at"] == "2026-10-05T13:59:45Z"
    assert "knowledge_health" not in first["source"]["partial_facets"]
    assert renewed["source"]["facet_observations"]["knowledge_health"]["observed_at"] == facet["observed_at"]
    assert renewed["source"]["projection_fresh_until"] != first["source"]["projection_fresh_until"]


def test_failed_refresh_preserves_value_but_cannot_present_facet_as_live() -> None:
    payload = panorama_adapter.project_compact_projection(
        _compact_projection(),
        _brief(),
        _health(),
        observation=_observation(status="STALE", error_class="timeout"),
        now=NOW,
        fetched_at=FETCHED_AT,
    )

    facet = payload["source"]["facet_observations"]["knowledge_health"]
    assert payload["knowledge_health"]["total"] == 20
    assert facet["state"] == "PARTIAL"
    assert facet["error_class"] == "timeout"
    assert "knowledge_health" in payload["source"]["partial_facets"]


def test_failed_refresh_last_good_expires_independently_of_projection_lease() -> None:
    observation = _observation(
        status="STALE",
        observed_at="2026-10-05T13:54:00Z",
        error_class="timeout",
    )

    payload = panorama_adapter.project_compact_projection(
        _compact_projection(), _brief(), _health(), observation=observation,
        now=NOW, fetched_at=FETCHED_AT,
    )

    facet = payload["source"]["facet_observations"]["knowledge_health"]
    assert facet["state"] == "STALE"
    assert facet["observation_status"] == "STALE"
    assert "knowledge_health" in payload["source"]["partial_facets"]
    assert "knowledge_health" not in payload


def test_digest_mismatch_remains_unknown_without_exposing_value() -> None:
    observation = _observation()
    facet = observation["facets"]["knowledge_health"]
    facet["source_digest"] = "0" * 64
    facet["provenance"]["source_digest"] = "0" * 64

    payload = panorama_adapter.project_compact_projection(
        _compact_projection(), _brief(), _health(), observation=observation,
        now=NOW, fetched_at=FETCHED_AT,
    )

    observed = payload["source"]["facet_observations"]["knowledge_health"]
    assert observed["state"] == "UNKNOWN"
    assert observed["observation_status"] == "UNKNOWN"
    assert observed["source_digest"] is None
    assert observed["value"] is None
    assert observed["observed_at"] is None
    assert observed["last_success_at"] is None
    assert "knowledge_health" not in payload
    assert "knowledge_health" in payload["source"]["partial_facets"]


def test_launchd_compact_observation_requires_matching_registry_digest() -> None:
    payload = panorama_adapter.project_compact_projection(
        _compact_projection(), _brief(), _health(), observation=_launchd_observation(),
        now=NOW, fetched_at=FETCHED_AT,
    )
    facet = payload["source"]["facet_observations"]["launchd_health"]
    assert facet["state"] == "LIVE"
    assert facet["provenance"]["registry_sha256"] == "c" * 64
    assert payload["launchd_health"]["jobs"][0]["command_result_class"] == "loaded"

    observation = _launchd_observation()
    observation["facets"]["launchd_health"]["provenance"]["registry_sha256"] = "d" * 64
    rejected = panorama_adapter.project_compact_projection(
        _compact_projection(), _brief(), _health(), observation=observation,
        now=NOW, fetched_at=FETCHED_AT,
    )["source"]["facet_observations"]["launchd_health"]
    assert rejected["state"] == "UNKNOWN"
    assert rejected["observed_at"] is None
    assert rejected["last_success_at"] is None
    assert rejected["value"] is None


def test_future_observation_is_ignored_instead_of_becoming_live() -> None:
    payload = panorama_adapter.project_compact_projection(
        _compact_projection(),
        _brief(),
        _health(),
        observation=_observation(observed_at="2026-10-05T14:01:00Z"),
        now=NOW,
        fetched_at=FETCHED_AT,
    )

    assert "facet_observations" not in payload["source"]
    assert "knowledge_health" not in payload


def test_direct_observation_requires_exact_value_and_collector_identity() -> None:
    for observation in (
        _observation(source_digest="0" * 64),
        _observation(source_ref="untrusted-collector"),
        _observation(status="OBSERVED"),
    ):
        if observation["facets"]["knowledge_health"]["source_digest"] == panorama_adapter._canonical_digest(
            observation["facets"]["knowledge_health"]["value"]
        ) and observation["facets"]["knowledge_health"]["provenance"]["source_ref"] == "bin/panorama/panorama-collect.py::collect_knowledge_health":
            observation["facets"]["knowledge_health"]["provenance"]["collector_sha256"] = "0" * 64
        payload = panorama_adapter.project_compact_projection(
            _compact_projection(), _brief(), _health(), observation=observation, now=NOW, fetched_at=FETCHED_AT
        )
        assert "knowledge_health" not in payload
        assert "knowledge_health" in payload["source"]["partial_facets"]


def test_panorama_route_returns_adapter_payload(monkeypatch) -> None:
    observed = {"generated_at": "", "data_state": "UNKNOWN", "gates": [], "source": {"status": "UNKNOWN"}}

    async def fake_projection() -> dict[str, Any]:
        return observed

    monkeypatch.setattr(dashboard_routes, "fetch_panorama_projection", fake_projection)
    app = FastAPI()
    app.include_router(dashboard_routes.router)

    response = TestClient(app).get("/api/governance/panorama")

    assert response.status_code == 200
    assert response.json() == observed
