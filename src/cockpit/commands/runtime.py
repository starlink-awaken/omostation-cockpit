"""cockpit.commands.runtime — 委派 runtime CLI（L1 运行时入口）。"""

from __future__ import annotations

import argparse
import subprocess

from ..data_index import resolve_workspace_root
from .delegation_guard import DelegationPreflightError, preflight_delegation


def cmd_runtime(args: argparse.Namespace) -> int:
    """通用 runtime CLI 委派包装。"""
    workspace_root = resolve_workspace_root()
    runtime_project = workspace_root / "projects" / "runtime"
    try:
        preflight_delegation(workspace_root, project="runtime", command="uv")
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
