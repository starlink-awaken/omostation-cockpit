"""Unified Observatory Service (BET-Y1Q4-T8-24A).

Integrates catalog_sources, strategy_sources, and query_engine into an
in-memory cache with generation locking, REST query dispatch, and SSE streaming.
No execution side-effects, no workspace writes.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, AsyncGenerator

from cockpit.compat import WORKSPACE_ROOT
from cockpit.observatory.catalog_sources import collect_catalog
from cockpit.observatory.query_engine import (
    ObservationIndex,
    OPERATIONS,
    QueryError,
    content_digest,
)
from cockpit.observatory.strategy_projection import build_strategy
from cockpit.observatory.strategy_sources import collect_strategy_sources


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ObservatoryService:
    """Unified observatory service facade with generation locking and pub/sub streaming."""

    def __init__(
        self,
        workspace: Path | None = None,
        snapshot_path: Path | None = None,
    ) -> None:
        self.workspace = (workspace or WORKSPACE_ROOT).resolve()
        self.snapshot_path = Path(snapshot_path) if snapshot_path else (
            Path.home() / ".local/share/zhixing-dashboard/current.json"
        )
        self._lock = threading.RLock()
        self._cached_snapshot: dict[str, Any] | None = None
        self._cached_index: ObservationIndex | None = None
        self._cached_generation: str | None = None
        self._last_loaded_mtime: float | None = None
        # SSE subscribers
        self._subscribers: set[asyncio.Queue] = set()

    def _build_dynamic_snapshot(self) -> dict[str, Any]:
        """Dynamically assemble a snapshot from catalog and strategy SSOT sources."""
        observed_time = _now()
        catalog_data = collect_catalog(self.workspace)
        strategy_raw = collect_strategy_sources(workspace=self.workspace)
        strategy_data = build_strategy(
            snapshot={"catalog": catalog_data, "observed_at": observed_time},
            supplemental=strategy_raw,
        )

        # Scene system extensions from panorama collector (Serena Phase D)
        scene_extensions = self._collect_scene_system()

        # Deterministic generation computation based on source contents
        raw_seed = (
            content_digest(catalog_data)
            + ":"
            + content_digest(strategy_data)
            + ":"
            + content_digest(scene_extensions)
        ).encode("utf-8")
        gen_id = hashlib.sha256(raw_seed).hexdigest()[:20]

        snapshot = {
            "schema": "cockpit-observatory-snapshot/v1",
            "generation_id": gen_id,
            "generated_at": observed_time,
            "observed_at": observed_time,
            "mode": "read-only-unified-observatory",
            "workspace": str(self.workspace),
            "catalog": catalog_data,
            "strategic": strategy_data,
            "source_states": {
                "catalog": {"status": catalog_data.get("state", "OBSERVED")},
                "strategic": {"status": strategy_data.get("state", "OBSERVED")},
            },
        }
        snapshot.update(scene_extensions)
        return snapshot

    def _collect_scene_system(self) -> dict[str, Any]:
        """Best-effort read of panorama collector output (runtime/dashboard/data.json).

        Panorama writes gitignored runtime data; when absent (fresh checkout,
        collector not yet run, or test harness) returns an empty dict so the
        observatory still boots. The dashboard at :43191 consumes the same file.
        """
        import json as _json
        data_path = self.workspace / "runtime" / "dashboard" / "data.json"
        if not data_path.is_file():
            return {}
        try:
            with data_path.open("r", encoding="utf-8") as fh:
                data = _json.load(fh)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        extensions: dict[str, Any] = {}
        for key in ("scene_cards", "signal_poller", "journey_executions",
                    "remote_hygiene", "service_keeper", "connectors", "bos_verifier"):
            value = data.get(key)
            if isinstance(value, dict):
                extensions[key] = value
        return extensions

    def get_snapshot(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return the current snapshot, preferring snapshot_path if fresh, or dynamic fallback."""
        with self._lock:
            if not force_refresh and self._cached_snapshot is not None:
                # Check if file has changed
                if self.snapshot_path.is_file():
                    try:
                        mtime = self.snapshot_path.stat().st_mtime
                        if self._last_loaded_mtime == mtime:
                            return self._cached_snapshot
                    except OSError:
                        pass
                else:
                    return self._cached_snapshot

            # Attempt to load from published snapshot file first
            loaded = False
            if self.snapshot_path.is_file():
                try:
                    raw = self.snapshot_path.read_text(encoding="utf-8")
                    data = json.loads(raw)
                    if (
                        isinstance(data, dict)
                        and isinstance(data.get("generation_id"), str)
                        and isinstance(data.get("strategic"), dict)
                        and isinstance(data.get("catalog"), dict)
                    ):
                        self._cached_snapshot = data
                        self._cached_generation = data["generation_id"]
                        self._last_loaded_mtime = self.snapshot_path.stat().st_mtime
                        self._cached_index = ObservationIndex(data)
                        loaded = True
                except Exception:
                    loaded = False

            if not loaded:
                snapshot = self._build_dynamic_snapshot()
                self._cached_snapshot = snapshot
                self._cached_generation = snapshot["generation_id"]
                self._last_loaded_mtime = None
                self._cached_index = ObservationIndex(snapshot)

            return self._cached_snapshot

    def get_index(self, generation: str | None = None) -> ObservationIndex:
        """Return an active ObservationIndex. If generation is provided, verify match."""
        snapshot = self.get_snapshot()
        index = self._cached_index
        if index is None:
            index = ObservationIndex(snapshot)
            self._cached_index = index

        if generation and index.generation != generation:
            raise QueryError(409, f"GENERATION_MISMATCH: requested {generation}, current {index.generation}")
        return index

    def query(self, operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a query against the in-memory observation index."""
        if operation not in OPERATIONS:
            raise QueryError(400, f"UNKNOWN_OPERATION: {operation}")
        params = dict(params or {})
        generation = params.pop("generation", None)
        index = self.get_index(generation=generation)
        return index.query(operation, params)

    def get_catalogs(self) -> dict[str, Any]:
        """Return raw catalog section."""
        snapshot = self.get_snapshot()
        return snapshot.get("catalog", {})

    def get_strategy(self) -> dict[str, Any]:
        """Return raw strategy section."""
        snapshot = self.get_snapshot()
        return snapshot.get("strategic", {})

    async def register_subscriber(self) -> asyncio.Queue:
        """Register a new SSE stream subscriber."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        # Send initial generation notification
        current_gen = self._cached_generation or "initial"
        await queue.put({
            "event": "connected",
            "data": json.dumps({"generation_id": current_gen, "timestamp": _now()}),
        })
        return queue

    def unregister_subscriber(self, queue: asyncio.Queue) -> None:
        """Remove an SSE stream subscriber."""
        self._subscribers.discard(queue)

    async def notify_change(self, event_type: str = "change", details: dict[str, Any] | None = None) -> None:
        """Broadcast changes to all active SSE queues."""
        payload = {
            "event": event_type,
            "data": json.dumps({
                "generation_id": self._cached_generation,
                "timestamp": _now(),
                "details": details or {},
            }),
        }
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                self._subscribers.discard(q)


# ── Global Singleton instance ────────────────────────────────────
_service_instance: ObservatoryService | None = None
_service_lock = threading.Lock()


def get_observatory_service(workspace: Path | None = None) -> ObservatoryService:
    global _service_instance
    with _service_lock:
        if _service_instance is None:
            _service_instance = ObservatoryService(workspace=workspace)
        return _service_instance
