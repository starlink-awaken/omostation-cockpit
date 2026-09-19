"""Cockpit scene v2 commands — lifecycle management, execution, calibration, graph.

cockpit scene lifecycle [list|status|promote|demote|validate] [--scene-id X] [--to Y]
cockpit scene execute <scene_id> [--signal <json>] [--dry-run]
cockpit scene calibrate [scene_id] [--window 30]
cockpit scene graph
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from cockpit.env_resolver import get_workspace_root as _get_workspace_root
WORKSPACE_ROOT = _get_workspace_root()
JOURNEY_ENGINE = WORKSPACE_ROOT / "bin" / "ssot" / "journey-engine.py"
CALIBRATION_ENGINE = WORKSPACE_ROOT / "bin" / "ssot" / "calibration-engine.py"
SCENE_GRAPH = WORKSPACE_ROOT / "bin" / "ssot" / "scene-graph.py"
SCENE_CARD_LIFECYCLE = WORKSPACE_ROOT / "bin" / "ssot" / "scene-card-lifecycle.py"


def _load_scene(scene_id: str) -> dict[str, Any] | None:
    import yaml

    scenes_dir = WORKSPACE_ROOT / ".omo" / "_truth" / "scenarios" / "v3"
    if not scenes_dir.is_dir():
        return None
    for p in scenes_dir.glob("*.yaml"):
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
    scenes_dir = WORKSPACE_ROOT / ".omo" / "_truth" / "scenarios" / "v3"
    if scenes_dir.is_dir():
        for p in sorted(scenes_dir.glob("*.yaml")):
            try:
                with open(p, encoding="utf-8") as f:
                    docs = list(yaml.safe_load_all(f))
                body = docs[-1] if len(docs) > 1 else docs[0]
                if isinstance(body, dict):
                    scenes.append(body)
            except Exception:
                continue
    return scenes


def cmd_lifecycle(args: argparse.Namespace) -> int:
    """Scene lifecycle subcommand dispatcher."""
    action = args.lifecycle_action or "list"

    if action == "list":
        scenes = _load_all_scenes()
        if getattr(args, "domain", None):
            scenes = [s for s in scenes if s.get("domain") == args.domain]
        if not scenes:
            print("No scenes found.")
            return 0
        print(f"{'ID':<40} {'Class':<12} {'Lifecycle':<12} {'Activation':<12} {'Domain':<12}")
        print("-" * 92)
        for s in scenes:
            print(
                f"{s.get('scene_id', '?'):<40} {s.get('scene_class', '?'):<12} "
                f"{s.get('lifecycle', '?'):<12} {s.get('activation', '?'):<12} {s.get('domain', '?'):<12}"
            )
        print(f"\nTotal: {len(scenes)} scenes")
        return 0

    if action == "status":
        if not args.scene_id:
            print("ERROR: --scene-id required", file=sys.stderr)
            return 2
        card = _load_scene(args.scene_id)
        if not card:
            print(f"ERROR: scene not found: {args.scene_id}", file=sys.stderr)
            return 2
        print(f"Scene: {card.get('scene_id', '?')}")
        for k in ["name", "scene_class", "scene_type", "domain", "lifecycle", "activation", "owner", "approver"]:
            print(f"  {k.capitalize():<12}: {card.get(k, '?')}")
        caps = card.get("runtime", {}).get("sandbox", {}).get("capabilities", [])
        if caps:
            print("  Capabilities:")
            for c in caps:
                print(f"    - {c}")
        topo = card.get("topology", {})
        if topo.get("upstream"):
            print(f"  Upstream:    {', '.join(u.get('scene', '?') for u in topo['upstream'])}")
        if topo.get("downstream"):
            print(f"  Downstream:  {', '.join(d.get('scene', '?') for d in topo['downstream'])}")
        return 0

    if action == "promote":
        if not args.scene_id or not args.target_level:
            print("ERROR: --scene-id and --to required", file=sys.stderr)
            return 2
        card = _load_scene(args.scene_id)
        if not card:
            print(f"ERROR: scene not found: {args.scene_id}", file=sys.stderr)
            return 2
        scenes_dir = WORKSPACE_ROOT / ".omo" / "_truth" / "scenarios" / "v3"
        card_path = scenes_dir / f"{args.scene_id}.yaml"
        cmd = [
            sys.executable, str(SCENE_CARD_LIFECYCLE), "transition",
            "--scene-card", str(card_path), "--tier", args.target_level,
            "--actor", "cockpit",
        ]
        return subprocess.run(cmd, capture_output=False, cwd=str(WORKSPACE_ROOT)).returncode

    if action == "demote":
        return cmd_lifecycle(
            argparse.Namespace(
                lifecycle_action="promote",
                scene_id=args.scene_id,
                target_level=args.target_level,
            )
        )

    if action == "validate":
        if not args.scene_id:
            print("ERROR: --scene-id required", file=sys.stderr)
            return 2
        card = _load_scene(args.scene_id)
        if not card:
            print(f"ERROR: scene not found: {args.scene_id}", file=sys.stderr)
            return 2
        errors = []
        for field in ["schema", "scene_id", "name", "lifecycle", "activation", "owner"]:
            if not card.get(field):
                errors.append(f"missing required field: {field}")
        if card.get("schema") != "scene-card/v3":
            errors.append(f"schema is '{card.get('schema')}', expected 'scene-card/v3'")
        print(
            json.dumps(
                {"scene_id": args.scene_id, "valid": len(errors) == 0, "errors": errors},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if len(errors) == 0 else 1

    print(f"ERROR: unknown action: {action}", file=sys.stderr)
    return 1


def cmd_execute(args: argparse.Namespace) -> int:
    """Execute a scene journey."""
    if not args.scene_id:
        print("ERROR: scene_id required", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(JOURNEY_ENGINE), "execute", args.scene_id]
    if args.signal and args.signal != "{}":
        cmd.extend(["--signal", args.signal])
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    return subprocess.run(cmd, capture_output=False, cwd=str(WORKSPACE_ROOT)).returncode


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Compute calibration score for a scene."""
    cmd = [sys.executable, str(CALIBRATION_ENGINE), "compute"]
    if args.scene_id:
        cmd.extend(["--scene-id", args.scene_id])
    cmd.extend(["--window", str(args.window)])
    return subprocess.run(cmd, capture_output=False, cwd=str(WORKSPACE_ROOT)).returncode


def cmd_graph(args: argparse.Namespace) -> int:
    """Build and display scene graph."""
    cmd = [sys.executable, str(SCENE_GRAPH), "build"]
    return subprocess.run(cmd, capture_output=False, cwd=str(WORKSPACE_ROOT)).returncode


def cmd_scene_lifecycle(args: argparse.Namespace) -> int:
    """Main dispatch for cockpit scene v2 subcommands."""
    sub = getattr(args, "scene_command", None)

    if sub == "lifecycle":
        return cmd_lifecycle(args)
    elif sub == "execute":
        return cmd_execute(args)
    elif sub == "calibrate":
        return cmd_calibrate(args)
    elif sub == "graph":
        return cmd_graph(args)
    else:
        return cmd_lifecycle(
            argparse.Namespace(
                lifecycle_action="list",
                scene_id=None,
                target_level=None,
                domain=None,
            )
        )
