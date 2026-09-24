"""cockpit.commands.panorama — 治理全景控制舱命令入口 (BET-Y2Q2-T10-166).

提供全景大屏的终端快照查看、浏览器原生控制舱唤起与双核导流守护管理。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

console = Console()


def _get_workspace_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "docs" / "project-registry.yaml").is_file():
            return parent
    return cur.parents[3]


def cmd_panorama(args: argparse.Namespace) -> int:
    """治理全景控制舱总调度入口."""
    as_json = getattr(args, "json", False) or getattr(args, "global_output", "text") == "json"
    root = _get_workspace_root()

    # 1. Sunset 导流守护处理
    if getattr(args, "sunset", False):
        redirector_script = root / "bin" / "panorama" / "sunset-redirector.py"
        if as_json:
            print(json.dumps({"ok": True, "action": "sunset_check", "script": str(redirector_script)}))
        else:
            console.print(
                Panel.fit(
                    f"[bold cyan]🔄 双核下线端口导流守护器[/]\n"
                    f"脚本路径: [dim]{redirector_script}[/]\n"
                    f"导流策略: 43191 / 43910 请求自动 302 重定向至 Cockpit-UI\n"
                    f"目标地址: [green]http://localhost:5173/panorama[/]",
                    border_style="cyan",
                )
            )
        return 0

    # 2. Web 浏览器唤起模式
    if getattr(args, "web", False) or getattr(args, "wallboard", False) or getattr(args, "tab", None):
        port = getattr(args, "port", 5173) or 5173
        tab = getattr(args, "tab", None)
        target_url = f"http://localhost:{port}/panorama"
        if tab:
            target_url += f"?tab={tab}"

        if as_json:
            print(json.dumps({"ok": True, "target_url": target_url, "wallboard": getattr(args, "wallboard", False)}))
            return 0

        console.print(
            Panel.fit(
                f"[bold green]🏛️ 正在启动并进入治理全景控制舱[/]\n"
                f"访问地址: [link={target_url}][bold cyan]{target_url}[/][/link]\n"
                f"大屏模式: [dim]{'壁挂沉浸 (Wallboard)' if getattr(args, 'wallboard', False) else '标准视窗'}[/]\n"
                f"[dim]快捷操作: 按 [cyan]F[/] 全屏沉浸 · 按 [cyan]A[/] 自动轮播 · 数字键 [cyan]1-5[/] 切板块[/dim]",
                title="Cockpit Panorama",
                border_style="green",
            )
        )
        try:
            webbrowser.open(target_url)
        except Exception as e:
            console.print(f"[yellow]⚠ 无法自动唤起系统浏览器: {e}[/]")
            console.print(f"请手动访问: [cyan]{target_url}[/]")
        return 0

    # 3. 终端 TUI / 7 维全景模式
    omo_project = str((root / "projects" / "omo").resolve())
    cmd = ["uv", "run", "--project", omo_project, "python", "-m", "omo.cli", "panorama"]
    if as_json:
        cmd.append("--json")

    env = {k: v for k, v in os.environ.items() if not k.startswith("VIRTUAL_ENV") and k != "PYTHONHOME"}
    exit_code = subprocess.call(cmd, env=env)

    if not as_json and exit_code == 0:
        console.print(
            "\n[dim]💡 提示: 运行 [bold cyan]cockpit panorama --web[/] 可在浏览器中唤起原生现代全景控制舱与门禁矩阵。[/dim]\n"
        )

    return exit_code
