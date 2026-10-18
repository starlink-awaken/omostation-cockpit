"""Tests for Phase 11 Multimodal and Voice API Endpoints in Cockpit."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cockpit.web.api_reflection import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_post_resident_chat_with_images(client):
    mock_msg = MagicMock()
    mock_msg.to_dict.return_value = {
        "role": "assistant",
        "content": "已分析上传图片",
        "metadata": {"images": ["/tmp/test.png"], "image_ocr_fallback": True},
    }

    with patch("omo.resident.chat_engine.ResidentChatEngine.chat", return_value=mock_msg):
        response = client.post(
            "/api/resident/chat",
            json={"prompt": "分析图片", "images": ["data:image/png;base64,iVBORw0KGgo="]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["message"]["content"] == "已分析上传图片"


def test_post_resident_voice_speak(client):
    mock_res = {
        "success": True,
        "engine": "say",
        "cleaned_text": "核心研判结论",
        "audio_path": "/tmp/speech.aiff",
        "latency_ms": 15.0,
    }
    with patch("omo.resident.voice_bridge.speak_text", return_value=mock_res):
        response = client.post(
            "/api/resident/voice/speak",
            json={"text": "这是测试文本 ```print(1)```", "voice": "Tingting", "play": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["result"]["engine"] == "say"


def test_post_resident_screen_capture(client):
    fake_img = Path("/tmp/screen_shot.png")
    fake_img.touch()
    with patch("omo.resident.screen_probe.capture_screen", return_value=fake_img):
        response = client.post("/api/resident/screen/capture", json={"fullscreen": False})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "screen_shot.png" in data["image_path"]
