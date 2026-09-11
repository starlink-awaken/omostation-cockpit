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


# ── Human adjudication flow (escalation queue + accept/reject) ────

OBSERVABILITY_EVENTS = WORKSPACE_ROOT / ".omo" / "_delivery" / "observability" / "events.jsonl"
OUTCOME_RECORDER = WORKSPACE_ROOT / "bin" / "ssot" / "scene-outcome-recorder.py"


@router.get("/escalations")
async def escalation_queue(limit: int = 20) -> dict[str, Any]:
    """List pending scene escalations from the observability event plane."""
    if not OBSERVABILITY_EVENTS.is_file():
        return {"ok": True, "count": 0, "escalations": []}

    escalations: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    with open(OBSERVABILITY_EVENTS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") != "scene.escalated":
                continue
            run_id = str(evt.get("trace_id", ""))
            if run_id in seen_run_ids:
                continue
            seen_run_ids.add(run_id)
            payload = evt.get("payload", {})
            escalations.append({
                "run_id": run_id,
                "scene_id": payload.get("scene_id") or evt.get("source", ""),
                "journey_id": payload.get("journey_id"),
                "confidence": payload.get("confidence"),
                "ts": evt.get("ts"),
                "trace_steps": payload.get("trace_steps"),
            })

    escalations.sort(key=lambda e: e.get("ts") or "", reverse=True)
    return {"ok": True, "count": len(escalations), "escalations": escalations[:limit]}


@router.post("/adjudicate")
async def adjudicate_escalation(request: dict[str, Any]) -> dict[str, Any]:
    """Record a human adjudication (accept/reject) for an escalated scene run.

    Bridges to scene-outcome-recorder (trust loop + value-evidence bridge).
    """
    scene_id = request.get("scene_id")
    run_id = request.get("run_id")
    decision = request.get("decision")  # accept | reject
    notes = request.get("notes", "")
    review_seconds = request.get("review_seconds")
    saved_seconds = request.get("saved_seconds")

    if not scene_id or not run_id or decision not in ("accept", "reject"):
        raise HTTPException(
            status_code=400,
            detail="scene_id, run_id, and decision (accept|reject) required",
        )

    adjudication = "accepted" if decision == "accept" else "rejected"
    card_path = SCENES_DIR / f"{scene_id}.yaml"
    if not card_path.is_file():
        raise HTTPException(status_code=404, detail=f"Scene card not found: {scene_id}")

    cmd = [
        sys.executable, str(OUTCOME_RECORDER), "record",
        "--scene-card", str(card_path),
        "--run-id", str(run_id),
        "--adjudication", adjudication,
        "--actor", "cockpit-operator",
    ]
    if notes:
        cmd.extend(["--notes", str(notes)])
    if review_seconds is not None:
        cmd.extend(["--review-seconds", str(int(review_seconds))])
    if saved_seconds is not None:
        cmd.extend(["--saved-seconds", str(int(saved_seconds))])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WORKSPACE_ROOT))
        return {
            "ok": result.returncode == 0,
            "adjudication": adjudication,
            "output": result.stdout[-500:],
            "error": result.stderr[-200:] if result.returncode != 0 else None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
