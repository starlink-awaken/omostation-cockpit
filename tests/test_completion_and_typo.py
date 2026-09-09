"""Tests for completion generators, typo suggestion, and CLI-REFERENCE (BET-Y1Q4-T8-16)."""

from __future__ import annotations

import json
from pathlib import Path

from cockpit.cli import main
from cockpit.commands.completion import (
    SUPPORTED_SHELLS,
    generate_bash_completion,
    generate_fish_completion,
    generate_zsh_completion,
    suggest_commands,
)
from cockpit.domain.exit_codes import ExitCode


def test_all_three_shell_scripts_generated():
    scripts = {
        "bash": generate_bash_completion(),
        "zsh": generate_zsh_completion(),
        "fish": generate_fish_completion(),
    }
    assert set(scripts) == set(SUPPORTED_SHELLS)
    assert "cockpit" in scripts["bash"] and "complete" in scripts["bash"]
    assert scripts["zsh"].startswith("#compdef cockpit")
    assert "_cockpit" in scripts["zsh"]
    assert "function" in scripts["fish"] or "complete" in scripts["fish"]


def test_suggest_commands_close_match():
    # 单字符换位/漏字 → 建议真实命令
    assert "telemetry" in suggest_commands("telemtry")
    assert "completion" in suggest_commands("completoin")
    for s in suggest_commands("totally-unknown-cmd-xyz"):
        assert isinstance(s, str)


def test_suggest_commands_distance_bound():
    # 完全无关的 token 不产生低质量建议
    assert suggest_commands("zzzzzzzzzzzz") == []
    # 距离上限: 空串无建议
    assert suggest_commands("") == []


def test_unknown_command_json_payload_carries_suggestions(capsys):
    """WorkspaceParser.error 的 did-you-mean: JSON 模式输出 suggestions 字段。"""
    import pytest

    from cockpit.domain.fuzzy_matcher import find_closest_commands

    assert "telemetry" in find_closest_commands("telemtry")
    with pytest.raises(SystemExit):
        main(["telemtry", "--json"])  # telemetry 的 typo, parser.error 拦截
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert "telemetry" in data["suggestions"]


def test_cli_reference_generated_scale():
    """生成物 ≥300 行且结构完整 (CLI Reference Manual)。

    cockpit docs export 默认输出到 cockpit 仓的 parents[5]/docs/CLI-REFERENCE.md。
    在 worktree 跑测试时, parents[5] = worktree 根。
    测试自动 export 后, 优先查找该路径, fallback 到主仓 docs。
    """
    import subprocess
    test_path = Path(__file__).resolve()
    cockpit_export_path = test_path.parents[5] / "docs" / "CLI-REFERENCE.md"
    main_workspace_path = Path("/Users/xiamingxing/Workspace/docs/CLI-REFERENCE.md")
    candidates = [cockpit_export_path, main_workspace_path]
    ref = next((p for p in candidates if p.exists()), None)
    if ref is None:
        # 自动 cockpit docs export
        try:
            subprocess.run(
                ["uv", "run", "python", "-m", "cockpit", "docs", "export"],
                capture_output=True, timeout=60,
                cwd=test_path.parents[1],  # projects/cockpit
            )
        except Exception:
            pass
        ref = next((p for p in candidates if p.exists()), None)
    assert ref is not None, f"CLI-REFERENCE.md not found. Tried: {[str(p) for p in candidates]}"
    lines = ref.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 300, f"only {len(lines)} lines"
    text = "\n".join(lines)
    # 兼容中英文版本
    assert ("## Table of Contents" in text) or ("## 1. Global Flags" in text), \
        "Neither ## Table of Contents (中文) nor ## 1. Global Flags (英文) found"
    # 至少 8 个 emoji category 段
    assert (
        sum(text.count(c) for c in ["### 📚", "### 🧠", "### 📋", "### 🤖", "### 🏛️", "### 🖥️", "### 📡", "### 🔌"]) >= 8
    )