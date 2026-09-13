"""Unit tests for ObservatoryEventBus (BET-Y1Q4-T8-24A/B/C/D)."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from cockpit.observatory.event_bus import ObservatoryEvent, ObservatoryEventBus


class TestObservatoryEventBus(unittest.TestCase):
    def setUp(self):
        # 使用临时文件测试持久化隔离
        self.tmp_dir = Path("/tmp/cockpit_test_event_bus")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.persist_path = self.tmp_dir / "test_events.jsonl"
        if self.persist_path.exists():
            self.persist_path.unlink()
        self.bus = ObservatoryEventBus(max_history=10, persist_path=self.persist_path)

    def tearDown(self):
        if self.persist_path.exists():
            self.persist_path.unlink()

    def test_publish_and_retrieve_recent(self):
        evt1 = ObservatoryEvent(
            type="COLLISION_RISK",
            severity="CRITICAL",
            title="测试并发写锁冲突",
            project_id="cockpit",
            advice="执行 guard-submodules 校验",
        )
        self.bus.publish(evt1)

        evt2 = ObservatoryEvent(
            type="WORKTREE_CLAIMED",
            severity="INFO",
            title="新工作树已挂载",
            project_id="omo",
        )
        self.bus.publish(evt2)

        recent = self.bus.get_recent(limit=10)
        self.assertEqual(len(recent), 2)
        # 倒序返回，最新的在前面
        self.assertEqual(recent[0]["type"], "WORKTREE_CLAIMED")
        self.assertEqual(recent[1]["type"], "COLLISION_RISK")

    def test_filter_by_type_severity_project(self):
        for i in range(5):
            self.bus.publish(ObservatoryEvent(
                type="SENTINEL_DRIFT" if i % 2 == 0 else "GATE_VERIFIED",
                severity="HIGH" if i < 3 else "LOW",
                title=f"Event {i}",
                project_id="cockpit" if i < 2 else "agora",
            ))

        # Filter by type
        drift_events = self.bus.get_recent(event_type="SENTINEL_DRIFT")
        self.assertTrue(all(e["type"] == "SENTINEL_DRIFT" for e in drift_events))

        # Filter by severity
        high_events = self.bus.get_recent(severity="HIGH")
        self.assertTrue(all(e["severity"] == "HIGH" for e in high_events))

        # Filter by project
        cockpit_events = self.bus.get_recent(project_id="cockpit")
        self.assertTrue(all(e["project_id"] == "cockpit" for e in cockpit_events))

    def test_ring_buffer_overflow(self):
        # max_history is 10
        for i in range(15):
            self.bus.publish(ObservatoryEvent(
                type="COLLISION_RISK",
                severity="INFO",
                title=f"Event {i}",
            ))

        recent = self.bus.get_recent(limit=50)
        self.assertEqual(len(recent), 10)
        # 应该包含最近的 Event 14 到 Event 5
        self.assertEqual(recent[0]["title"], "Event 14")
        self.assertEqual(recent[-1]["title"], "Event 5")

    def test_persistence_reload(self):
        self.bus.publish(ObservatoryEvent(
            type="PORT_HEALTH",
            severity="MEDIUM",
            title="端口重新上线",
            project_id="aetherforge",
        ))

        # 重新创建 bus 实例，验证文件恢复
        bus2 = ObservatoryEventBus(max_history=10, persist_path=self.persist_path)
        recent = bus2.get_recent(limit=5)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["title"], "端口重新上线")
        self.assertEqual(recent[0]["project_id"], "aetherforge")

    def test_async_subscriber(self):
        async def _run():
            queue = self.bus.subscribe()
            evt = ObservatoryEvent(type="TEST_ASYNC", severity="INFO", title="异步分发测试")
            self.bus.publish(evt)
            received = await asyncio.wait_for(queue.get(), timeout=1.0)
            self.assertEqual(received.title, "异步分发测试")
            self.bus.unsubscribe(queue)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
