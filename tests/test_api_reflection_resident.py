"""test_api_reflection_resident — 验证驾驶舱常驻反射 API 端点 (Phase 7)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpit.web.api_reflection import router


def create_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_resident_pitfalls():
    client = create_test_client()
    resp = client.get("/api/resident/pitfalls")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "rules" in data
    assert len(data["rules"]) > 0
    first_rule = data["rules"][0]
    assert "id" in first_rule
    assert "status" in first_rule


def test_get_resident_swarm():
    client = create_test_client()
    resp = client.get("/api/resident/swarm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    # 向后兼容字段
    assert "mbp_flagship" in data
    assert "macmini_sentinel" in data
    # Phase 7 动态多机拓扑
    assert "nodes" in data or "cluster_summary" in data


def test_post_resident_pitfalls_distill():
    client = create_test_client()
    payload = {
        "error_log": "error: edgesout npm install failed",
        "diff_text": "- npm install\n+ bun install\n",
        "save": False,
    }
    resp = client.post("/api/resident/pitfalls/distill", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["distilled"] is True
    assert "rule" in data
    assert data["rule"]["severity"] == "HIGH"


def test_post_resident_patrol_cycle():
    client = create_test_client()
    with patch("omo.resident.patrol.ResidentPatrolRunner.run_patrol_cycle") as mock_patrol:
        mock_patrol.return_value = {
            "ok": True,
            "health": "healthy",
            "findings": [],
            "remediations_executed": [],
            "escalated_tasks": [],
            "scan_duration_ms": 12.5,
        }
        resp = client.post("/api/resident/patrol", json={"auto_remediate": False})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["health"] == "healthy"


def test_get_resident_patrol_status():
    client = create_test_client()
    with patch("omo.resident.patrol.ResidentPatrolRunner.run_patrol_cycle") as mock_patrol:
        mock_patrol.return_value = {
            "ok": True,
            "health": "healthy",
            "findings": [],
            "remediations_executed": [],
            "escalated_tasks": [],
            "scan_duration_ms": 10.0,
        }
        resp = client.get("/api/resident/patrol")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True


def test_post_resident_remediate_invalid():
    client = create_test_client()
    resp = client.post("/api/resident/remediate", json={"action_id": "DANGEROUS_DROP_DB"})
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert "Invalid action_id" in data["error"]
