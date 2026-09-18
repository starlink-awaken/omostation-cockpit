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
    assert result["hard_gaps"] == []
    assert {
        "workspace:.omo/debt/gap-items:empty_or_missing_directory",
        "workspace:.omo/debt/gap-registry.yaml:missing",
    } <= set(result["optional_gaps"])
    assert result["hard_gaps"] == []
    assert {
        "workspace:.omo/debt/gap-items:empty_or_missing_directory",
        "workspace:.omo/debt/gap-registry.yaml:missing",
    } <= set(result["optional_gaps"])
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



def test_new_operations_registered():
    """T8-24A: ontology/lineage/context_pack 在 OPERATIONS 白名单中。"""
    from cockpit.observatory.query_engine import OPERATIONS

    assert {'ontology', 'lineage', 'context_pack'} <= set(OPERATIONS)


def test_scene_system_operations_registered():
    """Serena Phase D: scene_status / scene_graph 注册到 OPERATIONS。"""
    from cockpit.observatory.query_engine import OPERATIONS

    assert {'scene_status', 'scene_graph'} <= set(OPERATIONS)
    assert set(OPERATIONS['scene_status']) == {'kind'}
    assert set(OPERATIONS['scene_graph']) == {'root', 'depth'}


def test_scene_system_registration_and_query(tmp_path: Path):
    """_register_scene_system 把 panorama 扩展注册为 entities + edges,
       scene_status/scene_graph 能读取它们。"""
    non_existent = tmp_path / "nope.json"
    service = ObservatoryService(workspace=WORKSPACE_ROOT, snapshot_path=non_existent)
    index = service.get_index()

    # 无 panorama 数据时 entities 不应崩溃 (健壮降级)
    status = service.query("scene_status")
    assert status["data"]["entity_count"] == 0
    graph = service.query("scene_graph", {"root": "scene_system:signal_poller", "depth": "1"})
    assert graph["data"]["scope"] == "projected_scene_system_topology_only"
    assert graph["data"]["root"] == "scene_system:signal_poller"


def test_scene_system_registration_from_panorama(tmp_path: Path):
    """当 panorama data.json 存在时 scene_* entities 被注册。"""
    non_existent = tmp_path / "nope.json"
    service = ObservatoryService(workspace=WORKSPACE_ROOT, snapshot_path=non_existent)
    # 注入模拟 panorama 扩展
    import json as _json
    ext = {
        "scene_cards": {"total": 5, "with_trigger": 2,
                        "lifecycle": {"draft": 1, "supervised": 2, "routine": 2}},
        "signal_poller": {"watermark_entries": 2, "scenes_with_triggers": 2,
                          "last_poll": "2026-09-13T00:00:00Z",
                          "state_keys": ["email"], "available_connectors": []},
        "journey_executions": {"total": 2, "escalated": 1, "succeeded": 1,
                               "failed": 0, "auto_complete_rate": 0.5, "top_escalated": []},
        "remote_hygiene": {"origin_canonical": True, "origin_push_canonical": True,
                           "last_fix_remotes_run": "2026-09-13T00:00:00Z", "submodules_checked": 16},
        "service_keeper": {"services": []},
        "connectors": {"total": 0, "available": [], "wired_to_scenes": [], "unwired_available": []},
        "bos_verifier": {"last_run_ok": True, "last_run_errors": [], "output_tail": []},
    }
    service._cached_snapshot = service._build_dynamic_snapshot()
    service._cached_snapshot.update(ext)
    from cockpit.observatory.query_engine import ObservationIndex
    service._cached_index = ObservationIndex(service._cached_snapshot)

    ids = {e["id"] for e in service._cached_index.entities.values()}
    assert "scene_system:cards" in ids
    assert "scene_system:signal_poller" in ids
    assert "scene_system:journey_executions" in ids
    # 生命周期阶段实体
    stage_ids = {i for i in ids if i.startswith("scene_system:cards:")}
    assert len(stage_ids) == 3
    # 边已注册 (signal_poller → journey_executions 链)
    assert len(service._cached_index.edges) > 0

    status = service.query("scene_status", {"generation": service._cached_index.generation})
    assert status["data"]["entity_count"] >= 3
    assert "signal_poller" in status["data"]["sources"]
    assert "journey_executions" in status["data"]["sources"]
    assert status["data"]["sources"]["signal_poller"]["watermark_entries"] == "2"
    assert status["data"]["sources"]["journey_executions"]["auto_complete_rate"] == "0.5"
    assert any(k.startswith("scene_") for k in status["data"]["available_kinds"])


