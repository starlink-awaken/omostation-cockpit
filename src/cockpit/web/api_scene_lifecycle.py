"""Cockpit Web API — scene lifecycle management endpoints.

Routes:
  GET  /api/scene-lifecycle/list
  GET  /api/scene-lifecycle/status/{scene_id}
  POST /api/scene-lifecycle/execute
  POST /api/scene-lifecycle/promote
  POST /api/scene-lifecycle/demote
  GET  /api/scene-lifecycle/graph
  GET  /api/scene-lifecycle/metrics/{scene_id}
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/scene-lifecycle", tags=["scene-lifecycle"])

WORKSPACE_ROOT = Path(__file__).resolve().parents[5]
SCENES_DIR = WORKSPACE_ROOT / ".omo" / "_truth" / "scenarios" / "v3"
JOURNEY_ENGINE = WORKSPACE_ROOT / "bin" / "ssot" / "journey-engine.py"
CALIBRATION_ENGINE = WORKSPACE_ROOT / "bin" / "ssot" / "calibration-engine.py"
SCENE_GRAPH = WORKSPACE_ROOT / "bin" / "ssot" / "scene-graph.py"
SCENE_CARD_LIFECYCLE = WORKSPACE_ROOT / "bin" / "ssot" / "scene-card-lifecycle.py"


def _load_scene(scene_id: str) -> dict[str, Any] | None:
    import yaml

    if not SCENES_DIR.is_dir():
        return None
    for p in SCENES_DIR.glob("*.yaml"):
        try:
            with open(p, encoding="utf-8") as f:
                docs = list(yaml.safe_load_all(f))
            body = docs[-1] if len(docs) > 1 else docs[0]
            if isinstance(body, dict) and body.get("scene_id") == scene_id:
                return body
        except Exception:
            continue
    return None


def _load_all_scenes() -> list[dict[str, Any]]:
    import yaml

    scenes = []
    if SCENES_DIR.is_dir():
        for p in sorted(SCENES_DIR.glob("*.yaml")):
            try:
                with open(p, encoding="utf-8") as f:
                    docs = list(yaml.safe_load_all(f))
                body = docs[-1] if len(docs) > 1 else docs[0]
                if isinstance(body, dict):
                    scenes.append(body)
            except Exception:
                continue
    return scenes


@router.get("/list")
async def list_scenes(domain: str | None = None) -> dict[str, Any]:
    """List all v3 scenes."""
    scenes = _load_all_scenes()
    if domain:
        scenes = [s for s in scenes if s.get("domain") == domain]
    return {"ok": True, "count": len(scenes), "scenes": scenes}


@router.get("/status/{scene_id}")
async def scene_status(scene_id: str) -> dict[str, Any]:
    """Get scene card status."""
    card = _load_scene(scene_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"Scene not found: {scene_id}")
    return {"ok": True, "scene": card}


@router.post("/execute")
async def execute_scene(request: dict[str, Any]) -> dict[str, Any]:
    """Execute a scene journey."""
    scene_id = request.get("scene_id")
    if not scene_id:
        raise HTTPException(status_code=400, detail="scene_id required")
    signal = request.get("signal", {})
    dry_run = request.get("dry_run", False)

    cmd = [sys.executable, str(JOURNEY_ENGINE), "execute", scene_id]
    if signal:
        cmd.extend(["--signal", json.dumps(signal)])
    if dry_run:
        cmd.append("--dry-run")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(WORKSPACE_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": stdout.decode(),
            "error": stderr.decode(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/promote")
async def promote_scene(request: dict[str, Any]) -> dict[str, Any]:
    """Promote a scene to a higher lifecycle level."""
    scene_id = request.get("scene_id")
    target_level = request.get("target_level")
    if not scene_id or not target_level:
        raise HTTPException(status_code=400, detail="scene_id and target_level required")

    card_path = SCENES_DIR / f"{scene_id}.yaml"
    if not card_path.exists():
        raise HTTPException(status_code=404, detail=f"Scene card not found: {scene_id}")

    cmd = [
        sys.executable, str(SCENE_CARD_LIFECYCLE), "transition",
        "--scene-card", str(card_path), "--tier", target_level,
        "--actor", "cockpit-api",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WORKSPACE_ROOT))
        return {"ok": result.returncode == 0, "output": result.stdout, "error": result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/demote")
async def demote_scene(request: dict[str, Any]) -> dict[str, Any]:
    """Demote a scene to a lower lifecycle level."""
    return await promote_scene(request)


@router.get("/graph")
async def scene_graph() -> dict[str, Any]:
    """Build scene graph from topology."""
    try:
        result = subprocess.run(
            [sys.executable, str(SCENE_GRAPH), "build"],
            capture_output=True, text=True, cwd=str(WORKSPACE_ROOT),
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"ok": False, "error": result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/metrics/{scene_id}")
async def scene_metrics(scene_id: str, window: int = 30) -> dict[str, Any]:
    """Get calibration metrics for a scene."""
    try:
        result = subprocess.run(
            [sys.executable, str(CALIBRATION_ENGINE), "compute",
             "--scene-id", scene_id, "--window", str(window)],
            capture_output=True, text=True, cwd=str(WORKSPACE_ROOT),
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return {"ok": False, "error": result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}
