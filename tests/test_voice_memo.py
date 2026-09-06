"""Tests for cockpit voice-memo command face (BET-Y2Q1-T2-01)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cockpit.commands.voice_memo import cmd_voice_memo


def _fake_payload(ok: bool = True) -> dict:
    if ok:
        return {
            "ok": True, "engine": "whisper-cli", "elapsed_s": 0.9, "budget_s": 1.5,
            "polished": "落实数据迁移，下周前完成。",
            "kind": "task_list",
            "task_items": [{"task": "落实数据迁移", "owner": "待指定", "deadline": "下周前"}],
        }
    return {"ok": False, "error_code": "needs_asr_backend", "detail": "无引擎", "install_hint": "brew install whisper-cpp"}


def test_voice_memo_to_spine_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import cockpit.commands.voice_memo as vm

    monkeypatch.setattr(vm, "_agora_python", lambda code, timeout=180.0: (0, json.dumps(_fake_payload(), ensure_ascii=False)))
    monkeypatch.setattr(vm, "_ws", lambda: tmp_path)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")

    args = argparse.Namespace(spine_command="voice-memo", audio=str(audio), engine=None, to_spine=True, json=False)
    assert cmd_voice_memo(args) == 0
    pool = tmp_path / ".omo" / "state" / "spine-draft-pool.jsonl"
    entries = [json.loads(l) for l in pool.read_text(encoding="utf-8").splitlines() if l]
    assert len(entries) == 1 and entries[0]["source"] == "voice-memo"
    assert entries[0]["task_items"][0]["deadline"] == "下周前"


def test_voice_memo_honest_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    import cockpit.commands.voice_memo as vm

    monkeypatch.setattr(vm, "_agora_python", lambda code, timeout=180.0: (0, json.dumps(_fake_payload(False), ensure_ascii=False)))
    monkeypatch.setattr(vm, "_ws", lambda: tmp_path)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    args = argparse.Namespace(spine_command="voice-memo", audio=str(audio), engine=None, to_spine=True, json=True)
    assert cmd_voice_memo(args) == 1
    assert not (tmp_path / ".omo" / "state" / "spine-draft-pool.jsonl").exists()


def test_voice_memo_requires_audio():
    args = argparse.Namespace(spine_command="voice-memo", audio="", engine=None, to_spine=False, json=False)
    assert cmd_voice_memo(args) == 1
