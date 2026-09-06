"""cockpit.commands.calendar — 多维日历感知与督办闭环 (BET-Y1Q4-T7-02).

ICS (RFC 5545 子集) 零依赖解析 → 会前速递简报；会议转写文本 → 核心议题
+ 交办事项（责任人与时间节点标注）督办清单；督办事项经 bc-os signal_router
投递入库 Cockpit 待办。确定性规则实现，真实 CalDAV/腾讯会议/钉钉通道属
部署配置（本模块消费注入的 ICS 与转写文本）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _ws() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "docs" / "project-registry.yaml").is_file():
            return parent
    return Path.cwd()


# ── ICS 解析 (RFC 5545 子集) ─────────────────────────────────────────

_ICS_DT = re.compile(r"^DTSTART[^:]*:(\d{8}(?:T\d{6}Z?)?)$")
_ICS_DTEND = re.compile(r"^DTEND[^:]*:(\d{8}(?:T\d{6}Z?)?)$")
_ICS_SUMMARY = re.compile(r"^SUMMARY[^:]*:(.*)$")
_ICS_LOCATION = re.compile(r"^LOCATION[^:]*:(.*)$")


def _fmt_dt(raw: str) -> str:
    if len(raw) >= 15:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]} {raw[9:11]}:{raw[11:13]}"
    if len(raw) == 8:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def parse_ics(text: str) -> list[dict[str, str]]:
    """Parse VEVENT blocks from ICS text (SUMMARY/DTSTART/DTEND/LOCATION/DESCRIPTION)."""
    events: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    desc: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            cur, desc = {}, []
            continue
        if line == "END:VEVENT":
            if cur is not None:
                cur["description"] = "\n".join(desc).strip()
                events.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        if (m := _ICS_SUMMARY.match(line)):
            cur["summary"] = m.group(1).strip()
        elif (m := _ICS_DT.match(line)):
            cur["dtstart"] = _fmt_dt(m.group(1))
        elif (m := _ICS_DTEND.match(line)):
            cur["dtend"] = _fmt_dt(m.group(1))
        elif (m := _ICS_LOCATION.match(line)):
            cur["location"] = m.group(1).strip()
        elif line.startswith("DESCRIPTION"):
            desc.append(line.split(":", 1)[-1] if ":" in line else "")
    return events


# ── 会前速递简报 ──────────────────────────────────────────────────────

_PREP_HINTS = [
    ("评审|审查|评审会", ["相关方案文档", "上轮评审遗留问题清单"]),
    ("招标|采购|报价", ["预算审批单", "供应商对比表"]),
    ("进度|周报|例会", ["本周进展摘要", "风险与阻塞项列表"]),
    ("架构|技术|系统", ["架构图最新版", "ADR 决策记录"]),
]


def prebrief(event: dict[str, str]) -> dict[str, Any]:
    """会前速递简报：时间/地点/议题要点/建议准备材料（规则生成）。"""
    title = event.get("summary", "(未命名会议)")
    hints: list[str] = []
    for pat, materials in _PREP_HINTS:
        if re.search(pat, title):
            hints.extend(materials)
    if event.get("description"):
        hints.append("会议 DESCRIPTION 中的附件与议程逐项预读")
    if not hints:
        hints = ["会议目标一句话（组织者处确认）", "相关干系人清单"]
    return {
        "title": title,
        "when": event.get("dtstart", ""),
        "end": event.get("dtend", ""),
        "location": event.get("location", ""),
        "agenda_points": [s.strip() for s in event.get("description", "").split("。") if s.strip()][:3],
        "prep_materials": hints,
    }


# ── 转写文本 → 交办事项与决策要点 ────────────────────────────────────

_ACTION_VERBS = r"(?:落实|跟进|牵头|负责|完成|提交|梳理|输出|反馈|组织|协调|编制|推动|复审)"
_RESPONSIBLE = r"([\u4e00-\u9fff]{2,4}(?:处|科|室|中心|组|团队|部门)|夏明星|[A-Z][a-z]+)"
_TIME_HINT = r"(?:(本周|下周|本月|月底|周五|下周一|[一二三四五六日]月底?)[之]?前|\d{1,2}月\d{1,2}日前|(\d+) 个?工作日[之]?内)"

_ACTION_LINE = re.compile(rf"{_ACTION_VERBS}[^。；\n]*")
_RESP_IN_LINE = re.compile(_RESPONSIBLE + r"\s*(?:负责|牵头|落实|跟进)")
_TIME_IN_LINE = re.compile(_TIME_HINT)


def extract_action_items(transcript: str) -> dict[str, Any]:
    """转写文本 → 决策要点 + 交办事项（任务句式规则匹配，含责任人/时间）。"""
    decisions: list[str] = []
    actions: list[dict[str, str]] = []
    for line in transcript.splitlines():
        s = line.strip().lstrip("-•0123456789.、 ")
        if not s:
            continue
        if re.search(r"决定|同意|原则通过|明确", s) and len(s) >= 8:
            decisions.append(s[:80])
        for m in _ACTION_LINE.finditer(s):
            seg = m.group(0)
            resp_m = _RESP_IN_LINE.search(seg) or re.search(_RESPONSIBLE, s)
            time_m = _TIME_IN_LINE.search(s)
            actions.append(
                {
                    "task": seg[:70],
                    "owner": resp_m.group(1) if resp_m else "待指定",
                    "deadline": time_m.group(0) if time_m else "待排期",
                    "source_line": s[:60],
                }
            )
    return {
        "schema": "cockpit.calendar.minutes.v1",
        "decisions": decisions[:5],
        "action_items": actions,
        "owner_assigned": sum(1 for a in actions if a["owner"] != "待指定"),
        "deadline_assigned": sum(1 for a in actions if a["deadline"] != "待排期"),
    }


# ── signal 路由投递（督办入库）───────────────────────────────────────

def _route_to_signal(items: dict[str, Any], source: str = "calendar-minutes") -> dict[str, Any]:
    """把督办清单逐项经 bc-os signal_router 的 route_calendar_event 路由入库。"""
    router = _ws() / "bin" / "bc-os" / "signal_router.py"
    if not router.is_file():
        return {"ok": False, "error": "signal_router not found"}
    routed = []
    for a in items.get("action_items", []):
        title = f"[督办] {a['task']}"
        snippet = (
            "import json, sys\n"
            "sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(%r).resolve().parent))\n"
            "from signal_router import route_calendar_event\n"
            "r = route_calendar_event(%r, %r)\n"
            "print(json.dumps(r, ensure_ascii=False))\n"
            % (str(router.parent), str(router), title, a.get("source_line", ""))
        )
        res = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, check=False, timeout=60,
        )
        if res.returncode == 0:
            try:
                routed.append(json.loads(res.stdout.strip().splitlines()[-1]))
            except Exception:
                pass
    return {"ok": True, "routed_count": len(routed), "routed": routed}


# ── CLI 命令面 ────────────────────────────────────────────────────────

def cmd_calendar(args: argparse.Namespace) -> int:
    """Dispatch calendar subcommand."""
    sub = getattr(args, "calendar_command", None)
    ics_file = getattr(args, "ics", None)
    transcript_file = getattr(args, "transcript", None)
    is_json = getattr(args, "json", False)

    if sub == "prebrief":
        if not ics_file or not Path(ics_file).is_file():
            console.print("[red]缺少 --ics <file>[/red]")
            return 1
        events = parse_ics(Path(ics_file).read_text(encoding="utf-8"))
        briefs = [prebrief(e) for e in events]
        if is_json:
            print(json.dumps(briefs, ensure_ascii=False, indent=2))
            return 0
        for b in briefs:
            console.print(Panel(
                f"时间: {b['when']}  |  地点: {b['location']}\n"
                f"议题: {'；'.join(b['agenda_points']) or '—'}\n"
                f"建议准备: {'、'.join(b['prep_materials'])}",
                title=f"📅 会前速递 · {b['title']}",
            ))
        return 0

    if sub == "minutes":
        if not transcript_file or not Path(transcript_file).is_file():
            console.print("[red]缺少 --transcript <file>[/red]")
            return 1
        items = extract_action_items(Path(transcript_file).read_text(encoding="utf-8"))
        do_route = getattr(args, "route", False)
        if do_route:
            items["signal_delivery"] = _route_to_signal(items)
        if is_json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
        t = Table(title="🗒 会议纪要提炼 · 督办清单", header_style="bold cyan")
        t.add_column("交办事项", ratio=1)
        t.add_column("责任人", style="cyan")
        t.add_column("时限", style="yellow")
        for a in items["action_items"]:
            t.add_row(a["task"], a["owner"], a["deadline"])
        console.print(t)
        if items["decisions"]:
            console.print(Panel("；".join(items["decisions"]), title="✅ 决策要点"))
        console.print(f"[dim]交办 {len(items['action_items'])} 项（责任人已定 {items['owner_assigned']}，时限已定 {items['deadline_assigned']}）[/dim]")
        return 0

    console.print("可用: calendar prebrief --ics <f> | calendar minutes --transcript <f> [--route]")
    return 1
