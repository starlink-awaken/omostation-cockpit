"""cockpit.commands.family_hub — 家庭数字枢纽入口。"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from rich.console import Console

from cockpit.env_resolver import get_workspace_root as _get_workspace_root

console = Console()


def _workspace_root() -> Path:
    return _get_workspace_root()


def _project_root() -> Path:
    return _workspace_root() / "projects" / "family-hub"


def cmd_family_hub(args: argparse.Namespace) -> int:
    """family-hub 入口：status / api / mcp。"""
    subcmd = getattr(args, "family_hub_command", None)

    if subcmd == "status":
        console.print("[cyan]family-hub[/cyan]")
        console.print("  API server:  bun run api  (api/server.ts)")
        console.print("  MCP server:  python mcp_server.py")
        # 真实探测 API 是否在跑 + 前置条件 (2026-09-24 走查: 只打印启动命令不探测状态, 用户无法判断可用性)
        import urllib.error
        import urllib.request

        api_port = int(__import__("os").environ.get("FAMILY_HUB_PORT", "3001"))
        try:
            with urllib.request.urlopen(f"http://localhost:{api_port}/api/health", timeout=2) as resp:  # noqa: S310
                import json as _json

                health = _json.loads(resp.read())
            console.print(f"  [green]● API 运行中[/green] :{api_port} · db={health.get('database', '?')}")
            if not health.get("write_auth_configured"):
                console.print("  [yellow]⚠ FAMILY_HUB_API_TOKEN 未配置 — 数据接口停用[/yellow]")
                console.print("[dim]    启动: `cockpit family-hub api` (需 bun) · 配置 token 后数据面可用[/dim]")
        except (urllib.error.URLError, OSError):
            console.print(f"  [red]● API 未运行[/red] :{api_port}  [dim]→ `cockpit family-hub api`[/dim]")
        except Exception as exc:  # defensive — status 永不崩溃
            console.print(f"  [yellow]● API 探测失败[/yellow] [dim]({exc})[/dim]")
        return 0
    if subcmd == "api":
        bun_bin = shutil.which("bun")
        if not bun_bin:
            console.print("[red]未找到 bun[/red]")
            return 1
        return subprocess.call(
            [bun_bin, "run", "api"],
            cwd=str(_project_root().resolve()),
        )
    if subcmd == "mcp":
        return subprocess.call(
            ["python3", str((_project_root() / "mcp_server.py").resolve())],
            cwd=str(_project_root().resolve()),
        )

    console.print("[red]未知 family-hub 子命令[/red]")
    console.print("可用: status, api, mcp")
    return 1
