"""Cockpit Console must delegate durable OMO state writes to OMO brokers."""

from __future__ import annotations

import json
from pathlib import Path

from cockpit.console import bos_invoker, harness_runner


def test_bos_metrics_use_omo_append_broker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(bos_invoker, "WORKSPACE_ROOT", tmp_path)

    bos_invoker._record_metrics("bos://system/health", "resolved", 123, "http")

    metrics_file = tmp_path / ".omo" / "_knowledge" / "bos-metrics.jsonl"
    rows = [json.loads(line) for line in metrics_file.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "uri": "bos://system/health",
            "status": "resolved",
            "elapsed_ms": 123.0,
            "transport": "http",
        }
    ]


def test_harness_run_record_uses_omo_broker(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, str, dict]] = []

    def fake_write(workspace_root: Path, run_id: str, record: dict) -> Path:
        calls.append((workspace_root, run_id, record))
        return workspace_root / ".omo" / "_delivery" / "console" / "runs" / f"{run_id}.json"

    monkeypatch.setattr(harness_runner, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(harness_runner, "write_console_run_record", fake_write)
    runner = object.__new__(harness_runner.HarnessRunner)
    record = {"run_id": "cr-test", "status": "running"}

    runner._save_run(record)

    assert calls == [(tmp_path, "cr-test", record)]
