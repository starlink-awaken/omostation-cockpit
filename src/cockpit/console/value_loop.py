"""Value Loop overview — read-only projection of value-loop-standard.yaml.

V1: visualization only, no execution engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cockpit.compat import WORKSPACE_ROOT


def value_loop_overview(workspace: Path | None = None) -> dict[str, Any]:
    """Read value-loop-standard.yaml and dimension-system.yaml for overview.

    Returns the 5-stage cycle definition, north star metrics, broken chains,
    and 12-dimension targets.
    """
    ws = workspace or WORKSPACE_ROOT
    result: dict[str, Any] = {
        "ok": True,
        "degraded": False,
        "stages": [],
        "north_star": {},
        "broken_chains": [],
        "dimensions": [],
    }

    vl_path = ws / ".omo" / "standards" / "value-loop-standard.yaml"
    if vl_path.exists():
        try:
            vl = yaml.safe_load(vl_path.read_text(encoding="utf-8"))
            result["stages"] = vl.get("stages", [])
            result["north_star"] = vl.get("north_star", {})
            result["broken_chains"] = vl.get("broken_chains", [])
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)[:200]
            result["degraded"] = True

    dims_path = ws / ".omo" / "standards" / "dimension-system.yaml"
    if dims_path.exists():
        try:
            dims = yaml.safe_load(dims_path.read_text(encoding="utf-8"))
            result["dimensions"] = dims.get("dimensions", [])
        except Exception as e:
            result["degraded"] = True
            result.setdefault("errors", []).append(f"dimensions: {str(e)[:100]}")

    return result
