"""Tests for cockpit compute command and aetherforge integration."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

from cockpit.commands import compute as compute_mod


def test_check_aetherforge_resolves_gateway_paths():
    """Verify _check_aetherforge() resolves workspace and inserts gateway & mesh paths into sys.path."""
    res = compute_mod._check_aetherforge()
    assert res is True

    # Verify gateway and mesh paths are in sys.path
    found_gateway = any(p.endswith(os.path.join("packages", "gateway", "src")) for p in sys.path)
    found_mesh = any(p.endswith(os.path.join("packages", "mesh", "src")) for p in sys.path)
    found_aether = any(p.endswith(os.path.join("projects", "aetherforge", "src")) for p in sys.path)

    assert found_gateway, "packages/gateway/src should be inserted in sys.path"
    assert found_mesh, "packages/mesh/src should be inserted in sys.path"
    assert found_aether, "projects/aetherforge/src should be inserted in sys.path"


def test_aetherforge_interpreter_selection(tmp_path: Path):
    """Verify _aetherforge() uses venv python when present, otherwise sys.executable."""
    # When workspace_root is None
    cmd_none = compute_mod._aetherforge(None)
    assert cmd_none == [sys.executable, "-m", "aetherforge.cli"]

    # When workspace_root has no venv python
    cmd_no_venv = compute_mod._aetherforge(tmp_path)
    assert cmd_no_venv == [sys.executable, "-m", "aetherforge.cli"]

    # When workspace_root has venv python
    fake_venv_python = tmp_path / "projects" / "aetherforge" / ".venv" / "bin" / "python3"
    fake_venv_python.parent.mkdir(parents=True, exist_ok=True)
    fake_venv_python.write_text("#!/bin/sh\n")

    cmd_with_venv = compute_mod._aetherforge(tmp_path)
    assert cmd_with_venv == [str(fake_venv_python), "-m", "aetherforge.cli"]


def test_cmd_compute_injects_pythonpath(monkeypatch):
    """Verify cmd_compute() includes packages/gateway/src and packages/mesh/src in PYTHONPATH."""
    captured_subprocess: dict = {}

    def mock_subprocess_run(cmd, env=None, capture_output=False, text=True):
        captured_subprocess["cmd"] = cmd
        captured_subprocess["env"] = env
        mock_result = MagicMock()
        mock_result.returncode = 0
        return mock_result

    monkeypatch.setattr(compute_mod.subprocess, "run", mock_subprocess_run)

    args = argparse.Namespace(
        compute_command="gateway",
        extra=["list"],
    )

    rc = compute_mod.cmd_compute(args)
    assert rc == 0
    assert "cmd" in captured_subprocess
    assert captured_subprocess["cmd"][-2:] == ["gateway", "list"]

    # Check env PYTHONPATH
    env = captured_subprocess.get("env") or {}
    pythonpath = env.get("PYTHONPATH", "")
    assert "packages/gateway/src" in pythonpath
    assert "packages/mesh/src" in pythonpath
    assert "projects/aetherforge/src" in pythonpath


def test_cmd_compute_passes_workspace_root_to_aetherforge(monkeypatch, tmp_path: Path):
    """Verify cmd_compute() passes workspace_root to _aetherforge()."""
    mock_aether = MagicMock(return_value=["/custom/python", "-m", "aetherforge.cli"])
    monkeypatch.setattr(compute_mod, "_aetherforge", mock_aether)

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(compute_mod.subprocess, "run", mock_run)

    args = argparse.Namespace(
        compute_command="mesh",
        extra=["status"],
    )

    rc = compute_mod.cmd_compute(args)
    assert rc == 0
    assert mock_aether.call_count == 1
    # workspace_root passed should be a Path instance
    ws_root = mock_aether.call_args[0][0]
    assert isinstance(ws_root, Path)
    assert (ws_root / "docs" / "project-registry.yaml").is_file()


def test_cmd_compute_missing_subcmd():
    """Verify cmd_compute() returns 1 when compute_command is empty."""
    args = argparse.Namespace(
        compute_command=None,
        extra=[],
    )
    rc = compute_mod.cmd_compute(args)
    assert rc == 1


def test_cmd_compute_aetherforge_not_installed(monkeypatch):
    """Verify cmd_compute() returns 1 when aetherforge is not importable."""
    monkeypatch.setattr(compute_mod, "_check_aetherforge", lambda: False)
    args = argparse.Namespace(
        compute_command="gateway",
        extra=["list"],
    )
    rc = compute_mod.cmd_compute(args)
    assert rc == 1
