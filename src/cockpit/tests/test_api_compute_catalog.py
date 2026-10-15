"""The public compute catalog reads registered full local IDs from one local gateway GET."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cockpit.web import api_compute

FULL_ID = "ENG-LMSTUDIO-MACBOOKPRO/google/gemma-4-12b-qat"
SECOND_ID = "ENG-OMLX-NODE/org/collection/model"


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(api_compute.router)
    monkeypatch.setattr(api_compute, "get_workspace_root", lambda: None)
    monkeypatch.setattr(api_compute, "_strict_gateway_key", lambda deadline: "fixture-gateway")
    return TestClient(app)


def serve(monkeypatch, *, status=200, body=None, delay_headers=0.0, delay_body=0.0):
    observed = []
    raw = json.dumps(body if body is not None else {"data": [{"id": FULL_ID}]}).encode()

    class Provider(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append((self.path, self.headers.get("Authorization")))
            if delay_headers:
                time.sleep(delay_headers)
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if delay_body:
                    time.sleep(delay_body)
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(api_compute, "_strict_gateway_url", lambda: ("127.0.0.1", server.server_port))
    return server, thread, observed


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_catalog_uses_one_gateway_get_and_keeps_exact_registered_ids(client, monkeypatch):
    server, thread, observed = serve(
        monkeypatch,
        body={
            "data": [
                {"id": FULL_ID},
                {"id": FULL_ID},
                {"id": SECOND_ID},
                {"id": "coding"},
                {"id": "openai/gpt-4o"},
                {"id": "ENG-OMLX-NODE//empty"},
            ]
        },
    )
    try:
        response = client.get("/api/governance/compute/models")
    finally:
        stop(server, thread)

    assert response.status_code == 200, response.text
    data = response.json()
    assert [m["model_id"] for m in data["models"]] == [FULL_ID, SECOND_ID]
    assert data["total"] == 2
    assert data["status"] == "success"
    assert data["source"] == "aetherforge_gateway"
    assert data["residency"] == "unknown"
    assert data["loaded_by_node"] == {}
    assert data["observed_at"]
    assert observed == [("/v1/models", "Bearer fixture-gateway")]


@pytest.mark.parametrize(
    "status,body",
    [
        (307, {"data": [{"id": FULL_ID}]}),
        (308, {"data": [{"id": FULL_ID}]}),
        (401, {"error": "secret-fixture"}),
        (200, {"data": "bad"}),
        (200, {"data": [{"id": "coding"}]}),
    ],
)
def test_catalog_fails_closed_without_redirect_or_empty_green(client, monkeypatch, status, body):
    server, thread, observed = serve(monkeypatch, status=status, body=body)
    try:
        response = client.get("/api/governance/compute/models")
    finally:
        stop(server, thread)
    assert response.status_code != 200
    assert len(observed) == 1
    assert "secret-fixture" not in response.text


def test_catalog_requires_server_key_before_http(client, monkeypatch):
    server, thread, observed = serve(monkeypatch)
    monkeypatch.setattr(api_compute, "_strict_gateway_key", lambda deadline: None)
    try:
        response = client.get("/api/governance/compute/models")
    finally:
        stop(server, thread)
    assert response.status_code == 503
    assert observed == []


@pytest.mark.parametrize("delay_headers,delay_body", [(0.7, 0.0), (0.0, 0.7)])
def test_catalog_has_cumulative_deadline(client, monkeypatch, delay_headers, delay_body):
    monkeypatch.setattr(api_compute, "_CATALOG_DEADLINE", 0.2, raising=False)
    server, thread, observed = serve(monkeypatch, delay_headers=delay_headers, delay_body=delay_body)
    begin = time.monotonic()
    try:
        response = client.get("/api/governance/compute/models")
        elapsed = time.monotonic() - begin
    finally:
        stop(server, thread)
    assert response.status_code == 503
    assert elapsed < 0.65
    assert len(observed) == 1


def test_catalog_rejects_oversized_body(client, monkeypatch):
    server, thread, observed = serve(monkeypatch, body={"data": [{"id": FULL_ID, "padding": "x" * (1024 * 1024)}]})
    try:
        response = client.get("/api/governance/compute/models")
    finally:
        stop(server, thread)
    assert response.status_code != 200
    assert len(observed) == 1
