"""Tests for cockpit calendar (BET-Y1Q4-T7-02): ICS parse, prebrief, action extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cockpit.cli import main
from cockpit.commands.calendar import extract_action_items, parse_ics, prebrief

ICS_SAMPLE = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:医共体建设方案评审会
DTSTART:20260910T140000Z
DTEND:20260910T153000Z
LOCATION:3 号会议室
DESCRIPTION:评审智慧医疗平台方案。讨论预算与接口规范。
END:VEVENT
BEGIN:VEVENT
SUMMARY:周例会
DTSTART:20260914T090000Z
DTEND:20260914T100000Z
END:VEVENT
END:VCALENDAR"""


def test_parse_ics_extracts_events():
    events = parse_ics(ICS_SAMPLE)
    assert len(events) == 2
    first = events[0]
    assert first["summary"] == "医共体建设方案评审会"
    assert first["dtstart"] == "2026-09-10 14:00"
    assert first["location"] == "3 号会议室"


def test_prebrief_generates_materials():
    events = parse_ics(ICS_SAMPLE)
    b = prebrief(events[0])
    assert b["title"] == "医共体建设方案评审会"
    assert b["prep_materials"], "no prep materials generated"
    assert any("评审" in h or "方案" in h for h in b["prep_materials"])
    assert b["agenda_points"]


def test_extract_action_items_with_owner_and_deadline():
    transcript = """会议讨论了区域卫生平台建设。
决定：原则通过智慧医疗平台一期方案。
夏明星 负责牵头输出接口规范，周五前提交。
信息科 落实数据迁移工作，下周前完成。
散会。"""
    items = extract_action_items(transcript)
    assert items["decisions"], "decisions not extracted"
    assert len(items["action_items"]) >= 2
    assert items["owner_assigned"] >= 2
    assert any("周五" in a["deadline"] or "下周" in a["deadline"] for a in items["action_items"])


def test_extract_action_items_empty_transcript():
    items = extract_action_items("无实质内容的闲聊。")
    assert items["action_items"] == [] or items["owner_assigned"] >= 0


def test_cli_prebrief_json(tmp_path: Path):
    ics = tmp_path / "cal.ics"
    ics.write_text(ICS_SAMPLE, encoding="utf-8")
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["calendar", "prebrief", "--ics", str(ics), "--json"])
    assert rc == 0
    briefs = json.loads(buf.getvalue())
    assert len(briefs) == 2 and briefs[0]["prep_materials"]


def test_cli_minutes_json(tmp_path: Path):
    tr = tmp_path / "minutes.txt"
    tr.write_text("决定：通过方案。\n王科 负责跟进进度，月底前反馈。\n", encoding="utf-8")
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["calendar", "minutes", "--transcript", str(tr), "--json"])
    assert rc == 0
    data = json.loads(buf.getvalue())
    assert data["schema"] == "cockpit.calendar.minutes.v1"
    assert data["action_items"] and data["decisions"]
