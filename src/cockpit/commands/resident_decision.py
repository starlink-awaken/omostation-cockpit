"""resident_decision — 常驻决策提案 triage & approve CLI (BET-Y1Q4-T8-21).

提供:
  cockpit resident decision triage  — 按状态/类型过滤决策提案
  cockpit resident decision approve  — 一键生成 BET-YAML 或 ADR-YAML 模板
  cockpit resident decision status   — 查看存量提案归档进度
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import _CLI_DIR

# WORKSPACE_ROOT: 环境变量优先, 否则从 commands/ 路径推导
WORKSPACE_ROOT = Path(
    os.environ.get(
        "WORKSPACE_ROOT",
        str(_CLI_DIR.parent.parent.parent.parent),  # .../Workspace
    )
)

# ── Paths (dynamic — recomputed from WORKSPACE_ROOT for testability) ──


def _get_proposal_dir() -> Path:
    return WORKSPACE_ROOT / ".omo" / "_knowledge" / "decision-proposals"


def _get_inbox_dir() -> Path:
    return WORKSPACE_ROOT / ".omo" / "_knowledge" / "evolution-proposals"

# ── Status constants ──
STATUS_REVIEWED = "reviewed"
STATUS_PROMOTED = "promoted"
STATUS_DISMISSED = "dismissed"
VALID_STATUSES = (STATUS_REVIEWED, STATUS_PROMOTED, STATUS_DISMISSED)


def _scan_proposals(status_filter: str | None = None, type_filter: str | None = None) -> list[dict[str, Any]]:
    """扫描 decision-proposals 目录，返回结构化提案列表."""
    results = []
    proposal_dir = _get_proposal_dir()
    if not proposal_dir.exists():
        return results

    for md_file in sorted(proposal_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8", errors="replace")
        meta = _parse_frontmatter(content)

        # 跳过非提案文件
        if not meta.get("schema") and not meta.get("trigger_event_type"):
            continue

        current_status = meta.get("status") or meta.get("triage_status")
        if status_filter and current_status != status_filter:
            continue

        event_type = meta.get("trigger_event_type") or meta.get("event_type", "")
        if type_filter and type_filter.lower() not in event_type.lower():
            continue

        results.append({
            "file": str(md_file.relative_to(WORKSPACE_ROOT)),
            "filename": md_file.name,
            "schema": meta.get("schema", ""),
            "status": current_status or "unreviewed",
            "event_type": event_type,
            "trace_id": meta.get("trace_id", ""),
            "proposal_count": meta.get("proposal_count", 0),
            "generated_at": meta.get("generated_at", ""),
        })

    return results


def _parse_frontmatter(content: str) -> dict[str, str]:
    """简单 YAML frontmatter 解析."""
    meta: dict[str, str] = {}
    if not content.startswith("---"):
        return meta

    end = content.find("---", 3)
    if end == -1:
        return meta

    for line in content[3:end].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def cmd_triage(args: argparse.Namespace) -> int:
    """triage 子命令：列出并过滤提案."""
    proposals = _scan_proposals(
        status_filter=getattr(args, "status", None),
        type_filter=getattr(args, "type", None),
    )

    if getattr(args, "json", False):
        print(json.dumps(proposals, ensure_ascii=False, indent=2))
        return 0

    if not proposals:
        print("✅ 无匹配提案")
        return 0

    print(f"📋 决策提案列表 ({len(proposals)} 份)\n")
    for p in proposals:
        status_icon = {
            STATUS_REVIEWED: "✅",
            STATUS_PROMOTED: "🚀",
            STATUS_DISMISSED: "⛔",
        }.get(p["status"], "⬜")
        print(f"  {status_icon} [{p['status']}] {p['filename']}")
        print(f"      event_type: {p['event_type'] or 'N/A'}  proposals: {p['proposal_count']}")
        print(f"      file: {p['file']}")
        print()

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """status 子命令：查看归档进度."""
    proposals = _scan_proposals()
    total = len(proposals)
    by_status: dict[str, int] = {}
    for p in proposals:
        s = p["status"]
        by_status[s] = by_status.get(s, 0) + 1

    reviewed = by_status.get(STATUS_REVIEWED, 0) + by_status.get(STATUS_PROMOTED, 0) + by_status.get(STATUS_DISMISSED, 0)
    unreviewed = total - reviewed

    print(f"📊 决策提案归档进度\n")
    print(f"  总量: {total} 份")
    if total > 0:
        print(f"  已归档: {reviewed} 份 ({reviewed/total*100:.1f}%)")
    else:
        print(f"  已归档: 0 份")
    print(f"  待处理: {unreviewed} 份")
    print()
    for s, count in sorted(by_status.items()):
        print(f"    {s}: {count}")

    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """approve 子命令：一键生成 BET-YAML 或 ADR-YAML 模板."""
    proposal_id = getattr(args, "proposal_id", None)
    target = getattr(args, "target", "bet")

    if not proposal_id:
        print("❌ 必须指定 --proposal-id", file=sys.stderr)
        return 1

    matched = list(_get_proposal_dir().glob(f"*{proposal_id}*"))
    if not matched:
        print(f"❌ 未找到匹配 '{proposal_id}' 的提案", file=sys.stderr)
        return 1

    proposal_file = matched[0]
    content = proposal_file.read_text(encoding="utf-8", errors="replace")
    meta = _parse_frontmatter(content)

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    title = _extract_title(content) or f"Promoted from {proposal_file.stem}"

    if target == "adr":
        template = _generate_adr_yaml(title, proposal_file, meta, now)
        output_name = f"adr-{proposal_file.stem}.yaml"
    else:
        template = _generate_bet_yaml(title, proposal_file, meta, now)
        output_name = f"bet-{proposal_file.stem}.yaml"

    output_path = WORKSPACE_ROOT / ".omo" / "_delivery" / "templates" / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template, encoding="utf-8")

    print(f"✅ 模板已生成: {output_path.relative_to(WORKSPACE_ROOT)}")
    print(f"   来源: {proposal_file.relative_to(WORKSPACE_ROOT)}")
    print(f"   类型: {target.upper()}")
    return 0


def _extract_title(content: str) -> str:
    """从 markdown 内容提取第一个 H1 标题."""
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _generate_bet_yaml(title: str, source: Path, meta: dict[str, str], now: str) -> str:
    """生成 BET-YAML 模板."""
    return f"""---
