"""Tests for cockpit.console.bos_invoker and cockpit.console.risk."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cockpit.console.models import InvokeRequest
from cockpit.console.risk import RiskLevel, classify_risk, confirm_token, require_confirm


# ── Risk Classification Tests ────────────────────────────────


class TestClassifyRisk:
    def test_read_health(self):
        assert classify_risk("bos://system/health") == RiskLevel.READ

    def test_read_status(self):
        assert classify_risk("bos://governance/omo/status") == RiskLevel.READ

    def test_read_list(self):
        assert classify_risk("bos://capability/agent-runtime/list") == RiskLevel.READ

    def test_read_metrics(self):
        assert classify_risk("bos://system/metrics") == RiskLevel.READ

    def test_read_audit(self):
        assert classify_risk("bos://governance/mof/audit") == RiskLevel.READ

    def test_read_evaluate(self):
        assert classify_risk("bos://governance/mof/evaluate") == RiskLevel.READ

    def test_read_resolve(self):
        assert classify_risk("bos://agora/registry/resolve") == RiskLevel.READ

    def test_write_write(self):
        assert classify_risk("bos://memory/mos/write") == RiskLevel.WRITE

    def test_write_put(self):
        assert classify_risk("bos://memory/kos/put") == RiskLevel.WRITE

    def test_write_create(self):
        assert classify_risk("bos://governance/bet/create") == RiskLevel.WRITE

    def test_write_submit(self):
        assert classify_risk("bos://resident/task/submit") == RiskLevel.WRITE

    def test_write_run(self):
        assert classify_risk("bos://ecos/workflow/run") == RiskLevel.WRITE

    def test_write_infer(self):
        assert classify_risk("bos://compute/aetherforge/infer") == RiskLevel.WRITE

    def test_write_compile(self):
        assert classify_risk("bos://governance/intent/compile") == RiskLevel.WRITE

    def test_write_trigger(self):
        assert classify_risk("bos://memory/mos/trigger") == RiskLevel.WRITE

    def test_write_challenge(self):
        assert classify_risk("bos://governance/shadow/challenge") == RiskLevel.WRITE

    def test_dangerous_enforce(self):
        assert classify_risk("bos://harness/constraint/enforce") == RiskLevel.DANGEROUS

    def test_dangerous_delete(self):
        assert classify_risk("bos://governance/bet/delete") == RiskLevel.DANGEROUS

    def test_dangerous_trip(self):
        assert classify_risk("bos://cockpit/circuit/trip") == RiskLevel.DANGEROUS

    def test_dangerous_reset(self):
        assert classify_risk("bos://cockpit/circuit/reset") == RiskLevel.DANGEROUS

    def test_dangerous_closeout(self):
        assert classify_risk("bos://governance/bet/closeout") == RiskLevel.DANGEROUS

    def test_dangerous_sign(self):
        assert classify_risk("bos://cockpit/spine/sign") == RiskLevel.DANGEROUS

    def test_dangerous_sediment(self):
        assert classify_risk("bos://resident/sediment/trigger") == RiskLevel.DANGEROUS

    def test_harness_domain_always_dangerous(self):
        assert classify_risk("bos://harness/run") == RiskLevel.DANGEROUS
        assert classify_risk("bos://harness/status") == RiskLevel.DANGEROUS
        assert classify_risk("bos://harness/anything") == RiskLevel.DANGEROUS

    def test_invalid_uri_returns_read(self):
        assert classify_risk("not-a-uri") == RiskLevel.READ

    def test_empty_uri_returns_read(self):
        assert classify_risk("") == RiskLevel.READ

    def test_short_uri_returns_read(self):
        assert classify_risk("bos://onlydomain") == RiskLevel.READ


class TestConfirmToken:
    def test_deterministic(self):
        body = b'{"uri":"bos://memory/mos/write","arguments":{}}'
        t1 = confirm_token("bos://memory/mos/write", body)
        t2 = confirm_token("bos://memory/mos/write", body)
        assert t1 == t2

    def test_different_bodies_different_tokens(self):
        t1 = confirm_token("bos://x", b'body1')
        t2 = confirm_token("bos://x", b'body2')
        assert t1 != t2

    def test_different_uris_different_tokens(self):
        t1 = confirm_token("bos://x", b'body')
        t2 = confirm_token("bos://y", b'body')
        assert t1 != t2

    def test_format(self):
        t = confirm_token("bos://system/health", b'body')
        assert t.startswith("bos://system/health:")
        hash_part = t.split(":", 2)[2]  # skip "bos:" and "uri:"
        assert len(hash_part) == 16
        # All hex chars
        assert all(c in "0123456789abcdef" for c in hash_part)


class TestRequireConfirm:
    def test_read_no_confirm_needed(self):
        result = require_confirm(RiskLevel.READ, "bos://x", b'body', None)
        assert result is None

    def test_read_with_header_ok(self):
        result = require_confirm(RiskLevel.READ, "bos://x", b'body', "any-value")
        assert result is None

    def test_write_missing_header(self):
        result = require_confirm(RiskLevel.WRITE, "bos://x", b'body', None)
        assert result == "RISK_CONFIRM_REQUIRED"

    def test_dangerous_missing_header(self):
        result = require_confirm(RiskLevel.DANGEROUS, "bos://x", b'body', None)
        assert result == "RISK_CONFIRM_REQUIRED"

    def test_write_wrong_header(self):
        result = require_confirm(RiskLevel.WRITE, "bos://x", b'body', "wrong-token")
        assert result == "RISK_CONFIRM_MISMATCH"

    def test_write_correct_header(self):
        token = confirm_token("bos://x", b'body')
        result = require_confirm(RiskLevel.WRITE, "bos://x", b'body', token)
        assert result is None

    def test_dangerous_correct_header(self):
        token = confirm_token("bos://x", b'body')
        result = require_confirm(RiskLevel.DANGEROUS, "bos://x", b'body', token)
        assert result is None
