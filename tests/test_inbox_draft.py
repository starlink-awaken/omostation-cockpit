"""Tests for cockpit inbox mail-draft command face (BET-Y1Q3-T10-113)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cockpit.commands.inbox import cmd_inbox_draft


def test_inbox_draft_json_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import cockpit.commands.inbox as inbox

    body_file = tmp_path / "mail.txt"
    body_file.write_text("关于医共体建设方案的请示，请研究反馈。", encoding="utf-8")

    fake = {
        "subject": "关于医共体建设方案的请示",
        "tiers": {"brief_confirm": "收悉。", "verbose_reply": "经研究函复如下：", "polite_decline": "暂难安排。"},
        "latency_ms": 1.0, "ttft_budget_ms": 3000, "attachments": [],
    }
    monkeypatch.setattr(
        inbox, "_agora_python",
        lambda code, timeout=120.0: (0, json.dumps(fake, ensure_ascii=False)),
    )

    args = argparse.Namespace(
        spine_command="mail-draft", body="", body_file=str(body_file),
        subject="", attachment="", attachment_fmt="csv", json=True,
    )
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_inbox_draft(args)
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert set(data["tiers"]) == {"brief_confirm", "verbose_reply", "polite_decline"}


def test_inbox_draft_requires_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    args = argparse.Namespace(
        spine_command="mail-draft", body="", body_file=None,
        subject="", attachment="", attachment_fmt="csv", json=False,
    )
    assert cmd_inbox_draft(args) == 1
