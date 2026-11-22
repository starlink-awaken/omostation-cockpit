"""BET-Y2Q4-T10-348 — 心跳秒龄决定 healthy_count, 不信 tick JSON 自报 ok_count.

根因: collect_agents 曾直接采用心跳文件自报的 ok_count (或 agent_count - failed
兜底), 与 per-agent 的 sec_ago < 600 真判定脱钩 —— 25 天前的陈旧心跳仍显示
"N/N Agents Active + HEALTHY"。本测试锁定修复后的语义。
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cockpit.tui.swarm_collector import SwarmStateCollector


def _write_tick(root: Path, ts: str, ok_count: int = 6) -> None:
    d = root / ".omo" / "state"
    d.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "ts": ts,
            "agent_count": 6,
            "failed_count": 0,
            "ok_count": ok_count,
            "actions": [],
        }
    )
    (d / "agent-tick-daemon.jsonl").write_text(line + "\n", encoding="utf-8")


def test_stale_tick_yields_zero_healthy(tmp_path):
    """25 天前的 tick 即使自报 ok_count=6, healthy_count 也必须是 0."""
    old = (datetime.now(UTC) - timedelta(days=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_tick(tmp_path, old, ok_count=6)
    s = SwarmStateCollector(root=tmp_path).collect_agents()
    assert s.healthy_count == 0
    assert s.total_agents == 6
    assert all(h.status == "stale" for h in s.agents)


def test_fresh_tick_counts_all_healthy(tmp_path):
    """新鲜 tick (<600s): healthy_count == total, 与修复前行为一致."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_tick(tmp_path, now, ok_count=6)
    s = SwarmStateCollector(root=tmp_path).collect_agents()
    assert s.healthy_count == 6
    assert s.total_agents == 6
    assert all(h.status == "healthy" for h in s.agents)


def test_self_reported_ok_count_is_ignored(tmp_path):
    """自报 ok_count=0 但心跳新鲜: 仍应按秒龄真算为全绿 (自报数字不作健康度)."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_tick(tmp_path, now, ok_count=0)
    s = SwarmStateCollector(root=tmp_path).collect_agents()
    assert s.healthy_count == 6
