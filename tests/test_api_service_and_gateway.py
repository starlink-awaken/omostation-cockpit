#!/usr/bin/env python3
"""projects/cockpit/tests/test_api_service_and_gateway.py — 测试 LaunchAgent 守护与推断网关端点 (Phase 9)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpit.web.api_reflection import router


def create_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_resident_service_status():
    client = create_test_client()
    resp = client.get("/api/resident/service/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "service" in data
    assert "installed" in data["service"]
    assert "launchd_running" in data["service"]


def test_resident_service_trigger():
    client = create_test_client()
    # 手动触发巡检任务
    resp = client.post("/api/resident/service/trigger", json={"job": "patrol"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["job"] == "patrol"
    assert "result" in data


def test_resident_compute_metrics():
    client = create_test_client()
    resp = client.get("/api/resident/compute/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "metrics" in data


def test_resident_infer_proxy():
    client = create_test_client()
    payload = {
        "tier": "tier1_inspection",
        "prompt": "ping check",
        "timeout": 1.0,
    }
    resp = client.post("/api/resident/infer", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "content" in data
    assert "target_node" in data
    assert "latency_ms" in data
