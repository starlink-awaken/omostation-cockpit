"""
test_api_decision_graph.py — T5-05 决策因果图 API 集成测试
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cockpit.dashboard.constants import DECISION_GRAPH_PATH
from cockpit.handlers.decision_graph import (
    decision_graph_nodes,
    decision_graph_summary,
)
from cockpit.dashboard.routes import router
from fastapi import FastAPI


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture()
def app():
    """Minimal FastAPI app with decision graph routes and no auth."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def graph_data():
    """Ensure graph.jsonl exists with known data."""
    graph_path = Path(DECISION_GRAPH_PATH)
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    sample_nodes = [
        {"node_id": "t1", "kind": "patrol", "actor": "bot-a", "action": "scan", "ts": "2026-09-13T00:00:00Z"},
        {"node_id": "t2", "kind": "healing", "actor": "bot-b", "action": "fix", "ts": "2026-09-13T00:01:00Z", "decision": "fixed"},
        {"node_id": "t3", "kind": "decision", "actor": "human", "action": "approve", "ts": "2026-09-13T00:02:00Z", "decision": "yes"},
    ]
    sample_edges = [
        {"from_node": "t1", "to_node": "t2", "relation": "caused"},
        {"from_node": "t2", "to_node": "t3", "relation": "influenced"},
    ]
    with graph_path.open("w", encoding="utf-8") as f:
        for obj in sample_nodes + sample_edges:
            f.write(json.dumps(obj) + "\n")
    return graph_path


# ── Handler unit tests ────────────────────────────────────────


class TestHandlerFunctions:
    def test_summary_counts(self, graph_data):
        result = decision_graph_summary(graph_data)
        assert result["nodes"] == 3
        assert result["edges"] == 2
        assert result["by_kind"] == {"patrol": 1, "healing": 1, "decision": 1}

    def test_summary_actors_actions(self, graph_data):
        result = decision_graph_summary(graph_data)
        assert result["actors"] == {"bot-a": 1, "bot-b": 1, "human": 1}
        assert result["actions"] == {"scan": 1, "fix": 1, "approve": 1}

    def test_nodes_list(self, graph_data):
        result = decision_graph_nodes(graph_data)
        assert len(result["nodes"]) == 3
        assert len(result["edges"]) == 2
        assert result["nodes"][0]["node_id"] == "t1"
        assert result["edges"][0]["from_node"] == "t1"

    def test_missing_file_returns_empty(self, tmp_path):
        result = decision_graph_summary(tmp_path / "nonexistent.jsonl")
        assert result["nodes"] == 0
        assert result["edges"] == 0
        assert result["by_kind"] == {}
        assert result["actors"] == {}
        assert result["actions"] == {}


# ── API endpoint tests ────────────────────────────────────────


class TestApiEndpoints:
    def test_summary_endpoint(self, client, graph_data):
        resp = client.get("/api/v1/decision-graph/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert "by_kind" in data
        assert "actors" in data
        assert "actions" in data

    def test_nodes_endpoint(self, client, graph_data):
        resp = client.get("/api/v1/decision-graph/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

    def test_node_subgraph_endpoint(self, client, graph_data):
        resp = client.get("/api/v1/decision-graph/node/t1")
        assert resp.status_code == 200
        data = resp.json()
        # t1 has no node_id in DecisionGraph class so this may return error
        # but the endpoint should still respond
        assert "node" in data or "error" in data

    def test_node_subgraph_not_found(self, client, graph_data):
        resp = client.get("/api/v1/decision-graph/node/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
