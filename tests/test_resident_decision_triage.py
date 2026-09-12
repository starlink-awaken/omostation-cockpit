"""test_resident_decision_triage — BET-Y1Q4-T8-21 决策提案 triage 单元测试.

覆盖:
  - _scan_proposals 基础扫描
  - _parse_frontmatter 解析
  - cmd_status 归档进度
  - 状态过滤逻辑
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Fixtures ──

SAMPLE_PROPOSAL_MD = """---
schema: resident-decision/v1
status: draft
trigger_event_type: WorkflowFailed
trace_id: test-trace-001
proposal_count: 3
generated_at: 2026-09-12T00:00:00Z
---

# 测试提案

## 触发事件
- event_type: WorkflowFailed
"""

SAMPLE_REVIEWED_MD = """---
schema: resident-decision/v1
status: reviewed
triage_status: reviewed
trigger_event_type: StepFailed
trace_id: test-trace-002
proposal_count: 1
generated_at: 2026-09-11T00:00:00Z
---

# 已审阅提案
"""

SAMPLE_DISMISSED_MD = """---
schema: resident-decision/v1
status: dismissed
triage_status: dismissed
trigger_event_type: StepTimeout
trace_id: test-trace-003
proposal_count: 0
generated_at: 2026-09-10T00:00:00Z
---

# 已驳回提案
"""


@pytest.fixture
def tmp_proposal_dir(tmp_path: Path) -> Path:
    """创建临时提案目录并写入样本文件."""
    prop_dir = tmp_path / ".omo" / "_knowledge" / "decision-proposals"
    prop_dir.mkdir(parents=True)

    (prop_dir / "decision-20260912-test-001.md").write_text(SAMPLE_PROPOSAL_MD, encoding="utf-8")
    (prop_dir / "decision-20260911-test-002.md").write_text(SAMPLE_REVIEWED_MD, encoding="utf-8")
    (prop_dir / "decision-20260910-test-003.md").write_text(SAMPLE_DISMISSED_MD, encoding="utf-8")

    return tmp_path


# ── Tests: _parse_frontmatter ──

class TestParseFrontmatter:
    def test_basic_parsing(self):
        from cockpit.commands.resident_decision import _parse_frontmatter

        result = _parse_frontmatter(SAMPLE_PROPOSAL_MD)
        assert result["schema"] == "resident-decision/v1"
        assert result["trigger_event_type"] == "WorkflowFailed"
        assert result["proposal_count"] == "3"

    def test_empty_content(self):
        from cockpit.commands.resident_decision import _parse_frontmatter

        result = _parse_frontmatter("no frontmatter here")
        assert result == {}

    def test_reviewed_status(self):
        from cockpit.commands.resident_decision import _parse_frontmatter

        result = _parse_frontmatter(SAMPLE_REVIEWED_MD)
        assert result["triage_status"] == "reviewed"


# ── Tests: _scan_proposals ──

class TestScanProposals:
    def test_scan_all(self, tmp_proposal_dir: Path):
        from cockpit.commands.resident_decision import _scan_proposals

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            results = _scan_proposals()

        assert len(results) == 3

    def test_filter_by_status(self, tmp_proposal_dir: Path):
        from cockpit.commands.resident_decision import _scan_proposals

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            results = _scan_proposals(status_filter="reviewed")

        assert len(results) == 1
        assert results[0]["status"] == "reviewed"

    def test_filter_by_type(self, tmp_proposal_dir: Path):
        from cockpit.commands.resident_decision import _scan_proposals

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            results = _scan_proposals(type_filter="WorkflowFailed")

        assert len(results) == 1
        assert results[0]["event_type"] == "WorkflowFailed"

    def test_filter_no_match(self, tmp_proposal_dir: Path):
        from cockpit.commands.resident_decision import _scan_proposals

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            results = _scan_proposals(status_filter="promoted")

        assert len(results) == 0

    def test_empty_dir(self, tmp_path: Path):
        from cockpit.commands.resident_decision import _scan_proposals

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_path):
            results = _scan_proposals()

        assert results == []


# ── Tests: cmd_resident_decision_status (归档进度) ──

class TestStatusCommand:
    def test_status_output(self, tmp_proposal_dir: Path, capsys):
        from cockpit.commands.resident_decision import cmd_status

        args = type("Args", (), {})()

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            rc = cmd_status(args)

        assert rc == 0
        captured = capsys.readouterr()
        assert "3" in captured.out  # total

    def test_status_empty_dir(self, tmp_path: Path, capsys):
        from cockpit.commands.resident_decision import cmd_status

        args = type("Args", (), {})()

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_path):
            rc = cmd_status(args)

        assert rc == 0


# ── Tests: cmd_resident_decision_triage ──

class TestTriageCommand:
    def test_triage_json_output(self, tmp_proposal_dir: Path, capsys):
        from cockpit.commands.resident_decision import cmd_triage

        args = type("Args", (), {"status": None, "type": None, "json": True})()

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            rc = cmd_triage(args)

        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 3

    def test_triage_filtered_json(self, tmp_proposal_dir: Path, capsys):
        from cockpit.commands.resident_decision import cmd_triage

        args = type("Args", (), {"status": "reviewed", "type": None, "json": True})()

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            rc = cmd_triage(args)

        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 1


# ── Tests: cmd_resident_decision_approve ──

class TestApproveCommand:
    def test_approve_missing_id(self, tmp_path: Path, capsys):
        from cockpit.commands.resident_decision import cmd_approve

        args = type("Args", (), {"proposal_id": None, "target": "bet"})()

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_path):
            rc = cmd_approve(args)

        assert rc == 1

    def test_approve_not_found(self, tmp_path: Path, capsys):
        from cockpit.commands.resident_decision import cmd_approve

        args = type("Args", (), {"proposal_id": "nonexistent", "target": "bet"})()

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_path):
            rc = cmd_approve(args)

        assert rc == 1

    def test_approve_generates_bet_template(self, tmp_proposal_dir: Path, capsys):
        from cockpit.commands.resident_decision import cmd_approve

        args = type("Args", (), {"proposal_id": "test-001", "target": "bet"})()

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            rc = cmd_approve(args)

        assert rc == 0
        captured = capsys.readouterr()
        assert "模板已生成" in captured.out

        # 验证模板文件存在
        template_files = list(
            tmp_proposal_dir.glob(".omo/_delivery/templates/bet-*.yaml")
        )
        assert len(template_files) == 1

    def test_approve_generates_adr_template(self, tmp_proposal_dir: Path, capsys):
        from cockpit.commands.resident_decision import cmd_approve

        args = type("Args", (), {"proposal_id": "test-002", "target": "adr"})()

        with patch("cockpit.commands.resident_decision.WORKSPACE_ROOT", tmp_proposal_dir):
            rc = cmd_approve(args)

        assert rc == 0
        template_files = list(
            tmp_proposal_dir.glob(".omo/_delivery/templates/adr-*.yaml")
        )
        assert len(template_files) == 1


# ── Tests: register_resident_subparser ──

class TestRegisterSubparser:
    def test_register(self):
        from cockpit.commands.resident_decision import register_resident_subparser

        import argparse
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        register_resident_subparser(subparsers)

        # 验证子命令已注册（通过解析验证）
        args = parser.parse_args(["triage", "--status", "reviewed", "--json"])
        assert args.status == "reviewed"
        assert args.json is True

        args2 = parser.parse_args(["status"])
        assert hasattr(args2, "func")

        args3 = parser.parse_args(["approve", "--proposal-id", "test", "--target", "adr"])
        assert args3.proposal_id == "test"
        assert args3.target == "adr"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
