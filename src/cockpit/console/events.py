"""RunEventHub — per-run event fan-out with replay buffer and TTL GC.

Pattern: mirrors observatory/service.py subscriber model (asyncio.Queue).
Adds: per-run_id sharding, replay buffer (deque maxlen=500), TTL GC.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any


class RunEventHub:
    """Fan-out event hub for Harness run events.

    Each run_id gets its own subscriber set. Events are appended to a replay
    buffer so late subscribers (SSE reconnects with Last-Event-ID) can catch up.
    """

    KEEPALIVE_INTERVAL_S = 2.0
    RUN_TTL_S = 3600  # 1 hour
    QUEUE_MAX = 200
    REPLAY_BUFFER_SIZE = 500

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict]]] = defaultdict(set)
        self._replay: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=self.REPLAY_BUFFER_SIZE))
        self._last_seq: dict[str, int] = defaultdict(int)
        self._last_access: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: str) -> asyncio.Queue[dict]:
        """Register a subscriber. Returns a queue pre-filled with replay buffer."""
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self.QUEUE_MAX)

        # Replay buffered events
        for event in self._replay.get(run_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                break

        self._subscribers[run_id].add(queue)
        self._last_access[run_id] = time.monotonic()

        # Cleanup stale runs
        asyncio.create_task(self._gc())

        return queue

    async def publish(self, run_id: str, event: dict[str, Any]) -> int:
        """Publish an event to all subscribers of a run. Returns receiver count."""
        self._last_access[run_id] = time.monotonic()
        self._last_seq[run_id] += 1
        event = {"seq": self._last_seq[run_id], **event}

        # Append to replay buffer
        self._replay[run_id].append(event)

        receivers = 0
        for queue in list(self._subscribers.get(run_id, [])):
            try:
                queue.put_nowait(event)
                receivers += 1
            except asyncio.QueueFull:
                # Drop oldest event
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                    receivers += 1
                except asyncio.QueueFull:
                    pass

        return receivers

    def forget(self, run_id: str) -> None:
        """Remove all state for a run."""
        self._subscribers.pop(run_id, None)
        self._replay.pop(run_id, None)
        self._last_seq.pop(run_id, None)
        self._last_access.pop(run_id, None)

    async def forget_if_empty(self, run_id: str) -> None:
        """Forget run if no active subscribers."""
        if not self._subscribers.get(run_id):
            self.forget(run_id)

    def recent_runs(self, limit: int = 50) -> list[str]:
        """List run_ids sorted by most recent access."""
        sorted_runs = sorted(self._last_access.items(), key=lambda x: x[1], reverse=True)
        return [run_id for run_id, _ in sorted_runs[:limit]]

    def last_seq(self, run_id: str) -> int:
        """Get the last sequence number for a run."""
        return self._last_seq.get(run_id, 0)

    def replay_from(self, run_id: str, from_seq: int) -> list[dict]:
        """Get replay buffer events from a given sequence number."""
        return [e for e in self._replay.get(run_id, []) if e.get("seq", 0) > from_seq]

    async def _gc(self) -> None:
        """Garbage collect runs that haven't been accessed in RUN_TTL_S."""
        now = time.monotonic()
        expired = [
            run_id
            for run_id, last in self._last_access.items()
            if now - last > self.RUN_TTL_S
        ]
        for run_id in expired:
            self.forget(run_id)


_hub: RunEventHub | None = None


def get_hub() -> RunEventHub:
    """Singleton RunEventHub instance."""
    global _hub
    if _hub is None:
        _hub = RunEventHub()
    return _hub
