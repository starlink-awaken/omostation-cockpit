"""
cockpit.commands.dashboard — 现代化 Web Dashboard 管理与服务启动

功能特性:
  1. 端口冲突自动探测与自愈 (Auto-healing)
  2. 纯净结构化输出 (--json)
  3. 无头/CI/脚本友好 (--no-open)
  4. 状态探测与健康检查 (--status-only)
  5. 预检模式 (--dry-run)
  6. ExitCode 标准化 (ExitCode.SUCCESS, ExitCode.CONFIG_ERROR, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib import request as urlrequest

from rich.console import Console

from cockpit.commands.base import is_interactive, output_result
from cockpit.domain.exit_codes import ExitCode
from cockpit.env_resolver import get_workspace_root as _get_workspace_root

console = Console()


def is_port_available(host: str, port: int) -> bool:
    """检测指定 host 与 port 是否可被绑定（未被占用）"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def is_dashboard_alive(url: str, timeout: float = 1.5) -> bool:
    """检测指定 URL 是否正在响应 Cockpit Dashboard HTTP 请求"""
    try:
        r = urlrequest.urlopen(url, timeout=timeout)
        return getattr(r, "status", 200) == 200
    except Exception:
        return False


def find_available_port(host: str, start_port: int, max_attempts: int = 10) -> int | None:
    """寻找可用端口，自愈递增"""
    for p in range(start_port, start_port + max_attempts):
        if is_port_available(host, p):
            return p
    return None


