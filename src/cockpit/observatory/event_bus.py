"""cockpit.observatory.event_bus — 织星主权系统态势感知事件总线 (Observatory Event Bus)。

为常驻智能体 (Resident Agent)、并发子代理 (Subagents) 与驾驶舱 (Cockpit UI) 提供
纳秒级内存流转、结构化时间线回溯与异步事件广播。
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cockpit.compat import WORKSPACE_ROOT


@dataclass
class ObservatoryEvent:
    """标准化主权态势事件模型。"""

    type: str  # e.g., COLLISION_RISK, WORKTREE_CLAIMED, WORKTREE_RELEASED, SENTINEL_DRIFT, GATE_VERIFIED, PORT_HEALTH
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    title: str
    source: str = "observatory"  # topology_engine, agent_workflow, sentinel, gac_worktree
    project_id: str = "workspace"
    advice: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"evt_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}")
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObservatoryEvent:
        return cls(
            id=data.get("id", f"evt_{uuid.uuid4().hex[:8]}"),
            timestamp=data.get("timestamp", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
            type=data.get("type", "UNKNOWN"),
            severity=data.get("severity", "INFO"),
            source=data.get("source", "observatory"),
            project_id=data.get("project_id", "workspace"),
            title=data.get("title", ""),
            advice=data.get("advice", ""),
            payload=data.get("payload", {}),
        )


class ObservatoryEventBus:
    """态势感知事件总线核心类：具备内存环形队列、持久化追加与异步广播。"""

    def __init__(
        self,
        max_history: int = 200,
        persist_path: Path | None = None,
    ) -> None:
        self.max_history = max_history
        self._lock = threading.RLock()
        self._history: deque[ObservatoryEvent] = deque(maxlen=max_history)
        self._subscribers: set[asyncio.Queue[ObservatoryEvent]] = set()

        if persist_path is None:
            cache_dir = WORKSPACE_ROOT / ".cockpit" / "cache"
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                self.persist_path: Path | None = cache_dir / "observatory_events.jsonl"
            except Exception:
                self.persist_path = None
        else:
            self.persist_path = persist_path

        # 启动时若存在持久化文件，自动回溯最近事件
        self._load_persisted_events()

    def _load_persisted_events(self) -> None:
        if not self.persist_path or not self.persist_path.is_file():
            return
        try:
            with open(self.persist_path, encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines[-self.max_history:]:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    data = json.loads(line_str)
                    self._history.append(ObservatoryEvent.from_dict(data))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    pass
        except OSError:
            pass

    def publish(self, event: ObservatoryEvent) -> None:
        """发布一条态势事件：存入内存环、持久化写盘并分发给订阅者。"""
        with self._lock:
            self._history.append(event)

            # 持久化追加
            if self.persist_path:
                try:
                    with open(self.persist_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
                except Exception:
                    pass

        # 异步分发给活动队列
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._subscribers.discard(q)
            except Exception:
                pass

    def subscribe(self, maxsize: int = 100) -> asyncio.Queue[ObservatoryEvent]:
        """注册异步队列订阅者。"""
        queue: asyncio.Queue[ObservatoryEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[ObservatoryEvent]) -> None:
        """取消订阅。"""
        self._subscribers.discard(queue)

    def get_recent(
        self,
        limit: int = 50,
        event_type: str | list[str] | None = None,
        severity: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """多维筛选获取最近的历史态势事件。"""
        with self._lock:
            events = list(self._history)

        filtered = events
        if event_type:
            types = [t.strip().upper() for t in (event_type if isinstance(event_type, list) else event_type.split(","))]
            filtered = [e for e in filtered if e.type.upper() in types]

        if severity:
            sev_target = severity.strip().upper()
            filtered = [e for e in filtered if e.severity.upper() == sev_target]

        if project_id:
            pid = project_id.strip()
            filtered = [e for e in filtered if e.project_id == pid or e.project_id == "workspace"]

        # 按时间倒序返回最近 limit 条
        res = [e.to_dict() for e in filtered[-limit:]]
        res.reverse()
        return res

    def clear(self) -> None:
        """清空历史（主要供测试使用）。"""
        with self._lock:
            self._history.clear()
            if self.persist_path and self.persist_path.is_file():
                try:
                    self.persist_path.unlink()
                except Exception:
                    pass


# ── 全局单例 ───────────────────────────────────────────────────────
_EVENT_BUS: ObservatoryEventBus | None = None
_EVENT_BUS_LOCK = threading.Lock()


def get_event_bus() -> ObservatoryEventBus:
    global _EVENT_BUS
    with _EVENT_BUS_LOCK:
        if _EVENT_BUS is None:
            _EVENT_BUS = ObservatoryEventBus()
        return _EVENT_BUS
