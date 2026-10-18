"""test_api_resident_chat — 验证驾驶舱常驻 Agent 沉浸对话与记忆召回 API 端点 (Phase 10)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from omo.resident.chat_engine import ChatMessage

from cockpit.web.api_reflection import router


def create_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_post_resident_chat_success():
    client = create_test_client()
    mock_msg = ChatMessage(
        role="assistant",
        content="你好夏明星！系统各项只读指标正常。",
        metadata={
            "target_node": "local-mac",
            "tier": "tier2_dialog",
            "latency_ms": 15.2,
            "recalled_memories": [{"id": "pref-1", "directive": "回复优先使用简体中文", "domain": "language"}],
            "recalled_pitfalls": [{"id": "pitfall-1", "title": "工作树隔离", "rule": "主工作区物理只读"}],
            "react_tools_used": [],
        },
    )

    with patch("omo.resident.chat_engine.ResidentChatEngine.chat") as mock_chat:
        mock_chat.return_value = mock_msg
        resp = client.post(
            "/api/resident/chat",
            json={"prompt": "系统状态如何？", "session_id": "default", "tier": "tier2_dialog"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        msg = data["message"]
        assert msg["role"] == "assistant"
        assert "指标正常" in msg["content"]
        assert msg["metadata"]["target_node"] == "local-mac"
        assert len(msg["metadata"]["recalled_memories"]) == 1
        assert len(msg["metadata"]["recalled_pitfalls"]) == 1
        mock_chat.assert_called_once()


def test_post_resident_chat_empty_prompt():
    client = create_test_client()
    resp = client.post("/api/resident/chat", json={"prompt": "   "})
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert "prompt is required" in data["error"]


def test_get_resident_chat_history():
    client = create_test_client()
    mock_history = [
        {"role": "user", "content": "你好", "timestamp": "2026-10-19T00:00:00Z", "metadata": {}},
        {
            "role": "assistant",
            "content": "你好！",
            "timestamp": "2026-10-19T00:00:01Z",
            "metadata": {"recalled_memories": [], "recalled_pitfalls": []},
        },
    ]

    with patch("omo.resident.chat_engine.ResidentChatEngine.get_history") as mock_get_hist:
        mock_get_hist.return_value = mock_history
        resp = client.get("/api/resident/chat/history?session_id=default&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["session_id"] == "default"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        mock_get_hist.assert_called_once_with(session_id="default", limit=10)


def test_delete_resident_chat_history():
    client = create_test_client()
    with patch("omo.resident.chat_engine.ResidentChatEngine.clear_history") as mock_clear:
        mock_clear.return_value = True
        resp = client.delete("/api/resident/chat/history?session_id=default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["session_id"] == "default"
        assert data["cleared"] is True
        mock_clear.assert_called_once_with(session_id="default")
