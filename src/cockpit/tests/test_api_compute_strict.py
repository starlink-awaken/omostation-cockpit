"""The dedicated strict compute operation must use one exact local provider call."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpit.web import api_compute, auth

MODEL = "ENG-LMSTUDIO-LOCAL/qwen-test"


@pytest.fixture
def strict_client(monkeypatch):
    app = FastAPI()
    app.include_router(api_compute.router)
    monkeypatch.setattr(
        auth,
        "_cached_keys",
        lambda: {
            "fixture-operator": auth.ApiKeyInfo(name="operator", scopes=["compute-generate"]),
            "fixture-viewer": auth.ApiKeyInfo(name="viewer", scopes=["read"]),
        },
    )
    monkeypatch.setattr(api_compute, "_strict_gateway_key", lambda deadline: "fixture-gateway", raising=False)
    return TestClient(app)


def test_strict_route_uses_one_exact_http_request(strict_client, monkeypatch):
    observed = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            observed.append((self.path, body, self.headers.get("Authorization")))
            payload = json.dumps({
                "id": "trace-fixture-1",
                "model": MODEL,
                "choices": [{"message": {"content": "四十二"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("LLM_GATEWAY_URL", f"http://127.0.0.1:{server.server_port}")
        response = strict_client.post(
            "/api/governance/compute/generate-strict",
            headers={"X-Api-Key": "fixture-operator"},
            json={"model": MODEL, "prompt": "6×7?", "max_tokens": 32, "timeout": 2, "strict_model": True},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 200, response.text
    assert len(observed) == 1
    path, body, authorization = observed[0]
    assert path == "/v1/chat/completions"
    assert body["model"] == MODEL
    assert body["strict_model"] is True
    assert body["stream"] is False
    assert 0 < body["timeout"] <= 2
    assert body["max_tokens"] == 32
    assert authorization == "Bearer fixture-gateway"
    assert response.json()["model"] == MODEL
    assert response.json()["trace_id"] == "trace-fixture-1"


@pytest.mark.parametrize("headers,expected", [
    ({}, 401),
    ({"X-Api-Key": "fixture-viewer"}, 403),
])
def test_strict_route_requires_configured_operator(strict_client, monkeypatch, headers, expected):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://127.0.0.1:9")
    response = strict_client.post(
        "/api/governance/compute/generate-strict", headers=headers,
        json={"model": MODEL, "prompt": "hello", "max_tokens": 8, "timeout": 1, "strict_model": True},
    )
    assert response.status_code == expected


@pytest.mark.parametrize("model", ["coder", "ENG-LMSTUDIO-LOCAL/bad model", "ENG-CLOUD-X/model"])
def test_strict_route_rejects_alias_whitespace_and_cloud(strict_client, monkeypatch, model):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://127.0.0.1:9")
    response = strict_client.post(
        "/api/governance/compute/generate-strict",
        headers={"X-Api-Key": "fixture-operator"},
        json={"model": model, "prompt": "hello", "max_tokens": 8, "timeout": 1, "strict_model": True},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_strict_request"


@pytest.mark.parametrize("change", [
    {"max_tokens": True}, {"max_tokens": 0}, {"max_tokens": 513},
    {"timeout": 0}, {"timeout": 31}, {"timeout": "2"},
    {"strict_model": False}, {"prompt": ""},
])
def test_strict_route_rejects_bad_bounds_before_provider(strict_client, monkeypatch, change):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://127.0.0.1:9")
    body = {"model": MODEL, "prompt": "hello", "max_tokens": 8, "timeout": 1, "strict_model": True}
    body.update(change)
    response = strict_client.post(
        "/api/governance/compute/generate-strict",
        headers={"X-Api-Key": "fixture-operator"}, json=body,
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_strict_request"


def test_strict_route_rejects_unknown_fields_and_nonloopback_target(strict_client, monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://127.0.0.1:9")
    body = {"model": MODEL, "prompt": "hello", "max_tokens": 8, "timeout": 1, "strict_model": True}
    extra = strict_client.post(
        "/api/governance/compute/generate-strict",
        headers={"X-Api-Key": "fixture-operator"}, json={**body, "routing_mode": "cloud"},
    )
    assert extra.status_code == 422
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://example.com:4000")
    remote = strict_client.post(
        "/api/governance/compute/generate-strict",
        headers={"X-Api-Key": "fixture-operator"}, json=body,
    )
    assert remote.status_code == 503
    assert remote.json()["error"] == "strict_gateway_unconfigured"


def test_strict_route_does_not_follow_provider_redirect(strict_client, monkeypatch):
    calls = []

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            self.send_response(307)
            self.send_header("Location", "/v1/chat/completions")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("LLM_GATEWAY_URL", f"http://127.0.0.1:{server.server_port}")
        response = strict_client.post(
            "/api/governance/compute/generate-strict",
            headers={"X-Api-Key": "fixture-operator"},
            json={"model": MODEL, "prompt": "hello", "max_tokens": 8, "timeout": 1, "strict_model": True},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert response.status_code == 502
    assert calls == ["/v1/chat/completions"]


def test_timeout_keeps_slot_until_slow_http_worker_exits(strict_client, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class Slow(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "5")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            entered.set()
            release.wait(timeout=3)
            try:
                self.wfile.write(b"xxxx")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LLM_GATEWAY_URL", f"http://127.0.0.1:{server.server_port}")
    body = {"model": MODEL, "prompt": "hello", "max_tokens": 8, "timeout": 0.2, "strict_model": True}
    async def exercise():
        transport = httpx.ASGITransport(app=strict_client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            try:
                first = asyncio.create_task(client.post(
                    "/api/governance/compute/generate-strict",
                    headers={"X-Api-Key": "fixture-operator"}, json=body,
                ))
                assert await asyncio.to_thread(entered.wait, 2)
                response = await asyncio.wait_for(first, timeout=1.8)
                assert response.status_code == 504
                second = await client.post(
                    "/api/governance/compute/generate-strict",
                    headers={"X-Api-Key": "fixture-operator"}, json=body,
                )
                assert second.status_code == 429
                assert second.json()["error"] == "strict_inflight"
                assert calls == ["/v1/chat/completions"]
            finally:
                release.set()

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_slow_drip_has_total_deadline_and_worker_exits(strict_client, monkeypatch):
    calls = []

    class SlowDrip(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            for _ in range(50):
                try:
                    self.wfile.write(b"x")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(0.06)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowDrip)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LLM_GATEWAY_URL", f"http://127.0.0.1:{server.server_port}")

    async def exercise():
        transport = httpx.ASGITransport(app=strict_client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await asyncio.wait_for(client.post(
                "/api/governance/compute/generate-strict",
                headers={"X-Api-Key": "fixture-operator"},
                json={"model": MODEL, "prompt": "hello", "max_tokens": 8,
                      "timeout": 0.2, "strict_model": True},
            ), timeout=1.8)
            assert response.status_code == 504
            assert response.json()["provider_outcome"] == "unknown"
            assert calls == ["/v1/chat/completions"]
            assert await asyncio.to_thread(api_compute._STRICT_SLOT.acquire, True, 3)
            api_compute._STRICT_SLOT.release()

    try:
        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_slow_status_headers_cannot_hold_worker_past_deadline(strict_client, monkeypatch):
    calls = []

    class SlowHeaders(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            self.rfile.read(int(self.headers["Content-Length"]))
            for byte in b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n":
                try:
                    self.connection.sendall(bytes([byte]))
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(0.06)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHeaders)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LLM_GATEWAY_URL", f"http://127.0.0.1:{server.server_port}")

    async def exercise():
        transport = httpx.ASGITransport(app=strict_client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await asyncio.wait_for(client.post(
                "/api/governance/compute/generate-strict",
                headers={"X-Api-Key": "fixture-operator"},
                json={"model": MODEL, "prompt": "hello", "max_tokens": 8,
                      "timeout": 0.2, "strict_model": True},
            ), timeout=1.8)
            assert response.status_code == 504
            assert calls == ["/v1/chat/completions"]
            assert await asyncio.to_thread(api_compute._STRICT_SLOT.acquire, True, 3)
            api_compute._STRICT_SLOT.release()

    try:
        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
