"""cockpit.commands.mesh — omlx 算力网格路由入口。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from urllib import request as urlrequest

from rich.console import Console

from cockpit.env_resolver import get_workspace_root as _get_workspace_root
from cockpit.commands.delegation_guard import DelegationPreflightError, check_port_open, preflight_delegation

console = Console()


def _workspace_root() -> Path:
    return _get_workspace_root()


def _mesh_router_url() -> str:
    port = os.environ.get("MOF_MESH_PORT", "18080")
    return f"http://127.0.0.1:{port}"


def _urlopen_safe(url: str, timeout: float = 5.0):
    """只允许 http/https 的内部 urlopen 包装。"""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"不支持的 URL scheme: {url}")
    return urlrequest.urlopen(url, timeout=timeout)  # noqa: S310


def cmd_mesh(args: argparse.Namespace) -> int:
    """算力网格入口：nodes / status / route --model / serve。"""
    subcmd = getattr(args, "mesh_command", None)
    ws_root = _workspace_root()

    if subcmd == "nodes":
        endpoints = [
            f"{_mesh_router_url()}/nodes",
            f"{_mesh_router_url()}/v1/models",
            "http://127.0.0.1:18080/v1/models",
        ]
        unique_endpoints = list(dict.fromkeys(endpoints))
        last_exc = None
        for endpoint in unique_endpoints:
            try:
                with _urlopen_safe(endpoint) as resp:
                    console.print_json(data=json.loads(resp.read()))
                    return 0
            except Exception as exc:
                last_exc = exc
                continue

        console.print(f"[red]获取节点失败: 无法连接端点 ({', '.join(unique_endpoints)}): {last_exc}[/red]")
        console.print("[yellow]提示: 请确认智能网关 (18080) 或 AetherForge (4000) 服务已启动[/yellow]")
        return 1
    if subcmd == "status":
        primary_url = f"{_mesh_router_url()}/health"
        try:
            with _urlopen_safe(primary_url) as resp:
                console.print_json(data=json.loads(resp.read()))
                return 0
        except Exception as exc_primary:
            fallback_url = "http://127.0.0.1:4000/health"
            try:
                with _urlopen_safe(fallback_url) as resp:
                    console.print_json(data=json.loads(resp.read()))
                    return 0
            except Exception as exc_fallback:
                console.print(
                    f"[red]获取状态失败: 主网关 ({primary_url}: {exc_primary}) 与备用网关 ({fallback_url}: {exc_fallback}) 均不可达[/red]"
                )
                console.print("[yellow]提示: 请确认智能网关 (18080) 或 AetherForge (4000) 服务已启动[/yellow]")
                return 1
    if subcmd == "fabric":
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        return subprocess.call(["uv", "run", "omlxc", "fabric", "inspect"], cwd=str(omlxc_root))
    if subcmd == "triage":
        prompt = getattr(args, "prompt", "")
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        return subprocess.call(["uv", "run", "omlxc", "fabric", "triage", prompt], cwd=str(omlxc_root))
    if subcmd == "vram":
        model = getattr(args, "model", "coding")
        tokens = str(getattr(args, "tokens", 32768))
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        return subprocess.call(["uv", "run", "omlxc", "fabric", "vram", model, tokens], cwd=str(omlxc_root))
    if subcmd == "warm":
        model = getattr(args, "model", "coding")
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        return subprocess.call(["uv", "run", "omlxc", "fabric", "warm", "--model", model], cwd=str(omlxc_root))
    if subcmd == "route":
        model = getattr(args, "model", None)
        if not model:
            console.print("[red]缺少 --model[/red]")
            return 1
        try:
            with _urlopen_safe(f"{_mesh_router_url()}/route?model={model}") as resp:
                console.print_json(data=json.loads(resp.read()))
                return 0
        except Exception as exc:
            console.print(f"[red]路由选择失败: {exc}[/red]")
            return 1
    if subcmd == "cache":
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        bench_script = _workspace_root() / "bin" / "demo" / "live_context_and_cache_benchmark.py"
        return subprocess.call(["uv", "run", "--project", str(omlxc_root), "python", str(bench_script)])
    if subcmd == "dflash":
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        bench_script = _workspace_root() / "bin" / "demo" / "live_cluster_wide_benchmark.py"
        return subprocess.call(["uv", "run", "--project", str(omlxc_root), "python", str(bench_script)])
    if subcmd == "cluster":
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        bench_script = _workspace_root() / "bin" / "demo" / "live_cluster_wide_benchmark.py"
        return subprocess.call(["uv", "run", "--project", str(omlxc_root), "python", str(bench_script)])
    if subcmd in {"tree", "stream", "swarm"}:
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        bench_script = omlxc_root / "examples" / "live_nextgen_compute_engine_benchmark.py"
        return subprocess.call(["uv", "run", "--project", str(omlxc_root), "python", str(bench_script)])
    if subcmd in {"hud", "heatmap"}:
        try:
            from cockpit.tui.compute_hud import render_compute_hud_panel

            console.print(render_compute_hud_panel())
            return 0
        except Exception as exc:
            console.print(f"[red]渲染 HUD 失败: {exc}[/red]")
            return 1
    if subcmd in {"dma", "lora"}:
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        bench_script = _workspace_root() / "bin" / "demo" / "live_nextgen_compute_engine_benchmark.py"
        return subprocess.call(["uv", "run", "--project", str(omlxc_root), "python", str(bench_script)])
    if subcmd == "compact":
        model = getattr(args, "model", "coding")
        tokens = str(getattr(args, "tokens", 32768))
        avail = str(getattr(args, "available_mb", 4096))
        try:
            preflight_delegation(ws_root, project="omlxc", command="uv")
        except DelegationPreflightError as exc:
            console.print(f"[red]前置检查失败: {exc}[/red]")
            return 1
        omlxc_root = _workspace_root() / "projects" / "omlxc"
        return subprocess.call(
            ["uv", "run", "omlxc", "fabric", "compact", "--model", model, "--tokens", tokens, "--available-mb", avail],
            cwd=str(omlxc_root),
        )
    if subcmd == "serve":
        console.print(
            "[yellow]Mesh 网关服务请通过 aetherforge 或 LaunchAgent: com.user.omlx-smart-gateway 管理[/yellow]"
        )
        return 0

    console.print("[red]未知 mesh 子命令[/red]")
    console.print(
        "可用: nodes, status, fabric, hud, heatmap, dma, lora, cache, dflash, cluster, tree, stream, swarm, triage <PROMPT>, vram <MODEL> <TOKENS>, compact, route --model <MODEL>, serve"
    )
    return 1