def cmd_dashboard(args: argparse.Namespace) -> int:
    """启动或检视 Cockpit Dashboard"""
    as_json = getattr(args, "json", False) or getattr(args, "global_output", "text") == "json"
    is_dry_run = getattr(args, "dry_run", False)
    status_only = getattr(args, "status_only", False)
    no_open = getattr(args, "no_open", False)
    host = getattr(args, "host", "127.0.0.1") or "127.0.0.1"

    raw_port = getattr(args, "port", None) or os.environ.get("COCKPIT_DASHBOARD_PORT", 8090)
    try:
        port = int(raw_port)
    except ValueError:
        if as_json:
            print(json.dumps({"ok": False, "error": f"Invalid port: {raw_port}"}))
        else:
            console.print(f"[red]❌ 无效端口: {raw_port}[/]")
        return ExitCode.CONFIG_ERROR

    url = f"http://{host}:{port}/bos"
    workspace_root = _get_workspace_root()

    # 1. 探针：检查是否已经在运行
    alive = is_dashboard_alive(url, timeout=1.0)

    # ── Status-Only 模式 ──
    if status_only:
        payload = {
            "running": alive,
            "url": url,
            "host": host,
            "port": port,
        }
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if alive:
                console.print(f"[green]✅ Dashboard 正在运行: [cyan]{url}[/][/]")
            else:
                console.print(f"[yellow]⚪ Dashboard 未运行 (目标: {url})[/]")
        return ExitCode.SUCCESS if alive else ExitCode.SERVICE_UNAVAILABLE

    # ── Dry-Run 预检模式 ──
    if is_dry_run:
        port_free = is_port_available(host, port)
        payload = {
            "dry_run": True,
            "url": url,
            "host": host,
            "port": port,
            "alive": alive,
            "port_available": port_free,
            "ready": alive or port_free,
        }
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            console.print("[bold cyan]🔍 [Dry-Run] 预检 Dashboard 启动环境[/]")
            console.print(f"  • 目标地址: [cyan]{url}[/]")
            status_text = "[green]已在运行[/]" if alive else "[dim]未运行[/]"
            port_text = "[green]可用[/]" if port_free else "[yellow]已占用[/]"
            console.print(f"  • 存活状态: {status_text}")
            console.print(f"  • 端口状态: {port_text}")
        return ExitCode.SUCCESS

    # 2. 如果已存活，直接打开或提示
    if alive:
        if as_json:
            print(json.dumps({"ok": True, "running": True, "url": url, "port": port}, ensure_ascii=False))
        else:
            console.print(f"[green]✅ Dashboard 已在运行: [cyan]{url}[/][/]")
            if not no_open:
                webbrowser.open(url)
        return ExitCode.SUCCESS

    # 3. 端口占用自愈探测
    if not is_port_available(host, port):
        # 用户未强制传参时，尝试自动寻找替代端口
        if not getattr(args, "port", None):
            next_port = find_available_port(host, port + 1, max_attempts=10)
            if next_port:
                if not as_json:
                    console.print(f"[yellow]⚠️ 默认端口 {port} 被占用，自动自愈切换至端口 {next_port}[/]")
                port = next_port
                url = f"http://{host}:{port}/bos"
            else:
                if as_json:
                    print(json.dumps({"ok": False, "error": f"Port {port} and fallback ports all occupied"}))
                else:
                    console.print(f"[red]❌ 端口 {port} 及其后 10 个端口均被占用，无法启动 Dashboard[/]")
                return ExitCode.RESOURCE_EXHAUSTED
        else:
            if as_json:
                print(json.dumps({"ok": False, "error": f"Specified port {port} is already in use"}))
            else:
                console.print(f"[red]❌ 指定端口 {port} 已被占用，请更换端口或停止占用进程[/]")
            return ExitCode.RESOURCE_EXHAUSTED

    # 4. 准备启动子进程
    if not as_json:
        console.print(f"[dim]正在启动 Cockpit Dashboard ({host}:{port})...[/]")

    cmd = [sys.executable, "-m", "cockpit.dashboard_server"]
    child_env = os.environ.copy()
    child_env["COCKPIT_DASHBOARD_PORT"] = str(port)
    child_env["COCKPIT_DASHBOARD_HOST"] = host

    try:
        from cockpit.web.memory_env import apply_memory_os_env

        apply_memory_os_env()
        child_env = os.environ.copy()
    except Exception:
        pass

    import tempfile

    _server_err = tempfile.NamedTemporaryFile(  # 失败时回读诊断 (原先 DEVNULL 使启动死因不可见)
        prefix="cockpit-dashboard-err-", suffix=".log", delete=False
    )
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(workspace_root),
            stdout=subprocess.DEVNULL,
            stderr=_server_err,
            env=child_env,
        )
    except FileNotFoundError:
        if as_json:
            print(json.dumps({"ok": False, "error": "Dashboard server module not found"}))
        else:
            console.print("[red]❌ 无法启动 Dashboard (模块不存在)[/]")
        return ExitCode.SERVICE_UNAVAILABLE

    # 轮询等待就绪 — 首次启动需加载全部 web router (实测冷启动 >5s), 固定 2s 探活会误杀健康进程
    # (2026-09-24 链路D走查: 包装器报"无法连接"但手动直起同一命令 200)
    ready = False
    for _ in range(40):  # 最多 20s
        if proc.poll() is not None:
            break  # 子进程已退出 (如端口冲突), 下方报错
        if is_dashboard_alive(url, timeout=1.0):
            ready = True
            break
        time.sleep(0.5)
    if not ready:
        proc.terminate()
        _server_err.close()
        try:
            err_tail = Path(_server_err.name).read_text(errors="replace").strip()[-400:]
        except OSError:
            err_tail = ""
        if err_tail and not as_json:
            console.print(f"[dim]server stderr 尾部: {err_tail}[/]")
        if as_json:
            print(json.dumps({"ok": False, "error": f"Failed to connect to dashboard at {url}"}))
        else:
            console.print(f"[red]❌ 无法连接到 Dashboard: {url}[/]")
        return ExitCode.SERVICE_UNAVAILABLE

    # 启动成功
    if as_json:
        print(json.dumps({"ok": True, "running": True, "url": url, "port": port, "pid": proc.pid}, ensure_ascii=False))
        return ExitCode.SUCCESS

    if not no_open:
        webbrowser.open(url)

    console.print(f"[green]✅ Dashboard 已启动: [cyan]{url}[/][/]")
    console.print("[dim]按 Ctrl+C 停止服务[/]")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        console.print("\n[yellow]Dashboard 已停止[/]")
    return ExitCode.SUCCESS
