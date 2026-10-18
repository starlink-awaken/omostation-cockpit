#!/usr/bin/env python3
"""projects/cockpit/tests/test_api_notification_and_nodes.py — 测试通知中枢与动态节点端点."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpit.web.api_reflection import router


def create_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_resident_notify_history():
    client = create_test_client()
    resp = client.get("/api/resident/notify/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "history" in data
    assert isinstance(data["history"], list)


def test_resident_notify_send():
    client = create_test_client()
    payload = {
        "level": "P2_INFO",
        "title": "测试通知",
        "body": "自动化测试触发的系统通知",
        "force_macos": False,
    }
    resp = client.post("/api/resident/notify/send", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "dispatch" in data


def test_resident_nodes_list():
    client = create_test_client()
    resp = client.get("/api/resident/nodes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "topology" in data
    nodes = data["topology"].get("nodes", [])
    assert len(nodes) >= 1


def test_resident_node_register_and_unregister():
    client = create_test_client()
    # 1. 动态注册一台新节点
    node_payload = {
        "id": "node-test-gpu",
        "name": "Test Linux GPU",
        "host": "127.0.0.1",
        "port": 11434,
        "role": "worker",
        "memory_gb": 32.0,
        "vram_gb": 16.0,
    }
    resp = client.post("/api/resident/nodes/register", json=node_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["node_id"] == "node-test-gpu"

    # 2. 动态下线该节点
    del_resp = client.delete("/api/resident/nodes/node-test-gpu")
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["ok"] is True
    assert del_data["node_id"] == "node-test-gpu"

    # 3. 尝试移除不存在的节点应返回 400
    bad_del = client.delete("/api/resident/nodes/non-existent-node")
    assert bad_del.status_code == 400
