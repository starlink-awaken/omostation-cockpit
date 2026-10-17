"""Web reflection endpoints — 6 个只读反射端点冒烟测试.

覆盖:
  · GET /api/commands    — 命令目录
  · GET /api/chains      — chain 列表
  · GET /api/chains/{id} — chain 详情
  · GET /api/command-audit/summary — 评分卡汇总
  · GET /api/resident    — 常驻 Agent（可能不可达）
  · GET /api/bcos        — BCOS（可能不可达）
  · GET /api/p74         — P74（可能不可达）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cockpit.dashboard_server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestCommandsEndpoint:
    def test_commands_returns_200(self, client: TestClient):
        resp = client.get("/api/commands")
        assert resp.status_code == 200

    def test_commands_has_list(self, client: TestClient):
        data = client.get("/api/commands").json()
        assert data["available"] is True
        assert isinstance(data["commands"], list)
        assert data["total"] > 0

    def test_commands_have_required_fields(self, client: TestClient):
        data = client.get("/api/commands").json()
        for cmd in data["commands"]:
            assert "name" in cmd
            assert "summary" in cmd
            assert "category" in cmd


class TestChainsEndpoint:
    def test_chains_returns_200(self, client: TestClient):
        resp = client.get("/api/chains")
        assert resp.status_code == 200

    def test_chains_has_list(self, client: TestClient):
        data = client.get("/api/chains").json()
        assert data["available"] is True
        assert isinstance(data["chains"], list)

    def test_chain_detail_404(self, client: TestClient):
        resp = client.get("/api/chains/nonexistent-chain-xyz")
        # Returns 200 with available=False (chain spec not found)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("available") is False


class TestCommandAuditEndpoint:
    def test_audit_summary_returns_200(self, client: TestClient):
        resp = client.get("/api/command-audit/summary")
        assert resp.status_code == 200

    def test_audit_summary_has_dimensions(self, client: TestClient):
        data = client.get("/api/command-audit/summary").json()
        assert data["available"] is True
        assert "dimension_averages" in data
        assert "total_cards" in data


class TestReflectionEndpoints:
    """resident / bcos / p74 — 可能不可达, 但端点应返回 200 + available 标志."""

    def test_resident_returns_200(self, client: TestClient):
        resp = client.get("/api/resident")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data

    def test_bcos_returns_200(self, client: TestClient):
        resp = client.get("/api/bcos")
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data or "available" in data

    def test_p74_returns_200(self, client: TestClient):
        """p74 端点透传 agent-workflow compliance --json — 契约为 ok/p74_solidification,
        旧断言 "available" 是过时契约导致长期误报失败 (2026-09-24 实证修复)。"""
        resp = client.get("/api/p74")
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data


class TestResidentPhase6Endpoints:
    """Phase 6: 现场排障、枚举自愈、踩坑雷达与双机集群端点验证."""

    def test_resident_triage_returns_200(self, client: TestClient):
        payload = {
            "component": "dashboard_projection",
            "status": "stale",
            "error_log": "projection_stale: lease expired at 2026-10-17T08:00:00Z",
            "dry_run": True,
        }
        resp = client.post("/api/resident/triage", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["risk_tier"] in ("R0", "R1")
        assert "suggested_action" in data

    def test_resident_remediate_safe_action(self, client: TestClient):
        payload = {"action_id": "CLEAR_SUBMODULE_CACHE"}
        resp = client.post("/api/resident/remediate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["action_id"] == "CLEAR_SUBMODULE_CACHE"
        assert data["risk_tier"] == "R0"

    def test_resident_remediate_rejects_arbitrary_shell(self, client: TestClient):
        payload = {"action_id": "rm -rf /"}
        resp = client.post("/api/resident/remediate", json=payload)
        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False
        assert "Invalid action_id" in data["error"]

    def test_resident_pitfalls_returns_200(self, client: TestClient):
        resp = client.get("/api/resident/pitfalls")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["total_rules"] > 0
        assert isinstance(data["rules"], list)
        assert data["guard_status"] == "ACTIVE"

    def test_resident_swarm_returns_200(self, client: TestClient):
        resp = client.get("/api/resident/swarm")
        assert resp.status_code == 200
        data = resp.json()
        assert "mbp_flagship" in data
        assert "macmini_sentinel" in data

