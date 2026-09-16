"""MOF Auditor — full audit and single-constraint evaluation.

Full audit: subprocess ecos-constraint audit --json (asyncio.to_thread)
Single eval: in-process MOFPolicyCompiler.evaluate_*

V1: no incremental audit, no batch evaluate.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from cockpit.compat import WORKSPACE_ROOT
from cockpit.console.models import MofViolation

logger = logging.getLogger("cockpit.console.mof_auditor")

CONSTRAINTS_PATH = WORKSPACE_ROOT / "projects" / "ecos" / "src" / "ecos" / "ssot" / "registry" / "L0-constraints.yaml"
DIMENSIONS_PATH = WORKSPACE_ROOT / ".omo" / "standards" / "dimension-system.yaml"
VALUE_LOOP_PATH = WORKSPACE_ROOT / ".omo" / "standards" / "value-loop-standard.yaml"


class MofAuditor:
    """MOF constraint auditing and evaluation."""

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace or WORKSPACE_ROOT

    def full_audit(self, family: str | None = None, max_rules: int = 500) -> dict[str, Any]:
        """Run full audit via subprocess. Returns normalized results."""
        start = __import__("time").perf_counter()

        try:
            # Include ecos src in PYTHONPATH so the subprocess can import the module
            _ecos_src = str(self._workspace / "projects" / "ecos" / "src")
            _pp = f"{_ecos_src}:{os.environ.get('PYTHONPATH', '')}"
            _env = {**os.environ, "PYTHONPATH": _pp}

            result = subprocess.run(
                [
                    sys.executable, "-m", "ecos.cli.constraint",
                    "audit", "--json", "--layer", "L3",
                    str(self._workspace),
                ],
                cwd=self._workspace,
                env=_env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            elapsed = (__import__("time").perf_counter() - start) * 1000

            if result.returncode not in (0, 1):  # 1 = violations found
                return {
                    "ok": False,
                    "error_code": "MOF_AUDIT_FAILED",
                    "error": result.stderr[:500] if result.stderr else f"exit code {result.returncode}",
                    "elapsed_ms": round(elapsed, 1),
                    "degraded": True,
                }

            output = json.loads(result.stdout)
            violations_raw = output.get("violations", [])

            violations: list[MofViolation] = []
            by_family: dict[str, dict[str, int]] = {}

            for v in violations_raw:
                code = v.get("violation_code", "UNKNOWN")
                fam = _normalize_family(code)
                violations.append(MofViolation(
                    constraint_id=code,
                    family=fam,
                    severity=v.get("severity", "error"),
                    target=v.get("file", ""),
                    message=v.get("summary", ""),
                    fix_hint=v.get("remediation"),
                ))
                if fam not in by_family:
                    by_family[fam] = {"total": 0, "violations": 0}
                by_family[fam]["violations"] += 1

            for fam in by_family:
                by_family[fam]["total"] = by_family[fam].get("total", 0) + by_family[fam]["violations"]

            return {
                "ok": True,
                "total_rules": output.get("files_scanned", 0),
                "checked": len(violations_raw),
                "violations": [v.__dict__ for v in violations],
                "by_family": by_family,
                "elapsed_ms": round(elapsed, 1),
                "source": "ecos-constraint",
                "degraded": False,
            }

        except FileNotFoundError:
            return {
                "ok": False,
                "error_code": "MOF_UNAVAILABLE",
                "error": "ecos package not found",
                "elapsed_ms": 0,
                "degraded": True,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error_code": "TIMEOUT",
                "error": "Audit timed out after 180s",
                "elapsed_ms": 180_000,
                "degraded": True,
            }
        except (json.JSONDecodeError, Exception) as e:
            return {
                "ok": False,
                "error_code": "MOF_UNAVAILABLE",
                "error": str(e)[:500],
                "elapsed_ms": 0,
                "degraded": True,
            }

    def evaluate(
        self,
        *,
        constraint_id: str,
        target: str,
        target_kind: str,
        caller_layer: str = "L3",
        caller_domain: str = "default",
    ) -> dict[str, Any]:
        """Evaluate a single constraint in-process."""
        start = __import__("time").perf_counter()

        try:
            from ecos.ssot.compiler.mof_policy_compiler import MOFPolicyCompiler

            compiler = MOFPolicyCompiler(constraints_path=str(CONSTRAINTS_PATH))
            policy_set = compiler.compile()

            if target_kind == "python_code":
                result = compiler.evaluate_python_code(target, caller_layer=caller_layer)
            elif target_kind == "write":
                result = compiler.evaluate_write(target, caller_domain=caller_domain)
            elif target_kind == "command":
                result = compiler.evaluate_command(target)
            else:
                return {
                    "ok": False,
                    "error_code": "INVALID_FIELD",
                    "error": f"Unknown target_kind: {target_kind}",
                    "elapsed_ms": 0,
                }

            elapsed = (__import__("time").perf_counter() - start) * 1000

            violations = []
            if hasattr(result, "violations"):
                for v in result.violations:
                    violations.append(MofViolation(
                        constraint_id=getattr(v, "violation_code", constraint_id),
                        family=_normalize_family(getattr(v, "violation_code", constraint_id)),
                        severity=getattr(v, "severity", "error"),
                        target=getattr(v, "file", target),
                        message=getattr(v, "summary", ""),
                        fix_hint=getattr(v, "remediation", None),
                    ))

            return {
                "ok": True,
                "constraint_id": constraint_id,
                "passed": result.passed,
                "violations": [v.__dict__ for v in violations],
                "elapsed_ms": round(elapsed, 1),
            }

        except ImportError:
            return {
                "ok": False,
                "error_code": "MOF_UNAVAILABLE",
                "error": "ecos package not available",
                "elapsed_ms": 0,
            }
        except Exception as e:
            elapsed = (__import__("time").perf_counter() - start) * 1000
            return {
                "ok": False,
                "error_code": "MOF_UNAVAILABLE",
                "error": str(e)[:500],
                "elapsed_ms": round(elapsed, 1),
            }

    def rule_catalog(self) -> dict[str, Any]:
        """Return 126 rules grouped by family."""
        try:
            if not CONSTRAINTS_PATH.exists():
                return {"ok": False, "error_code": "MOF_UNAVAILABLE", "degraded": True}

            data = yaml.safe_load(CONSTRAINTS_PATH.read_text(encoding="utf-8"))
            rules = data if isinstance(data, list) else data.get("rules", data.get("constraints", []))

            by_family: dict[str, list[dict]] = {}
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                rid = rule.get("id", rule.get("rule_id", "UNKNOWN"))
                fam = _normalize_family(rid)
                if fam not in by_family:
                    by_family[fam] = []
                by_family[fam].append({
                    "id": rid,
                    "dimension": rule.get("dimension", ""),
                    "type": rule.get("type", ""),
                    "severity": rule.get("severity", rule.get("type", "required")),
                })

            return {
                "ok": True,
                "total_rules": len(rules),
                "families": {fam: {"count": len(items), "rules": items} for fam, items in by_family.items()},
                "degraded": False,
            }

        except Exception as e:
            return {
                "ok": False,
                "error_code": "MOF_UNAVAILABLE",
                "error": str(e)[:500],
                "degraded": True,
            }


def _normalize_family(rule_id: str) -> str:
    """Normalize rule ID to family prefix (e.g. CR-SFOP-003 → CR-SFOP-*)."""
    parts = rule_id.split("-")
    if len(parts) >= 3:
        return f"{'-'.join(parts[:-1])}-*"
    return rule_id


def value_loop_overview(workspace: Path | None = None) -> dict[str, Any]:
    """Read value-loop-standard.yaml and dimension-system.yaml for overview."""
    ws = workspace or WORKSPACE_ROOT
    result: dict[str, Any] = {"ok": True, "degraded": False}

    try:
        if VALUE_LOOP_PATH.exists():
            vl = yaml.safe_load(VALUE_LOOP_PATH.read_text(encoding="utf-8"))
            result["stages"] = vl.get("stages", [])
            result["north_star"] = vl.get("north_star", {})
            result["broken_chains"] = vl.get("broken_chains", [])

        if DIMENSIONS_PATH.exists():
            dims = yaml.safe_load(DIMENSIONS_PATH.read_text(encoding="utf-8"))
            result["dimensions"] = dims.get("dimensions", [])
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)[:200]
        result["degraded"] = True

    return result
