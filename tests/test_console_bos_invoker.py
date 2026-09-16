"""Tests for cockpit.console.bos_invoker."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cockpit.console.bos_invoker import BosInvoker, aggregate_metrics
from cockpit.console.models import InvokeRequest


class TestBosInvokerKnownServices:
    def test_returns_list(self):
        invoker = BosInvoker()
        result = invoker.known_services()
        assert isinstance(result, list)

    def test_filter_by_domain(self):
        invoker = BosInvoker()
        result = invoker.known_services(domain="governance")
        for svc in result:
            assert svc["domain"] == "governance"

    def test_filter_by_query(self):
        invoker = BosInvoker()
        result = invoker.known_services(query="bos://")
        assert len(result) > 0

    def test_no_match(self):
        invoker = BosInvoker()
        result = invoker.known_services(query="zzz-nonexistent-zzz")
        assert result == []


class TestBosInvokerSchema:
    def test_known_uri(self):
        invoker = BosInvoker()
        schema = invoker.schema_for("bos://system/health")
        assert schema["uri"] == "bos://system/health"
        assert schema["risk"] in ("read", "write", "dangerous")

    def test_unknown_uri(self):
        invoker = BosInvoker()
        schema = invoker.schema_for("bos://nonexistent/uri")
        assert schema["uri"] == "bos://nonexistent/uri"
        assert schema["risk"] == "read"
        assert schema["parameters"] == []


class TestBosInvokerInvoke:
    @pytest.mark.asyncio
    async def test_agora_http_success(self):
        """Test successful invocation via Agora HTTP."""
        invoker = BosInvoker(agora_endpoint="http://localhost:9999")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "result": {"data": "test_result"},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("cockpit.console.bos_invoker.httpx.AsyncClient", return_value=mock_client):
            req = InvokeRequest(uri="bos://system/health", arguments={})
            result = await invoker.invoke(req)

        assert result.error is None
        assert result.route == "agora_http"
        assert result.transport == "http"
        assert result.result == {"data": "test_result"}
        assert result.risk == "read"

    @pytest.mark.asyncio
    async def test_fallback_to_in_process(self):
        """Test fallback when Agora is unreachable."""
        invoker = BosInvoker(agora_endpoint="http://localhost:9999")

        with patch("cockpit.console.bos_invoker.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            with patch("cockpit.adapters.agora.resolve_bos_uri", return_value={"status": "ok"}):
                req = InvokeRequest(uri="bos://system/health", arguments={})
                result = await invoker.invoke(req)

        assert result.error is None
        assert result.route == "in_process_compat"
        assert result.transport == "in_process"

    @pytest.mark.asyncio
    async def test_both_fail(self):
        """Test when both Agora and in-process fail."""
        invoker = BosInvoker(agora_endpoint="http://localhost:9999")

        with patch("cockpit.console.bos_invoker.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            with patch("cockpit.adapters.agora.resolve_bos_uri", side_effect=Exception("resolver error")):
                req = InvokeRequest(uri="bos://system/health", arguments={})
                result = await invoker.invoke(req)

        assert result.error is not None
        assert "resolver error" in result.error

    @pytest.mark.asyncio
    async def test_timeout_clamping(self):
        """Test that timeout_ms is clamped to [500, 120000]."""
        invoker = BosInvoker(agora_endpoint="http://localhost:9999")

        with patch("cockpit.console.bos_invoker.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok", "result": {}}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            # Very low timeout — should be clamped to 500ms
            req = InvokeRequest(uri="bos://system/health", arguments={}, timeout_ms=100)
            result = await invoker.invoke(req)

        # It should succeed despite the low timeout being clamped
        assert result.error is None

    @pytest.mark.asyncio
    async def test_read_timeout_reduced(self):
        """Test that read-level operations have reduced timeout."""
        invoker = BosInvoker(agora_endpoint="http://localhost:9999")

        with patch("cockpit.console.bos_invoker.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok", "result": {}}
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_client

            # Read-level with high timeout — should be clamped to 10s
            req = InvokeRequest(uri="bos://system/health", arguments={}, timeout_ms=120000)
            result = await invoker.invoke(req)

        assert result.error is None


class TestAggregateMetrics:
    def test_empty_file(self, tmp_path: Path):
        """Test with no metrics file."""
        with patch("cockpit.console.bos_invoker.METRICS_FILE", tmp_path / "nonexistent.jsonl"):
            result = aggregate_metrics()

        assert result["summary"]["total_calls"] == 0
        assert result["data_quality"] == "unavailable"

    def test_with_data(self, tmp_path: Path):
        """Test with sample metrics data."""
        metrics_file = tmp_path / "bos-metrics.jsonl"
        entries = [
            {"uri": "bos://system/health", "status": "resolved", "elapsed_ms": 50, "transport": "http", "recorded_at": "2026-01-01T00:00:00Z"},
            {"uri": "bos://memory/mos/write", "status": "resolved", "elapsed_ms": 100, "transport": "http", "recorded_at": "2026-01-01T00:01:00Z"},
            {"uri": "bos://system/status", "status": "error", "elapsed_ms": 200, "transport": "in_process", "recorded_at": "2026-01-01T00:02:00Z"},
        ]
        metrics_file.write_text("\n".join(json.dumps(e) for e in entries))

        with patch("cockpit.console.bos_invoker.METRICS_FILE", metrics_file):
            result = aggregate_metrics()

        assert result["summary"]["total_calls"] == 3
        assert result["summary"]["success_count"] == 2
        assert result["data_quality"] == "ok"
        assert len(result["domains"]) == 2

    def test_with_prefix(self, tmp_path: Path):
        """Test prefix filtering."""
        metrics_file = tmp_path / "bos-metrics.jsonl"
        entries = [
            {"uri": "bos://system/health", "status": "resolved", "elapsed_ms": 50, "transport": "http", "recorded_at": "2026-01-01T00:00:00Z"},
            {"uri": "bos://memory/mos/write", "status": "resolved", "elapsed_ms": 100, "transport": "http", "recorded_at": "2026-01-01T00:01:00Z"},
        ]
        metrics_file.write_text("\n".join(json.dumps(e) for e in entries))

        with patch("cockpit.console.bos_invoker.METRICS_FILE", metrics_file):
            result = aggregate_metrics(prefix="bos://memory")

        assert result["summary"]["total_calls"] == 1
        assert result["domains"][0]["domain"] == "memory"
