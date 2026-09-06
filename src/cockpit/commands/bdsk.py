"""cockpit.commands.bdsk — B.D.S.K. 四角对抗审议一键评审 (BET-Y1Q4-T5-02).

Business / Developer / Security / Knowledge 四角规则启发式审议：
读取方案文本 → 信号词推导各角关注点与风险评分 → 输出 MADR 决策报告
（4 角评语 + 风险雷达表 + 折中方案）。确定性实现，零模型调用；
LLM 增强由 bdsk_engine 的 BOS persona 面另行提供。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

ROLES = ("business", "developer", "security", "knowledge")
ROLE_LABELS = {
    "business": "💼 商业 (Business)",
    "developer": "🔧 研发 (Developer)",
    "security": "🛡️ 安全 (Security)",
    "knowledge": "📚 知识 (Knowledge)",
}

# 信号词 → (维度, 分值增量, 关注点)
_SIGNALS: list[tuple[str, str, int, str]] = [
    (r"预算|成本|费用|万元|报价", "cost", 1, "预算边界需量化并锁定"),
    (r"外包|采购|第三方|供应商", "cost", 1, "第三方依赖引入长期成本"),
    (r"工期|里程碑|deadline|上线时间", "schedule", 1, "工期硬约束需缓冲"),
    (r"重构|迁移|替换|下线", "schedule", 1, "迁移/重构周期易低估"),
    (r"涉密|敏感|身份证|密钥|鉴权|脱敏", "security", 2, "敏感数据面需 DLP 与权限收敛"),
    (r"外发|对外|公网|开放接口", "security", 1, "外发面需审计与重放拦截"),
    (r"微服务|拆分|重构", "maintainability", 1, "拆分粒度需以团队规模校准"),
    (r"试验|探索|预研|POC|验证", "unknown", 2, "探索性假设需 falsifier 明确"),
    (r"AI|大模型|LoRA|推理", "unknown", 1, "模型行为非确定性需评测集"),
    (r"文档|ADR|决策记录|复盘", "unknown", -1, "决策已进入知识沉淀流程"),
]


def _radar_scores(text: str) -> dict[str, int]:
    scores = {"cost": 2, "schedule": 2, "security": 2, "maintainability": 2, "unknown": 2}
    for pat, dim, delta, _ in _SIGNALS:
        if re.search(pat, text, re.IGNORECASE):
            scores[dim] = min(5, scores[dim] + delta)
    return scores


def _role_verdicts(text: str, radar: dict[str, int]) -> dict[str, dict[str, str]]:
    points = _key_points(text)
    return {
        "business": {
            "verdict": "approve_with_conditions" if radar["cost"] >= 4 else "approve",
            "comment": (
                f"方案要点 {len(points)} 项。"
                + ("成本信号密集（雷达 cost={}），建议先锁定预算边界与 ROI 度量口径。".format(radar["cost"]) if radar["cost"] >= 4 else "成本面信号温和，可按 MVP 切片验证。")
            ),
        },
        "developer": {
            "verdict": "approve_with_conditions" if radar["maintainability"] >= 4 or radar["schedule"] >= 4 else "approve",
            "comment": (
                "实现路径可行。"
                + ("拆分/迁移面大，建议先出接口契约与回滚方案再动工。" if radar["maintainability"] >= 4 else "建议按模块切片交付，保持每片可独立验证。")
            ),
        },
        "security": {
            "verdict": "reject" if radar["security"] >= 4 else ("approve_with_conditions" if radar["security"] >= 3 else "approve"),
            "comment": (
                "安全信号强：敏感/外发面需先过 DLP 扫描、权限收敛与重放拦截，"
                "未闭环前不应外发。" if radar["security"] >= 4 else "常规安全面可控，保持审计与最小权限即可。"
            ),
        },
        "knowledge": {
            "verdict": "approve_with_conditions" if radar["unknown"] >= 4 else "approve",
            "comment": (
                "未知度偏高：探索性假设需逐条配 falsifier 与复盘锚点，"
                "结论沉淀回 ADR/Skills。" if radar["unknown"] >= 4 else "已有决策记录路径，按 ADR 惯例沉淀即可。"
            ),
        },
    }


def _key_points(text: str, limit: int = 5) -> list[str]:
    points = []
    for line in text.splitlines():
        s = line.strip()
        if len(s) >= 10 and not s.startswith(("#", "|", ">", "-")):
            points.append(s[:50])
        if len(points) >= limit:
            break
    return points or ["（方案要点待补充）"]


def _compromise(verdicts: dict[str, dict[str, str]], radar: dict[str, int]) -> str:
    hard = [r for r, v in verdicts.items() if v["verdict"] == "reject"]
    cond = [r for r, v in verdicts.items() if v["verdict"] == "approve_with_conditions"]
    if hard:
        return (
            f"安全角为一票否决（{'、'.join(hard)}）——建议先收敛敏感/外发面并复评；"
            f"其余角的条件项（{'、'.join(cond) or '无'}）在复评时一并闭环。"
        )
    if cond:
        return f"四角均可推进，附条件项：{'、'.join(cond)}。建议按条件切片交付，每片带验证锚点。"
    return "四角全绿，按方案推进；保持 ADR 沉淀与复盘节奏。"


def evaluate_spec(spec_text: str) -> dict[str, Any]:
    """Run the 4-role adversarial review and build the MADR-style report."""
    radar = _radar_scores(spec_text)
    verdicts = _role_verdicts(spec_text, radar)
    compromise = _compromise(verdicts, radar)
    overall = "reject" if any(v["verdict"] == "reject" for v in verdicts.values()) else (
        "approve_with_conditions" if any(v["verdict"] == "approve_with_conditions" for v in verdicts.values()) else "approve"
    )
    return {
        "schema": "cockpit.bdsk.evaluate.v1",
        "radar": radar,
        "verdicts": verdicts,
        "compromise": compromise,
        "overall": overall,
    }


def render_madr(result: dict[str, Any], spec_path: str) -> str:
    """Markdown MADR decision report (done_when[1]: 4 角评语+雷达+折中方案)。"""
    ts = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        "# B.D.S.K. 四角对抗审议决策报告 (MADR)",
        "",
        f"> 评审对象: `{spec_path}` | 时间: {ts} | 引擎: 规则启发式 (零模型)",
        "",
        "## 背景",
        "",
        "本报告由 B.D.S.K. 四角对抗审议引擎自动生成，供署名确认前的风险决策参考。",
        "",
        "## 四角评语",
        "",
    ]
    for role in ROLES:
        v = result["verdicts"][role]
        lines.append(f"### {ROLE_LABELS[role]} — {v['verdict']}")
        lines.append("")
        lines.append(v["comment"])
        lines.append("")
    lines.extend(["## 风险雷达", "", "| 维度 | 风险分 (0-5) | 量级 |", "|------|------|------|"])
    dim_labels = {"cost": "成本", "schedule": "工期", "security": "安全", "maintainability": "可维护性", "unknown": "未知度"}
    for dim, score in result["radar"].items():
        bar = "█" * score + "░" * (5 - score)
        lines.append(f"| {dim_labels[dim]} | {score} | {bar} |")
    lines.extend(["", "## 折中方案", "", result["compromise"], "",
                  "## 决议建议", "",
                  f"总体结论: **{result['overall']}**", "",
                  f"*由 cockpit bdsk evaluate 生成于 {ts}*"])
    return "\n".join(lines)


DEMO_SPEC = """# 示例方案：区域全民健康信息平台互联互通升级

