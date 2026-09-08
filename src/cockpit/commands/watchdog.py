"""cockpit.commands.watchdog — Autonomous daemon watchdog & supervisor command."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path


def cmd_watchdog(args: argparse.Namespace) -> int:
    """DEPRECATED (Cockpit PR #78): watchdog 已退役 → Mesh-bound capability admission.

    保留 stub: 转发到 daemon-watchdog.py 但加迁移提示, 返回 exit 0 (不制造红色)。
    """
    from rich.console import Console

    from cockpit.commands.registry import COMMAND_CATALOG

    console = Console()
    meta = COMMAND_CATALOG.get("watchdog")
    console.print("[yellow]⚠ watchdog 已标记为 deprecated[/]")
    console.print(f"[dim]注册 maturity={meta.maturity} · risk={meta.risk}[/]")
    console.print(f"[bold cyan]迁移路径:[/]\n{meta.example}")

    # 软执行: 转发到 daemon-watchdog.py 仍然跑 (供现有监控脚本探测)
    # 但用 stderr 标记 deprecated
    from cockpit.env_resolver import get_workspace_root

    ws = get_workspace_root()
    script = ws / "bin" / "gac" / "daemon-watchdog.py"
    if not script.is_file():
        sys.stderr.write(f"Error: watchdog script not found at {script}\n")
        return 0  # 软返回

    watchdog_args = ["daemon-watchdog"]
    if getattr(args, "probe", False):
        watchdog_args.append("--probe")
    if getattr(args, "json", False):
        watchdog_args.append("--json")
    if getattr(args, "interval", None) is not None:
        watchdog_args.extend(["--interval", str(args.interval)])

    old_argv = sys.argv
    try:
        sys.argv = watchdog_args
        runpy.run_path(str(script), run_name="__main__")
        return 0
    except SystemExit:
        # deprecated 入口不传播非零退出码
        return 0
    except Exception as exc:
        sys.stderr.write(f"Watchdog error: {exc}\n")
        return 1
    finally:
        sys.argv = old_argv
