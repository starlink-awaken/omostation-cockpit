"""cockpit.commands.strategy — 个人战略决策沙盘命令面 (BET-Y2Q1-T5-01).

``cockpit strategy simulate --proposal <file>``：读取提案文本 → 调用 agora
核心 ``agora.orchestration.sandbox_sim``（商业/研发/安全/财务 4 角蒙特卡洛
推演）→ 输出收益分布表、最坏情况止损线与敏感性因子报告。
确定性实现，零模型调用；``--demo`` 内置样例提案。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

DEMO_PROPOSAL = """# 示例提案：自研向量检索服务替代外部订阅

预算 60 万元，工期 4 个月里程碑交付，替换现有第三方语义检索订阅（年费
28 万元）。涉及现有知识库迁移与重构，引入大模型重排试验（POC）验证召回
提升。预期年降本 20 万元并提效检索响应。要求沉淀 ADR 并完成安全评审。
"""


def _ws() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "docs" / "project-registry.yaml").is_file():
            return parent
    return Path.cwd()


def _load_core() -> tuple[Any, str]:
    """导入 agora 沙盘核心；缺失则返回 (None, 原因)。"""
    try:
        from agora.orchestration.sandbox_sim import simulate_proposal  # type: ignore

        return simulate_proposal, ""
    except ImportError:
        pass
    agora_src = _ws() / "projects" / "agora" / "src"
    if not (agora_src / "agora" / "orchestration" / "sandbox_sim.py").is_file():
        return None, "agora checkout 缺失 sandbox_sim（需 init projects/agora 子模块）"
    if str(agora_src) not in sys.path:
        sys.path.insert(0, str(agora_src))
    try:
        from agora.orchestration.sandbox_sim import simulate_proposal  # type: ignore

        return simulate_proposal, ""
    except ImportError as exc:
        return None, f"agora 核心导入失败: {exc}"


def render_report(result: dict[str, Any], label: str) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# 战略决策沙盘推演报告 — {label}",
        "",
        f"- 轮数: {result['rounds']} / 种子: {result['seed']} / 耗时: {result['elapsed_s']}s",
        "",
        "## 收益分布",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 期望收益（均值） | {result['mean']} |",
        f"| 波动（标准差） | {result['stdev']} |",
        f"| p5（悲观） | {result['p5']} |",
        f"| p50（中位） | {result['p50']} |",
        f"| p95（乐观） | {result['p95']} |",
        "",
        "## 最坏情况止损线",
        "",
        f"95% 的推演不差于 **{result['stop_loss']}** 分；若实际可接受下限高于此线，"
        "建议缩小投入切片或先行 POC 验证后再全量投入。",
        "",
        "## 4 角均值",
        "",
        "| 角色 | 均值 |",
        "| --- | --- |",
    ]
    for role, val in result["role_means"].items():
        lines.append(f"| {role} | {val} |")
    lines.extend(["", "## 敏感性因子（单因子 +20% 对均值的影响）", ""])
    for item in result["sensitivity"]:
        lines.append(f"- {item['factor']}: {item['delta_mean']:+.2f}")
    lines.extend(["", f"*由 cockpit strategy simulate 生成于 {ts}*"])
    return "\n".join(lines)


def cmd_strategy(args: argparse.Namespace) -> int:
    """Dispatch strategy subcommand."""
    sub = getattr(args, "strategy_subcmd", None) or "simulate"
    if sub != "simulate":
        console.print("可用: strategy simulate --proposal <file> [--rounds N] [--seed S] [--out md] | strategy simulate --demo [--json]")
        return 1
    return cmd_strategy_simulate(args)


def cmd_strategy_simulate(args: argparse.Namespace) -> int:
    proposal_path = getattr(args, "proposal", None)
    is_demo = getattr(args, "demo", False)
    if is_demo:
        proposal_text, label = DEMO_PROPOSAL, "(demo)"
    elif proposal_path and Path(proposal_path).is_file():
        proposal_text, label = Path(proposal_path).read_text(encoding="utf-8"), proposal_path
    elif proposal_path:
        console.print(f"[red]提案文件不存在: {proposal_path}[/red]")
        return 1
    else:
        console.print("[red]缺少 --proposal <file> 或 --demo[/red]")
        return 1

    simulate, err = _load_core()
    if simulate is None:
        console.print(f"[red]{err}[/red]")
        return 1
    try:
        result = simulate(
            proposal_text,
            rounds=int(getattr(args, "rounds", 100) or 100),
            seed=int(getattr(args, "seed", 42) if getattr(args, "seed", 42) is not None else 42),
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    out = getattr(args, "out", None)
    if out:
        Path(out).write_text(render_report(result, label), encoding="utf-8")
        console.print(f"[green]✅ 沙盘报告已写入 {out}[/green]")
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        table = Table(title=f"🎲 战略沙盘推演 — {label}")
        table.add_column("指标", style="cyan")
        table.add_column("数值", justify="right", style="green")
        for key in ("mean", "stdev", "p5", "p50", "p95", "stop_loss"):
            table.add_row(key, str(result[key]))
        console.print(table)
        console.print(
            Panel(
                f"止损线: [bold]{result['stop_loss']}[/bold] | "
                f"最敏感因子: {result['sensitivity'][0]['factor']} "
                f"({result['sensitivity'][0]['delta_mean']:+.2f}) | "
                f"耗时 {result['elapsed_s']}s",
                title="📊 结论",
            )
        )
    return 0