def _pick_real_entity_id(service) -> str | None:
    """挑一个 trace graph 里真实存在的 BET 实体; 无则返回 None (CI 子模块面差异时 skip)。"""
    index = service.get_index()
    for eid in index.entities:
        if eid.startswith('bet:'):
            return eid
    return None


def test_lineage_operation_traces_subgraph():
    """lineage 对真实 BET 实体返回 subgraph 与 depth 层级。"""
    service = get_observatory_service()
    entity_id = _pick_real_entity_id(service)
    if entity_id is None:
        pytest.skip('trace graph has no bet: entities in this checkout')
    result = service.query('lineage', {'id': entity_id})
    data = result.get('data', {})
    assert data.get('found') is True
    sub = data.get('subgraph', {})
    assert isinstance(sub.get('nodes'), list) and len(sub['nodes']) > 0
    assert isinstance(data.get('lineage_by_depth'), dict)


def test_lineage_missing_entity_is_truthful():
    """不存在的实体返回 found=False 而非异常。"""
    service = get_observatory_service()
    result = service.query('lineage', {'id': 'no-such-entity-xyz'})
    assert result.get('data', {}).get('found') is False


def test_ontology_operation_exports_schema():
    """ontology 返回 schema 导出 + axioms_live 注入。"""
    service = get_observatory_service()
    result = service.query('ontology', {})
    data = result.get('data', {})
    assert isinstance(data, dict)
    assert 'axioms_live' in data


def test_context_pack_operation_synthesizes():
    """context_pack 对真实实体产出 markdown pack 与 related_knowledge。"""
    service = get_observatory_service()
    entity_id = _pick_real_entity_id(service)
    if entity_id is None:
        pytest.skip('trace graph has no bet: entities in this checkout')
    result = service.query('context_pack', {'id': entity_id})
    data = result.get('data', {})
    assert data.get('found') is True
    assert len(data.get('markdown_pack') or '') > 0


def test_fidelity_with_43191_snapshot_ops():
    """与 43191 live snapshot 的语义对账 (跳过时间戳字段)。

    43191 不在线时跳过 — 保真度对账只在 live 服务可用时有意义。
    """
    import urllib.request
    try:
        with urllib.request.urlopen('http://127.0.0.1:43191/api/v1/summary', timeout=5) as resp:
            zx = json.loads(resp.read())
    except Exception:
        pytest.skip('43191 observatory not running')
    service = get_observatory_service()
    mine = service.query('summary', {})
    norm = lambda o: (  # noqa: E731
        {k: norm(v) for k, v in o.items() if k not in ('generated_at', 'last_attempt_at', 'freshness', 'observed_at', 'age_seconds')}
        if isinstance(o, dict) else
        [norm(x) for x in o] if isinstance(o, list) else o
    )
    assert json.dumps(norm(mine.get('data')), sort_keys=True) == json.dumps(norm(zx.get('data')), sort_keys=True)


def test_lineage_depth_keys_match_43191_contract():
    """43191 兼容: HTTP 序列化后 lineage_by_depth 键为 str (JSON 对象键)。

    实体不在 trace graph (CI checkout 子模块面差异) 时 found=False 且无
    lineage_by_depth 键 — 跳过键型断言。
    """
    service = get_observatory_service()
    entity_id = _pick_real_entity_id(service)
    if entity_id is None:
        pytest.skip('trace graph has no bet: entities in this checkout')
    result = service.query('lineage', {'id': entity_id})
    data = result.get('data', {})
    lbd = data.get('lineage_by_depth')
    if lbd is None:
        assert data.get('found') is False
        pytest.skip('entity not in trace graph in this checkout')
    assert all(isinstance(k, int) for k in lbd.keys())
    # HTTP 层 (envelope) 序列化后与 43191 同构: str 键
    serialized = json.loads(json.dumps(result))
    s_lbd = serialized['data']['lineage_by_depth']
    assert all(isinstance(k, str) for k in s_lbd.keys())
