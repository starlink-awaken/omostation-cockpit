"""Cockpit Ask & Proxy-Env Commands — 本地大模型快速调用与环境代理."""

from __future__ import annotations

import os
import subprocess

from rich.console import Console
from rich.markdown import Markdown

console = Console()

AETHERFORGE_BASE_URL = os.environ.get("AETHERFORGE_BASE_URL", "http://127.0.0.1:9290/v1")


def _get_api_key() -> str:
    """Retrieve AetherForge API key from macOS Keychain or environment."""
    key = os.environ.get("AETHERFORGE_API_KEY", "")
    if key:
        return key
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "aetherforge-gateway", "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def cmd_ask(args) -> int:
    """快速询问本地大模型 (llm-router 三级降级: omlxc 网关 → ollama)。"""
    prompt = " ".join(args.prompt) if getattr(args, "prompt", None) else None
    if not prompt:
        console.print('[yellow]用法: cockpit ask "你的问题"[/yellow]')
        return 1

    model = getattr(args, "model", None)

    try:
        from cockpit.llm_router import complete

        with console.status("[cyan]llm-router 推理中 (omlxc → ollama)...[/cyan]"):
            content, source = complete(prompt, model=model)
    except Exception as e:  # noqa: BLE001 — CLI 边界兜底, 保持与旧行为一致的错误呈现
        console.print(f"[red]Error: {e}[/red]")
        return 1

    if not content:
        console.print("[red]所有推理后端均不可用 (omlxc 网关 + ollama)。[/red]")
        console.print("[yellow]排查: 1) 启动 omlxc 网关  2) `ollama pull <model>` 拉取本地模型[/yellow]")
        return 1

    console.print()
    console.print(Markdown(content))
    console.print()
    if source == "ollama":
        console.print("[dim]⚠️ 此为 ollama 降级回复 (omlxc 网关不可用)。[/dim]")
    return 0


def cmd_proxy_env(args) -> int:
    """输出兼容外部 CLI 的环境变量."""
    key = _get_api_key()
    if not key:
        console.print("[red]AETHERFORGE_API_KEY 未找到。请确认 AetherForge 已就绪或环境变量已设置。[/red]")
        return 1

    console.print(f'export OPENAI_API_BASE="{AETHERFORGE_BASE_URL}"')
    console.print(f'export OPENAI_API_KEY="{key}"')
    console.print(f'export AETHERFORGE_BASE_URL="{AETHERFORGE_BASE_URL}"')
    console.print(f'export AETHERFORGE_API_KEY="{key}"')
    console.print("\n# 用法: eval $(cockpit proxy-env)")
    return 0
