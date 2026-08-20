"""Truth-contract tests for the Cockpit B.D.S.K. BOS client."""

from __future__ import annotations

import inspect
import sys

from cockpit import cli
from cockpit.commands import bdsk_engine
from cockpit.commands.bdsk_engine import DynamicBDSKAdjudicator


def _proved_persona_result():
    return {
        "status": "ok",
        "result": {
            "status": "ok",
            "proof_state": "proven",
            "topic_digest": "sha256:abc123",
            "compute_uri": "bos://compute/aetherforge/infer",
            "verdict": "REVIEW_REQUIRED",
            "risk_score": 38,
            "recommendation": "Human review is required.",
            "board_reviews": {
                role: {"opinion": f"{role} evidence"}
                for role in ("builder", "devil", "sage", "keeper")
            },
        },
    }


def test_bdsk_client_calls_only_persona_bos_uri(monkeypatch):
    calls = []

    async def fake_resolve(uri, **kwargs):
        calls.append((uri, kwargs))
        return _proved_persona_result()

    monkeypatch.setattr(bdsk_engine, "_resolve_bos_uri", fake_resolve)
    result = DynamicBDSKAdjudicator.adjudicate(
        "low-sensitivity architecture review", context="bounded context", mode="deep"
    )

    assert calls == [
        (
            "bos://persona/bdsk/evaluate",
            {
                "topic": "low-sensitivity architecture review",
                "context": "bounded context",
                "mode": "deep",
            },
        )
    ]
    assert result["status"] == "ok"
    assert result["proof_state"] == "proven"
    assert result["engine_source"] == "bos_persona_bdsk"
    assert result["topic_digest"] == "sha256:abc123"
    assert "low-sensitivity architecture review" not in str(result)
    assert result["builder"] == "builder evidence"
    assert result["verdict"] == "REVIEW_REQUIRED"


def test_bdsk_client_failure_is_not_proven_without_fallback(monkeypatch):
    async def fake_resolve(_uri, **_kwargs):
        return {
            "status": "ok",
            "result": {
                "status": "error",
                "proof_state": "not_proven",
                "verdict": "NOT_PROVEN",
                "error_code": "compute_unavailable",
                "compute_uri": "bos://compute/aetherforge/infer",
            },
        }

    monkeypatch.setattr(bdsk_engine, "_resolve_bos_uri", fake_resolve)
    result = DynamicBDSKAdjudicator.adjudicate("low-sensitivity smoke")

    assert result == {
        "status": "error",
        "proof_state": "not_proven",
        "verdict": "NOT_PROVEN",
        "error_code": "compute_unavailable",
        "engine_source": "bos_persona_not_proven",
        "compute_uri": "bos://compute/aetherforge/infer",
    }


def test_bdsk_engine_has_no_direct_ollama_or_rules_success_fallback():
    source = inspect.getsource(bdsk_engine)
    assert "11434" not in source
    assert "/api/generate" not in source
    assert "aetherforge_fallback_domain_rules" not in source
    assert "DomainParser" not in source


def test_bdsk_cli_returns_nonzero_for_not_proven(monkeypatch, capsys):
    monkeypatch.setattr(
        DynamicBDSKAdjudicator,
        "adjudicate",
        staticmethod(
            lambda _topic: {
                "status": "error",
                "proof_state": "not_proven",
                "verdict": "NOT_PROVEN",
                "error_code": "compute_unavailable",
                "engine_source": "bos_persona_not_proven",
                "compute_uri": "bos://compute/aetherforge/infer",
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["cockpit", "bdsk", "debate", "low-sensitivity smoke"],
    )

    assert cli.main() == 4
    output = capsys.readouterr().out
    assert "NOT_PROVEN" in output
    assert "bos://persona/bdsk/evaluate" in output
    assert "Local LLM Active" not in output
