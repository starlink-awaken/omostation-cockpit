"""cockpit.commands.omo — 委派 omo CLI（债务治理入口）。"""

from __future__ import annotations

import argparse
import subprocess

from .base import _SCRIPT_DIR
from .delegation import clean_env
from .delegation_guard import DelegationPreflightError, preflight_delegation


def cmd_omo(args: argparse.Namespace) -> int:
    """通用 omo CLI 委派包装：omo debt / omo state / omo governance / omo lint / ..."""
    # 定位 omo 项目
    omo_project = _SCRIPT_DIR.parent.parent.parent.parent / "omo"
    try:
        preflight_delegation(omo_project.parent, project="omo", command="uv")
    except DelegationPreflightError as exc:
        from rich.console import Console

        Console().print(f"[red]❌ 前置检查失败: {exc}[/red]")
        return 1
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
    ] + list(getattr(args, "omo_args", []))
    return subprocess.call(cmd, env=clean_env())


# 以下为高频子命令的具名包装 —— 可在 cli.py 中直接绑定


def cmd_omo_debt(args: argparse.Namespace) -> int:
    """cockpit omo debt — OMO 债务查询。"""
    omo_project = _SCRIPT_DIR.parent.parent.parent.parent / "omo"
    try:
        preflight_delegation(omo_project.parent, project="omo", command="uv")
    except DelegationPreflightError as exc:
        from rich.console import Console

        Console().print(f"[red]❌ 前置检查失败: {exc}[/red]")
        return 1
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
        "debt",
    ] + list(getattr(args, "omo_debt_args", []))
    return subprocess.call(cmd, env=clean_env())


def cmd_omo_state(args: argparse.Namespace) -> int:
    """cockpit omo state — OMO 状态查询。"""
    omo_project = _SCRIPT_DIR.parent.parent.parent.parent / "omo"
    try:
        preflight_delegation(omo_project.parent, project="omo", command="uv")
    except DelegationPreflightError as exc:
        from rich.console import Console

        Console().print(f"[red]❌ 前置检查失败: {exc}[/red]")
        return 1
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
        "state",
    ] + list(getattr(args, "omo_state_args", []))
    return subprocess.call(cmd, env=clean_env())
