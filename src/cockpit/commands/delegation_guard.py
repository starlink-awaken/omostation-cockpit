"""cockpit.commands.delegation_guard — 委派命令连通性预检 (P1 委派可靠性加固).

职责:
  · 在执行薄委派/自定义委派前, 快速校验目标项目/脚本/端口是否可达;
  · 失败时给出可操作的修复提示, 而不是静默返回 cryptic returncode.
"""

from __future__ import annotations

import shutil
import socket
from pathlib import Path


def check_project_exists(workspace_root: Path, project_name: str) -> bool:
    """检查 workspace 下某个子项目是否存在且像有效 checkout."""
    project = workspace_root / "projects" / project_name
    if not project.is_dir():
        return False
    return (project / "pyproject.toml").is_file() or (project / "setup.py").is_file()


def check_command_available(command: str) -> bool:
    """检查命令是否在当前 PATH 中可用."""
    return shutil.which(command) is not None


def check_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 端口探活, 用于 mesh/agora 等 HTTP 服务预检."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return bool(sock.connect_ex((host, port)) == 0)
    except (OSError, ValueError):
        return False


class DelegationPreflightError(Exception):
    """委派前置校验失败."""


def preflight_delegation(
    workspace_root: Path,
    *,
    project: str | None = None,
    command: str | None = None,
    port: tuple[str, int] | None = None,
    port_timeout: float = 2.0,
) -> None:
    """批量执行委派预检, 任一失败抛 DelegationPreflightError.

    Args:
      workspace_root: 工作区根.
      project: 子项目名, 如 "omo" / "omlxc" / "runtime".
      command: 可执行文件名, 如 "uv" / "python3".
      port: (host, port) 元组, 用于 HTTP/mesh 服务探活.
      port_timeout: 端口超时秒数.

    Raises:
      DelegationPreflightError: 首个失败的校验错误信息.
    """
    if project is not None and not check_project_exists(workspace_root, project):
        raise DelegationPreflightError(
            f"项目缺失: projects/{project} 不存在或不是有效 checkout"
        )

    if command is not None and not check_command_available(command):
        raise DelegationPreflightError(f"命令不可用: {command} 不在 PATH 中")

    if port is not None:
        host, port_number = port
        if not check_port_open(host, port_number, timeout=port_timeout):
            raise DelegationPreflightError(
                f"端口未监听: {host}:{port_number} 不可达 (timeout={port_timeout}s)"
            )