schema: bet-template/v1
title: "{title}"
source_proposal: {source.name}
source_trace_id: "{meta.get('trace_id', '')}"
status: draft
created: {now}
decision_ref: decision://pending/{source.stem}
---

# {title}

## 背景

本 Bet 由决策提案 {source.name} 晋升生成。

## 目标

<!-- 请补充具体目标 -->

## 完成标准

- [ ] <!-- 标准 1 -->
- [ ] <!-- 标准 2 -->

## 验证

- cmd: make gac-local-gate
  expect: exit 0
"""


def _generate_adr_yaml(title: str, source: Path, meta: dict[str, str], now: str) -> str:
    """生成 ADR-YAML 模板."""
    return f"""---
schema: adr-template/v1
title: "{title}"
source_proposal: {source.name}
source_trace_id: "{meta.get('trace_id', '')}"
status: proposed
created: {now}
decision_ref: decision://pending/{source.stem}
---

# {title}

## Status

Proposed

## Context

本 ADR 由决策提案 {source.name} 晋升生成。

## Decision

<!-- 请补充架构决策 -->

## Consequences

<!-- 请补充影响分析 -->
"""


def register_resident_subparser(subparsers: argparse._SubParsersAction) -> None:
    """注册 resident decision 子命令到 cockpit CLI."""
    triage_parser = subparsers.add_parser("triage", help="按状态/类型过滤决策提案")
    triage_parser.add_argument("--status", choices=VALID_STATUSES, help="按状态过滤")
    triage_parser.add_argument("--type", help="按事件类型过滤 (如 WorkflowFailed)")
    triage_parser.add_argument("--json", action="store_true", help="JSON 输出")
    triage_parser.set_defaults(func=cmd_triage)

    status_parser = subparsers.add_parser("status", help="查看归档进度")
    status_parser.set_defaults(func=cmd_status)

    approve_parser = subparsers.add_parser("approve", help="一键生成 BET/ADR 模板")
    approve_parser.add_argument("--proposal-id", required=True, help="提案 ID 或文件名片段")
    approve_parser.add_argument("--target", choices=["bet", "adr"], default="bet", help="模板类型")
    approve_parser.set_defaults(func=cmd_approve)
