"""Cockpit entrypoint for executable agent governance workflows."""

from __future__ import annotations

import subprocess
from pathlib import Path
from cockpit.env_resolver import get_workspace_root as _get_workspace_root

WORKSPACE = _get_workspace_root()


def cmd_agent_workflow(args) -> int:
    """Delegate to the workspace agent-workflow runner."""
    forwarded = getattr(args, "agent_workflow_args", None)
    if forwarded is None:
        forwarded = getattr(args, "agent_args", [])
    forwarded = list(forwarded or [])
    if not forwarded:
        forwarded = ["bootstrap"] if getattr(args, "command", "") == "agent" else ["list"]
    command = [
        "uv",
        "run",
        "--with",
        "pyyaml",
        "python",
        str(WORKSPACE / "bin" / "agent-workflow.py"),
        *forwarded,
    ]
    return subprocess.call(command, cwd=str(WORKSPACE))
