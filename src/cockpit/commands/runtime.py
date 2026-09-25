"""cockpit.commands.runtime — 委派 runtime CLI（L1 运行时入口）。"""

from __future__ import annotations

import argparse
import subprocess

from .base import _SCRIPT_DIR
from .delegation_guard import DelegationPreflightError, preflight_delegation


def cmd_runtime(args: argparse.Namespace) -> int:
    """通用 runtime CLI 委派包装。"""
    runtime_project = _SCRIPT_DIR.parent.parent.parent.parent / "runtime"
    try:
        preflight_delegation(runtime_project.parent, project="runtime", command="uv")
    except DelegationPreflightError as exc:
        from rich.console import Console

        Console().print(f"[red]❌ 前置检查失败: {exc}[/red]")
        return 1
    cmd = [
        "uv",
        "run",
        "--directory",
        str(runtime_project.resolve()),
        "python",
        "-W",
        "ignore::DeprecationWarning",
        "-m",
        "runtime.cli",
    ] + list(getattr(args, "runtime_args", []))
    return subprocess.call(cmd)
