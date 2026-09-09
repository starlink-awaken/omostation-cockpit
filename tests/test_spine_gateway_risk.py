"""Tests for spine outbound gateway risk layer (BET-Y1Q4-T4-06).

覆盖: DLP 风控阻断/acknowledge 放行、重放拦截/allow 放行、单日频次硬熔断、
OutboundMessageReceipt 落盘、smtp 配置缺失 fail closed。
隔离: monkeypatch _ws → tmp_path; DLP/builtin 通道按需 patch。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cockpit.commands.spine import (
    _content_digest,
    cmd_spine_send,
)


def _send_args(**kw):
    base = dict(
        spine_command="send", body="测试外发内容", body_file=None,
        channel="api", to="x@example", dry_run=False, sender="",
        risk_acknowledge=False, allow_replay=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _spool(tmp_path: Path) -> Path:
    return tmp_path / ".omo" / "state" / "spine-outbox"


def _first_msg_dir(spool: Path) -> Path:
    return next(d for d in spool.iterdir() if d.is_dir())


@pytest.fixture()
def no_builtin(monkeypatch: pytest.MonkeyPatch):
    """默认桩掉内建通道 (风控层单测不触真实发送); 需要 sent 态的用例自行覆盖为成功。"""
    import cockpit.commands.spine as spine

    monkeypatch.setattr(spine, "_send_builtin", lambda channel, to, body, msg_id: (True, "test://mock"))


def test_digest_stable_and_distinct():
    assert _content_digest("api", "a@x", "hi") == _content_digest("api", "a@x", "hi")
    assert _content_digest("api", "a@x", "hi") != _content_digest("smtp", "a@x", "hi")
    assert _content_digest("api", "a@x", "hi") != _content_digest("api", "b@x", "hi")


def test_envelope_carries_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_builtin):
    """入队 envelope 必须带 body_digest (重放拦截的判定基础)。"""
    import cockpit.commands.spine as spine

    monkeypatch.setattr(spine, "_ws", lambda: tmp_path)
    assert cmd_spine_send(_send_args(dry_run=True)) == 0
    env = json.loads((_first_msg_dir(_spool(tmp_path)) / "envelope.json").read_text(encoding="utf-8"))
    assert env["body_digest"] == _content_digest("api", "x@example", "测试外发内容")


def test_replay_blocked_then_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_builtin):
    """同 digest 已 sent → blocked-replay; --allow-replay 显式放行。"""
    import cockpit.commands.spine as spine

    monkeypatch.setattr(spine, "_ws", lambda: tmp_path)
    assert cmd_spine_send(_send_args()) == 0  # 首发成功
    # 二发同内容: 默认拦截
    assert cmd_spine_send(_send_args()) == 1
    dirs = sorted(d for d in _spool(tmp_path).iterdir() if d.is_dir())
    env = json.loads((dirs[-1] / "envelope.json").read_text(encoding="utf-8"))
    assert env["status"] == "blocked-replay"
    receipt = json.loads((dirs[-1] / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["schema"] == "outbound-message-receipt/v1"
    assert receipt["status"] == "blocked-replay" and "重放" in receipt["reason"]
    # --allow-replay 显式放行
    assert cmd_spine_send(_send_args(allow_replay=True)) == 0


def test_daily_cap_hard_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_builtin):
    """单日频次硬熔断: 到 cap 即拦, --allow-replay 也解不了 (无 flag 可解)。"""
    import cockpit.commands.spine as spine

    monkeypatch.setattr(spine, "_ws", lambda: tmp_path)
    monkeypatch.setattr(spine, "_gateway_policy", lambda: {"daily_send_cap": 1})
    assert cmd_spine_send(_send_args(body="第一条")) == 0  # 占满 cap
    rc = cmd_spine_send(_send_args(body="第二条"))  # 不同的内容, 非重放
    assert rc == 1
    dirs = sorted(d for d in _spool(tmp_path).iterdir() if d.is_dir())
    env = json.loads((dirs[-1] / "envelope.json").read_text(encoding="utf-8"))
    assert env["status"] == "blocked-cap"
    receipt = json.loads((dirs[-1] / "receipt.json").read_text(encoding="utf-8"))
    assert "超限" in receipt["reason"]


def test_receipt_sent_has_required_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_builtin):
    """OutboundMessageReceipt 形式化: sent 凭据字段齐 + 台账引用 receipt。"""
    import cockpit.commands.spine as spine

    monkeypatch.setattr(spine, "_ws", lambda: tmp_path)
    assert cmd_spine_send(_send_args()) == 0
    msg_dir = _first_msg_dir(_spool(tmp_path))
    receipt = json.loads((msg_dir / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["schema"] == "outbound-message-receipt/v1"
    assert receipt["status"] == "sent"
    for field in ("msg_id", "channel", "to", "body_digest", "sent_at", "provider_ref"):
        assert receipt.get(field), f"receipt 缺字段 {field}"
    ledger = tmp_path / ".omo" / "state" / "value-pacing-ledger.jsonl"
    entry = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert entry["body_digest"] == receipt["body_digest"]


def test_smtp_missing_config_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """T4-06 契约: 内建通道凭据缺失 fail closed (不再静默假装成功)。"""
    import cockpit.commands.spine as spine

    monkeypatch.setattr(spine, "_ws", lambda: tmp_path)
    monkeypatch.setenv("SPINE_SMTP_CONFIG", str(tmp_path / "nonexistent-smtp.json"))
    rc = cmd_spine_send(_send_args(channel="smtp"))
    assert rc == 1
    env = json.loads((_first_msg_dir(_spool(tmp_path)) / "envelope.json").read_text(encoding="utf-8"))
    assert env["status"] == "failed"
    receipt = json.loads((_first_msg_dir(_spool(tmp_path)) / "receipt.json").read_text(encoding="utf-8"))
    assert "配置缺失" in receipt["reason"]
    assert not (tmp_path / ".omo" / "state" / "value-pacing-ledger.jsonl").exists()


def test_dlp_high_blocked_then_acknowledged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """DLP high 命中 → 强制阻断; --risk-acknowledge 人工确认放行 (circuit_breaker 语义)。"""
    import cockpit.commands.spine as spine

    monkeypatch.setattr(spine, "_ws", lambda: tmp_path)
    monkeypatch.setattr(spine, "_send_builtin", lambda channel, to, body, msg_id: (True, "test://mock"))

    class _F:
        risk = "high"
        type = "secret-key"

    monkeypatch.setattr(spine, "_dlp_high_findings", lambda body: [_F()])
    assert cmd_spine_send(_send_args(body="含密钥内容")) == 1
    dirs = sorted(d for d in _spool(tmp_path).iterdir() if d.is_dir())
    env = json.loads((dirs[-1] / "envelope.json").read_text(encoding="utf-8"))
    assert env["status"] == "blocked-risk"
    # 人工确认后放行
    assert cmd_spine_send(_send_args(body="含密钥内容", risk_acknowledge=True)) == 0


def test_policy_registry_cap_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """policy 注册表 daily_send_cap 被正确读取 (rrgistry 缺失回退默认 50)。"""
    import cockpit.commands.spine as spine

    monkeypatch.setattr(spine, "_ws", lambda: tmp_path)
    assert spine._gateway_policy()["daily_send_cap"] == 50  # 缺失回退
    reg = tmp_path / ".omo" / "_truth" / "registry"
    reg.mkdir(parents=True)
    (reg / "spine-gateway-policy.yaml").write_text("daily_send_cap: 7\n", encoding="utf-8")
    assert spine._gateway_policy()["daily_send_cap"] == 7
