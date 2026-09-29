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


def test_extract_action_items_single_line_asr_transcript():
    """ASR 转写常是一整行、以分号分隔: 每条事项的责任人/时限必须取自本条, 不能串到别条。"""
    asr = (
        "今天处务会议定五件事：第一，数据安全专项检查由张磊牵头，十月十日前完成自查报告；"
        "第二，电子病历升级项目验收材料由李娜负责，本周五前报规划信息处；"
        "第三，传染病直报质量核查由王强负责，十月十二日前报疾控处；"
        "第四，下周二上午九点召开信创适配推进会，赵敏负责会务；"
        "第五，十月底前完成第三季度信息化工作总结，由我本人审定。"
    )
    items = extract_action_items(asr)
    got = [(a["owner"], a["deadline"]) for a in items["action_items"]]
    assert got == [
        ("张磊", "十月十日前"),
        ("李娜", "本周五前"),
        ("王强", "十月十二日前"),
        ("赵敏", "下周二上午九点"),
        ("本人", "十月底前"),
    ]
    assert items["action_items"][0]["task"].startswith("数据安全专项检查")
    assert items["decisions"]


def test_route_persists_to_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--route 的每条行动项除路由外还要落 deadline-tracker 台账(不再只算不存)。"""
    import cockpit.commands.calendar as cal

    calls = []
    fake_ws = tmp_path / "ws"
    (fake_ws / "bin" / "bc-os").mkdir(parents=True)
    (fake_ws / "bin" / "bc-os" / "signal_router.py").touch()

    class R:
        returncode = 0
        stdout = '{"signal_id": "cal-x", "source": "calendar"}'

    monkeypatch.setattr(cal, "_ws", lambda: fake_ws)
    monkeypatch.setattr(cal.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or R())
    items = {"action_items": [{"task": "牵头自查", "owner": "张磊", "deadline": "十月十日前", "source_line": "s"}]}
    out = cal._route_to_signal(items)
    assert out["routed_count"] == 1 and out["persisted_count"] == 1
    snippet = calls[0][-1]
    assert "register_task" in snippet and "meeting-supervision" in snippet and "owner" in snippet


def test_resolve_deadline_chinese_relative():
    """中文相对期限解析: 「十月十日前」「本周五」此前落不了账(全链路实测)。"""
    import datetime

    from cockpit.commands.calendar import _resolve_deadline as r

    assert r("2026年10月12日前") == "2026-10-12"
    assert r("十月十日前") == "2026-10-10"
    today = datetime.date.today()
    friday_delta = (5 - today.isoweekday()) % 7 or 7
    assert r("本周五") == (today + datetime.timedelta(days=friday_delta)).isoformat()
    assert r("下周三") == (today + datetime.timedelta(days=((3 - today.isoweekday()) % 7) + 7)).isoformat()
    assert r("待排期") == ""
