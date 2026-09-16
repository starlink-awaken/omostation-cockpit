"""HarnessRunner — subprocess-based Harness execution with SSE bridge.

Design:
- Launch bin/harness as subprocess with --json output
- Parse stdout line-by-line as JSON events
- Publish to RunEventHub for SSE consumers
- Support cancel (SIGINT → 10s grace → SIGKILL)
- Enforce worktree_only (harness-policy.yaml admission rule)
- Enforce circuit breaker (resident_flight_deck)
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cockpit.compat import WORKSPACE_ROOT
from cockpit.console.events import RunEventHub, get_hub
from cockpit.console.models import HarnessRunSpec

logger = logging.getLogger("cockpit.console.harness_runner")

HARNESS_BIN = WORKSPACE_ROOT / "bin" / "harness"
RUNS_DIR = WORKSPACE_ROOT / ".omo" / "_delivery" / "console" / "runs"
MAX_CONCURRENT = 2

STAGES = ("admission", "spec", "grill", "dispatch", "execute", "verify", "audit", "accept")

_active_runs: dict[str, asyncio.subprocess.Process] = {}


class HarnessRunner:
    """Manage Harness run lifecycle."""

    def __init__(self) -> None:
        self._hub = get_hub()
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

    async def submit(self, spec: HarnessRunSpec) -> tuple[str, str | None]:
        """Submit a new run. Returns (run_id, error)."""
        # Check concurrency
        if len(_active_runs) >= MAX_CONCURRENT:
            return "", "RUNNER_SATURATED"

        # Enforce worktree_only
        wt_path = Path(spec.worktree_path)
        if not wt_path.exists():
            return "", "WORKTREE_REQUIRED"
        try:
            result = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--show-toplevel",
                cwd=str(wt_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await result.communicate()
            actual_root = stdout.decode().strip()
            if actual_root == str(WORKSPACE_ROOT):
                return "", "WORKTREE_REQUIRED"
        except Exception:
            return "", "WORKTREE_REQUIRED"

        # Check circuit breaker
        try:
            from cockpit.resident_flight_deck import get_circuit_breaker
            breaker = get_circuit_breaker()
            decision = breaker.check("harness_run", confidence=0.8)
            if getattr(decision, "is_tripped", False):
                return "", "CIRCUIT_BREAKER_TRIPPED"
        except (ImportError, Exception):
            pass  # breaker not available, proceed

        # Generate run_id
        run_id = f"cr-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{id(spec) % 0xFFFF:04x}"

        # Create run record
        run_record = {
            "run_id": run_id,
            "bet_id": spec.bet_id,
            "profile": spec.profile,
            "objective": spec.objective,
            "worktree_path": spec.worktree_path,
            "dry_run": spec.dry_run,
            "status": "submitted",
            "stage": "admission",
            "exit_code": None,
            "elapsed_ms": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_run(run_record)

        # Launch subprocess
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(HARNESS_BIN),
                "run",
                "--bet", spec.bet_id,
                "--profile", spec.profile,
                "--objective", spec.objective,
                "--json",
                cwd=str(wt_path),
                env={**__import__("os").environ, "WORKSPACE": str(WORKSPACE_ROOT)},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _active_runs[run_id] = proc
            run_record["pid"] = proc.pid
            run_record["status"] = "running"
            self._save_run(run_record)

            # Start event processing
            asyncio.create_task(self._process_run(run_id, proc, run_record))

            return run_id, None

        except Exception as e:
            return "", str(e)[:200]

    async def cancel(self, run_id: str) -> bool:
        """Cancel a running harness process."""
        proc = _active_runs.get(run_id)
        if not proc:
            return False

        try:
            proc.send_signal(signal.SIGINT)
            # Wait for graceful exit with 10s grace
            try:
                await asyncio.wait_for(proc.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                proc.kill()

            await self._hub.publish(run_id, {
                "event": "run_complete",
                "state": "cancelled",
                "ts": datetime.now(timezone.utc).isoformat(),
            })

            run_data = self._load_run(run_id)
            if run_data:
                run_data["status"] = "cancelled"
                self._save_run(run_data)

            _active_runs.pop(run_id, None)
            return True

        except Exception:
            return False

    def list_runs(self, limit: int = 50) -> list[dict]:
        """List run records sorted by most recent."""
        runs = []
        for f in RUNS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                runs.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        runs.sort(key=lambda r: r.get("started_at", ""), reverse=True)
        return runs[:limit]

    def run_detail(self, run_id: str) -> dict | None:
        """Get a single run record."""
        return self._load_run(run_id)

    async def _process_run(
        self, run_id: str, proc: asyncio.subprocess.Process, run_record: dict
    ) -> None:
        """Parse subprocess stdout and publish events."""
        start_time = time.monotonic()
        current_stage = "admission"
        raw_log: list[str] = []

        try:
            assert proc.stdout is not None
            async for line in proc.stdout:
                line_str = line.decode().strip()
                if not line_str:
                    continue

                raw_log.append(line_str)
                if len(raw_log) > 200:
                    raw_log.pop(0)

                try:
                    event = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                # Map harness output to stage events
                stage = event.get("stage", event.get("step", ""))
                if stage and stage != current_stage:
                    current_stage = stage
                    await self._hub.publish(run_id, {
                        "event": "stage_started",
                        "stage": stage,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })

                # Verify stage checks
                check_name = event.get("check", event.get("name", ""))
                check_state = event.get("state", event.get("status", ""))
                if check_name and stage == "verify":
                    blocking = event.get("blocking", True)
                    await self._hub.publish(run_id, {
                        "event": "run_progress",
                        "stage": "verify",
                        "check": check_name,
                        "blocking": blocking,
                        "state": check_state,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })

                # Stage completion
                if event.get("stage_state") == "completed" or event.get("status") == "completed":
                    await self._hub.publish(run_id, {
                        "event": "stage_completed",
                        "stage": stage,
                        "state": "completed",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })

                # Gate required (HITL)
                if event.get("type") == "gate_required" or event.get("state") == "blocked":
                    await self._hub.publish(run_id, {
                        "event": "gate_required",
                        "gate": event.get("gate", stage),
                        "reason": event.get("reason", "approval needed"),
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    run_record["status"] = "blocked"
                    self._save_run(run_record)

                # Update current stage
                run_record["stage"] = current_stage
                self._save_run(run_record)

        except Exception as e:
            logger.error("Run %s processing error: %s", run_id, e)

        # Process exited
        exit_code = proc.returncode or 0
        elapsed_ms = (time.monotonic() - start_time) * 1000

        state = "completed" if exit_code == 0 else "failed"
        await self._hub.publish(run_id, {
            "event": "run_complete",
            "state": state,
            "exit_code": exit_code,
            "elapsed_ms": round(elapsed_ms, 1),
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        run_record["status"] = state
        run_record["exit_code"] = exit_code
        run_record["elapsed_ms"] = round(elapsed_ms, 1)
        self._save_run(run_record)
        _active_runs.pop(run_id, None)

    def _save_run(self, record: dict) -> None:
        """Persist run record to JSON file."""
        try:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            path = RUNS_DIR / f"{record['run_id']}.json"
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save run record: %s", e)

    def _load_run(self, run_id: str) -> dict | None:
        """Load a run record from JSON file."""
        path = RUNS_DIR / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None


_runner: HarnessRunner | None = None


def get_runner() -> HarnessRunner:
    """Singleton HarnessRunner instance."""
    global _runner
    if _runner is None:
        _runner = HarnessRunner()
    return _runner