预算 180 万元，工期 6 个月里程碑交付，涉及敏感健康数据脱敏与外发接口开放。
采用微服务拆分重构现有单体，并引入大模型推理试验（POC）辅助公文拟办。
要求沉淀 ADR 决策记录并完成安全评审。
"""


def cmd_bdsk(args: argparse.Namespace) -> int:
    """Dispatch bdsk subcommand."""
    sub = getattr(args, "bdsk_subcmd", None) or "evaluate"
    if sub == "evaluate":
        return cmd_bdsk_evaluate(args)
    console.print("可用: bdsk evaluate --spec <file> [--out <md>] | bdsk evaluate --demo [--json]")
    return 1


def cmd_bdsk_evaluate(args: argparse.Namespace) -> int:
    spec_path = getattr(args, "spec", None)
    is_demo = getattr(args, "demo", False)
    if is_demo:
        spec_text, label = DEMO_SPEC, "(demo)"
    elif spec_path and Path(spec_path).is_file():
        spec_text, label = Path(spec_path).read_text(encoding="utf-8"), spec_path
    elif spec_path:
        console.print(f"[red]spec 文件不存在: {spec_path}[/red]")
        return 1
    else:
        console.print("[red]缺少 --spec <file> 或 --demo[/red]")
        return 1

    result = evaluate_spec(spec_text)
    report = render_madr(result, label)
    out = getattr(args, "out", None)
    if out:
        Path(out).write_text(report, encoding="utf-8")
        console.print(f"[green]✅ MADR 报告已写入 {out}[/green]")
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        console.print(Panel(
            f"总体结论: [bold]{result['overall']}[/bold] | "
            f"雷达: {result['radar']}\n折中: {result['compromise'][:80]}",
            title=f"🧭 B.D.S.K. 评审 — {label}",
        ))
    return 0
