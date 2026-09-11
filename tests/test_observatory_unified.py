"""Tests for Cockpit Observatory unified data plane (BET-Y1Q4-T8-24A)."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from cockpit.compat import WORKSPACE_ROOT
from cockpit.observatory.catalog_sources import collect_catalog
from cockpit.observatory.strategy_sources import collect_strategy_sources
from cockpit.observatory.service import ObservatoryService, get_observatory_service
from cockpit.observatory.query_engine import QueryError
from cockpit.dashboard_server import app


def test_collect_catalog_smoke():
    """Verify collect_catalog returns structured read-only metadata."""
    result = collect_catalog(WORKSPACE_ROOT)
    assert isinstance(result, dict)
    assert result.get("schema") == "dashboard-catalog/v1"
    assert "projects" in result
    assert "layers" in result
    assert "bos_services" in result
    assert "capabilities" in result
    assert "mof" in result
    assert isinstance(result["projects"], list)
    assert len(result["projects"]) > 0


def test_collect_strategy_sources_smoke():
    """Verify collect_strategy_sources returns strategic ledger metadata."""
    result = collect_strategy_sources(workspace=WORKSPACE_ROOT)
    assert isinstance(result, dict)
    assert result.get("schema") == "zhixing-strategy-sources/v1"
    assert "records" in result
    assert "documents" in result


def test_observatory_service_dynamic_snapshot(tmp_path: Path):
    """Verify ObservatoryService constructs a dynamic snapshot with generation_id."""
    # Use empty snapshot path to trigger dynamic builder
    non_existent = tmp_path / "does_not_exist.json"
    service = ObservatoryService(workspace=WORKSPACE_ROOT, snapshot_path=non_existent)
    snapshot = service.get_snapshot()
    assert isinstance(snapshot, dict)
    assert snapshot.get("generation_id") is not None
    assert len(snapshot["generation_id"]) >= 10
    assert "catalog" in snapshot
    assert "strategic" in snapshot

    # Index should be available
    index = service.get_index()
    assert index.generation == snapshot["generation_id"]

    # Manifest query
    manifest = service.query("manifest")
    assert manifest.get("generation_id") == snapshot["generation_id"]
    assert "data" in manifest
    assert "operations" in manifest["data"]
    assert "summary" in manifest["data"]["operations"]

    # Summary query
    summary = service.query("summary")
    assert summary.get("generation_id") == snapshot["generation_id"]
    assert "data" in summary
    assert "entities_known" in summary["data"]
    assert "edges_known" in summary["data"]


def test_observatory_service_generation_lock(tmp_path: Path):
    """Verify generation mismatch raises QueryError(409)."""
    non_existent = tmp_path / "does_not_exist.json"
    service = ObservatoryService(workspace=WORKSPACE_ROOT, snapshot_path=non_existent)
    snapshot = service.get_snapshot()
    current_gen = snapshot["generation_id"]

    # Match passes
    service.query("manifest", {"generation": current_gen})

    # Mismatch fails with 409
    with pytest.raises(QueryError) as exc_info:
        service.query("manifest", {"generation": "mismatched-generation-id"})
    assert exc_info.value.status == 409


def test_observatory_api_routes():
    """Verify FastAPI observatory routes work end-to-end via TestClient."""
    client = TestClient(app)

    # 1. Snapshot
    res = client.get("/api/v1/observatory/snapshot")
    assert res.status_code == 200
    data = res.json()
    assert "generation_id" in data
    gen_id = data["generation_id"]

    # 2. Snapshot with matching generation
    res_gen = client.get(f"/api/v1/observatory/snapshot?generation={gen_id}")
    assert res_gen.status_code == 200

    # 3. Snapshot with mismatched generation -> 409
    res_mismatch = client.get("/api/v1/observatory/snapshot?generation=bogus_gen_12345")
    assert res_mismatch.status_code == 409

    # 4. Catalogs
    res_cat = client.get("/api/v1/observatory/catalogs")
    assert res_cat.status_code == 200
    assert "projects" in res_cat.json()

    # 5. Strategy
    res_strat = client.get("/api/v1/observatory/strategy")
    assert res_strat.status_code == 200
    assert "trace" in res_strat.json()

    # 6. Query GET
    res_query = client.get("/api/v1/observatory/query?operation=summary")
    assert res_query.status_code == 200
    assert "data" in res_query.json()
    assert "entities_known" in res_query.json()["data"]

    # 7. Query POST
    res_post = client.post("/api/v1/observatory/query", json={"operation": "manifest"})
    assert res_post.status_code == 200
    assert "data" in res_post.json()
    assert "operations" in res_post.json()["data"]


def test_observatory_stream_sse():
    """Verify SSE streaming endpoint connects and returns event stream."""
    client = TestClient(app)
    with client.stream("GET", "/api/v1/observatory/stream?once=true") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        content = response.read().decode("utf-8")
        assert "event: connected" in content
        assert "generation_id" in content

