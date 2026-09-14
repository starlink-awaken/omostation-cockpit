"""cockpit.commands.resident — 委派 omo resident CLI（常驻 Agent 体系, WP-A~I）。"""

from __future__ import annotations

import argparse
import subprocess

from .base import _SCRIPT_DIR


def cmd_resident(args: argparse.Namespace) -> int:
    """cockpit resident <sub> — resident 常驻 Agent 体系命令。

    委派到 omo.cli resident（SSOT 入口, 见 docs/architecture/resident-agent-system-v1.md）。
    子命令: status / roles / daemon / signals / alert / decision / execute /
            sediment / memory / promote / resources / ingest

    cockpit-native decision 子命令 (BET-Y1Q4-T8-21):
      decision triage  — 按状态/类型过滤决策提案
      decision approve — 一键生成 BET/ADR 模板
      decision status  — 查看归档进度

    跨 worktree/主仓兼容: 直接调用 omo 项目的 .venv/bin/python, 避免 uv 的 VIRTUAL_ENV 警告
    (uv parent env 读取的 VIRTUAL_ENV 与 subprocess env=env 无关)。
    """
    resident_args = list(getattr(args, "resident_args", []))

    # ── 拦截 cockpit-native decision triage/approve/status (BET-Y1Q4-T8-21) ──
    if len(resident_args) >= 2 and resident_args[0] == "decision":
        sub_cmd = resident_args[1]
        if sub_cmd in ("triage", "approve", "status"):
            from cockpit.commands.resident_decision import (
                cmd_approve,
                cmd_status,
                cmd_triage,
                register_resident_subparser,
            )

            # 构建子解析器
            parser = argparse.ArgumentParser(prog=f"cockpit resident {resident_args[0]} {sub_cmd}")
            subparsers = parser.add_subparsers(dest="resident_sub")
            register_resident_subparser(subparsers)
            try:
                parsed = parser.parse_args(resident_args[1:])
                if hasattr(parsed, "func"):
                    return parsed.func(parsed)
                return 1
            except SystemExit as exc:
                return int(exc.code or 0)

    # ── 委派 omo (原有逻辑) ──
    omo_project = _SCRIPT_DIR.parent.parent.parent.parent / "omo"
    omo_venv_python = omo_project / ".venv" / "bin" / "python"

    if omo_venv_python.exists():
        # 优先: 用 omo/.venv/bin/python (直接, 无 uv 警告)
        cmd = [
            str(omo_venv_python),
            "-W",
            "ignore::DeprecationWarning",
            "-m",
            "omo.cli",
            "resident",
        ] + list(getattr(args, "resident_args", []))
        return subprocess.call(cmd, cwd=str(omo_project))

    # 回退: 用 uv run (需 OMO_PROJECT_READY, 触发 VIRTUAL_ENV 警告但不致命)
    cmd = [
        "uv",
        "run",
        "--directory",
        str(omo_project.resolve()),
        "python",
        "-W",
        "ignore::DeprecationWarning",
        "-m",
        "omo.cli",
        "resident",
    ] + list(getattr(args, "resident_args", []))
    env = {k: v for k, v in __import__("os").environ.items() if k != "VIRTUAL_ENV"}
    return subprocess.call(cmd, env=env)
