"""Tests for cockpit mesh routing and smart gateway integration."""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

import pytest

from cockpit.commands import mesh as mesh_mod


def test_mesh_router_url_default_and_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MOF_MESH_PORT", raising=False)
    assert mesh_mod._mesh_router_url() == "http://127.0.0.1:18080"

    monkeypatch.setenv("MOF_MESH_PORT", "19090")
    assert mesh_mod._mesh_router_url() == "http://127.0.0.1:19090"


def test_cmd_mesh_status_primary_success(monkeypatch: pytest.MonkeyPatch):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"status": "healthy"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    def mock_urlopen(url: str, timeout: float = 5.0):
        if url == "http://127.0.0.1:18080/health":
            return mock_resp
        raise ConnectionRefusedError(f"unexpected url: {url}")

    monkeypatch.delenv("MOF_MESH_PORT", raising=False)
    monkeypatch.setattr(mesh_mod, "_urlopen_safe", mock_urlopen)

    args = argparse.Namespace(mesh_command="status")
    rc = mesh_mod.cmd_mesh(args)
    assert rc == 0


def test_cmd_mesh_status_fallback_success(monkeypatch: pytest.MonkeyPatch):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"status": "ok", "service": "aetherforge"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    def mock_urlopen(url: str, timeout: float = 5.0):
        if url == "http://127.0.0.1:18080/health":
            raise ConnectionRefusedError("primary down")
        if url == "http://127.0.0.1:4000/health":
            return mock_resp
        raise ConnectionRefusedError(f"unexpected url: {url}")

    monkeypatch.delenv("MOF_MESH_PORT", raising=False)
    monkeypatch.setattr(mesh_mod, "_urlopen_safe", mock_urlopen)

    args = argparse.Namespace(mesh_command="status")
    rc = mesh_mod.cmd_mesh(args)
    assert rc == 0


def test_cmd_mesh_status_both_fail(monkeypatch: pytest.MonkeyPatch):
    def mock_urlopen(url: str, timeout: float = 5.0):
        raise ConnectionRefusedError("down")

    monkeypatch.delenv("MOF_MESH_PORT", raising=False)
    monkeypatch.setattr(mesh_mod, "_urlopen_safe", mock_urlopen)

    args = argparse.Namespace(mesh_command="status")
    rc = mesh_mod.cmd_mesh(args)
    assert rc == 1


def test_cmd_mesh_nodes_primary_success(monkeypatch: pytest.MonkeyPatch):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"nodes": ["node1", "node2"]}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    def mock_urlopen(url: str, timeout: float = 5.0):
        if url.endswith("/nodes"):
            return mock_resp
        raise ConnectionRefusedError(f"unexpected url: {url}")

    monkeypatch.delenv("MOF_MESH_PORT", raising=False)
    monkeypatch.setattr(mesh_mod, "_urlopen_safe", mock_urlopen)

    args = argparse.Namespace(mesh_command="nodes")
    rc = mesh_mod.cmd_mesh(args)
    assert rc == 0


def test_cmd_mesh_nodes_models_fallback_success(monkeypatch: pytest.MonkeyPatch):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"object": "list", "data": [{"id": "model1"}]}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    def mock_urlopen(url: str, timeout: float = 5.0):
        if url.endswith("/nodes"):
            raise ConnectionRefusedError("404 not found")
        if url.endswith("/v1/models"):
            return mock_resp
        raise ConnectionRefusedError(f"unexpected url: {url}")

    monkeypatch.delenv("MOF_MESH_PORT", raising=False)
    monkeypatch.setattr(mesh_mod, "_urlopen_safe", mock_urlopen)

    args = argparse.Namespace(mesh_command="nodes")
    rc = mesh_mod.cmd_mesh(args)
    assert rc == 0


def test_cmd_mesh_nodes_all_fail(monkeypatch: pytest.MonkeyPatch):
    def mock_urlopen(url: str, timeout: float = 5.0):
        raise ConnectionRefusedError("all down")

    monkeypatch.delenv("MOF_MESH_PORT", raising=False)
    monkeypatch.setattr(mesh_mod, "_urlopen_safe", mock_urlopen)

    args = argparse.Namespace(mesh_command="nodes")
    rc = mesh_mod.cmd_mesh(args)
    assert rc == 1


def test_cmd_mesh_serve_prints_guidance(capsys: pytest.CaptureFixture[str]):
    args = argparse.Namespace(mesh_command="serve")
    rc = mesh_mod.cmd_mesh(args)
    assert rc in (0, 1)
    captured = capsys.readouterr()
    assert "com.user.omlx-smart-gateway" in captured.out or "com.user.omlx-smart-gateway" in captured.err
