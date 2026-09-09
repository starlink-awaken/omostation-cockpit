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

    跨 worktree/主仓兼容: 直接调用 omo 项目的 .venv/bin/python, 避免 uv 的 VIRTUAL_ENV 警告
    (uv parent env 读取的 VIRTUAL_ENV 与 subprocess env=env 无关)。
    """
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
