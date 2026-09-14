"""Tests for cockpit strategy command face (BET-Y2Q1-T5-01)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cockpit.commands.strategy import cmd_strategy, cmd_strategy_simulate


def _args(**kw):
    base = dict(strategy_subcmd="simulate", proposal=None, rounds=100, seed=42,
                demo=False, out=None, json=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_strategy_demo_ok(capsys):
    assert cmd_strategy(_args(demo=True)) == 0
    out = capsys.readouterr().out
    assert "止损线" in out or "stop" in out.lower()


def test_strategy_demo_json(tmp_path: Path, capsys):
    rc = cmd_strategy_simulate(_args(demo=True, json=True))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["rounds"] == 100
    assert payload["p5"] <= payload["p50"] <= payload["p95"]
    assert payload["stop_loss"] == payload["p5"]
    assert len(payload["sensitivity"]) == 4


def test_strategy_proposal_file_and_out(tmp_path: Path):
    prop = tmp_path / "p.md"
    prop.write_text("预算 60 万元替换第三方订阅，预期降本。", encoding="utf-8")
    report = tmp_path / "r.md"
    assert cmd_strategy(_args(proposal=str(prop), out=str(report), rounds=20, seed=7)) == 0
    text = report.read_text(encoding="utf-8")
    assert "止损线" in text and "敏感性因子" in text


def test_strategy_missing_file():
    assert cmd_strategy(_args(proposal="/nonexistent/p.md")) == 1


def test_strategy_requires_proposal_or_demo():
    assert cmd_strategy(_args()) == 1
