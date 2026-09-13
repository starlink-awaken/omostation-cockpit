"""cockpit.commands.topology — 主权系统八层架构拓扑、活体工作树感知与调用链 CLI。

将 Dashboard 实战孵化的 TopologyEngine 核心能力沉淀为主仓命令行标准第一公民。
支持:
  - cockpit topology overview [--json]
  - cockpit topology agents [--collisions] [--json]
  - cockpit topology sentinel [--json]
  - cockpit topology callchains [--cid <id>] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cockpit.observatory.event_bus import get_event_bus
from cockpit.observatory.topology_engine import TopologyEngine

console = Console()


def _get_engine() -> TopologyEngine:
    return TopologyEngine()


def cmd_topology(args: argparse.Namespace) -> int:
    """主入口分发：overview / agents / sentinel / callchains / guard / events / listen。"""
    subcmd = getattr(args, "topology_command", None) or "overview"
    as_json = getattr(args, "json", False) or getattr(args, "global_output", "text") == "json"

    engine = _get_engine()

    if subcmd == "overview":
        return _handle_overview(engine, as_json)
    elif subcmd == "agents":
        only_collisions = getattr(args, "collisions", False)
        return _handle_agents(engine, as_json, only_collisions)
    elif subcmd == "sentinel":
        return _handle_sentinel(engine, as_json)
    elif subcmd == "callchains":
        cid = getattr(args, "cid", None)
        return _handle_callchains(engine, as_json, cid)
    elif subcmd == "guard":
        paths = getattr(args, "paths", [])
        strict = getattr(args, "strict", False)
        return _handle_guard(engine, as_json, paths, strict)
    elif subcmd == "events":
        limit = getattr(args, "limit", 20)
        evt_type = getattr(args, "type", None)
        severity = getattr(args, "severity", None)
        return _handle_events(as_json, limit, evt_type, severity)
    elif subcmd == "listen":
        filter_type = getattr(args, "type", None)
        timeout = getattr(args, "timeout", None)
        count = getattr(args, "count", None)
        return _handle_listen(filter_type, timeout, count)

    console.print(f"[red]未知 topology 子命令: {subcmd}[/]")
    console.print("可用: overview, agents, sentinel, callchains, guard, events, listen")
    return 1




def _handle_overview(engine: TopologyEngine, as_json: bool) -> int:
    overview = engine.get_overview()
    if as_json:
        print(json.dumps(overview, ensure_ascii=False, indent=2))
        return 0

    console.print(Panel.fit(
        f"[bold cyan]织星主权系统八层架构拓扑总览[/]\n"
        f"[dim]eCOS 版本:[/] [green]{overview.get('ecos_version', 'v6.0')}[/]  |  "
        f"[dim]受管项目:[/] [yellow]{overview.get('total_projects', 0)}[/]  |  "
        f"[dim]MCP 工具:[/] [cyan]{overview.get('total_mcp_tools', 0)}[/]  |  "
        f"[dim]BOS 路由:[/] [magenta]{overview.get('total_bos_services', 0)}[/]  |  "
        f"[dim]端口网格:[/] [blue]{overview.get('total_ports', 0)}[/]",
        border_style="cyan"
    ))

    table = Table(title="八层架构分层状态与项目资产", border_style="dim")
    table.add_column("层级", style="bold")
    table.add_column("层级名称", style="cyan")
    table.add_column("纳管项目", style="white")
    table.add_column("MCP 工具", justify="right", style="green")
    table.add_column("BOS 路由", justify="right", style="magenta")
    table.add_column("CLI 命令", justify="right", style="yellow")

    for lid, linfo in overview.get("layers", {}).items():
        projs = ", ".join(linfo.get("projects", [])) or "-"
        table.add_row(
            lid,
            linfo.get("name", lid),
            projs,
            str(linfo.get("mcp_tools_count", 0)),
            str(linfo.get("bos_services_count", 0)),
            str(linfo.get("cli_commands_count", 0)),
        )
    console.print(table)
    return 0


def _handle_agents(engine: TopologyEngine, as_json: bool, only_collisions: bool) -> int:
    data = engine.get_workspace_agents()
    if as_json:
        if only_collisions:
            print(json.dumps({
                "collisions_count": data.get("collisions_count", 0),
                "collisions": data.get("collisions", []),
            }, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    total_wt = data.get("total_worktrees", 0)
    col_count = data.get("collisions_count", 0)

    # 冲突预警横幅
    if col_count > 0:
        console.print(Panel(
            f"[bold red]⚠️  Multi-Agent 并发写锁冲突预警 (Collision Guard)[/]\n"
            f"检测到 [bold yellow]{col_count}[/] 个核心项目正面临多分支并发改动踩踏风险！\n"
            f"[dim]安全建议: 合并前执行[/] [cyan]bash bin/gac/gac-worktree.sh guard-submodules[/] [dim]进行等价校验[/]",
            border_style="red"
        ))

        col_table = Table(title="并发冲突详情清单", border_style="red")
        col_table.add_column("项目 ID", style="bold red")
        col_table.add_column("层级", style="dim")
        col_table.add_column("并发 Worktree 数量", justify="right", style="yellow")
        col_table.add_column("关联分支快照", style="white")

        for c in data.get("collisions", []):
            branches = ", ".join(c.get("branches", [])[:4])
            if len(c.get("branches", [])) > 4:
                branches += f" ... (+{len(c.get('branches', [])) - 4})"
            col_table.add_row(
                c.get("project_id"),
                c.get("layer"),
                str(c.get("worktrees_count")),
                branches
            )
        console.print(col_table)
    else:
        console.print(f"[green]✅ 当前无高危并发写冲突 (活跃工作树: {total_wt})[/]")

    if not only_collisions:
        # 层级热力图
        heat_table = Table(title=f"八层架构作业热力分布 (总工作树: {total_wt})", border_style="blue")
        heat_table.add_column("架构层级", style="bold")
        heat_table.add_column("活跃 Worktree", justify="right", style="cyan")
        heat_table.add_column("受波及项目", style="white")

        for lid, h in data.get("layer_heatmap", {}).items():
            cnt = h.get("count", 0)
            if cnt > 0:
                heat_table.add_row(lid, str(cnt), ", ".join(h.get("projects_affected", [])))
        console.print(heat_table)

    return 0


def _handle_sentinel(engine: TopologyEngine, as_json: bool) -> int:
    data = engine.get_sentinel_status()
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    sub_summary = data.get("submodules_summary", {})
    port_summary = data.get("ports_summary", {})

    state_color = "green" if sub_summary.get("overall_state") == "ALL_ALIGNED" else "yellow"
    console.print(Panel.fit(
        f"[bold]16 子模块与主权端口哨兵探针 (Sentinel)[/]\n"
        f"[dim]子模块状态:[/] [{state_color}]{sub_summary.get('overall_state')}[/] ({sub_summary.get('aligned')}/{sub_summary.get('total')} 对齐)  |  "
        f"[dim]主权端口:[/] [green]{port_summary.get('listening')}[/] 监听中, [dim]{port_summary.get('offline')}[/] 离线",
        border_style="cyan"
    ))

    # 子模块清单
    s_table = Table(title="子模块 Gitlink 对齐快照", border_style="dim")
    s_table.add_column("子模块路径", style="cyan")
    s_table.add_column("HEAD Commit", style="dim")
    s_table.add_column("状态", style="bold")

    for sm in data.get("submodules", []):
        st = sm.get("status")
        st_styled = f"[green]{st}[/]" if st == "ALIGNED" else f"[yellow]{st}[/]"
        s_table.add_row(sm.get("path"), sm.get("commit")[:8], st_styled)
    console.print(s_table)

    # 端口清单
    p_table = Table(title="主权关键端口监听状态", border_style="dim")
    p_table.add_column("端口", justify="right", style="bold")
    p_table.add_column("服务名称", style="white")
    p_table.add_column("所属项目", style="cyan")
    p_table.add_column("状态", style="bold")

    for pr in data.get("ports", []):
        st = pr.get("status")
        st_styled = "[green]LISTENING[/]" if st == "LISTENING" else "[dim]OFFLINE[/]"
        p_table.add_row(str(pr.get("port")), pr.get("name"), pr.get("owner"), st_styled)
    console.print(p_table)

    return 0


def _handle_callchains(engine: TopologyEngine, as_json: bool, cid: str | None) -> int:
    chains = engine.get_callchains()
    if cid:
        chains = [c for c in chains if c["id"] == cid or cid.lower() in c["name"].lower()]

    if as_json:
        print(json.dumps(chains, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold cyan]主权系统跨层调用链时序与流光穿透 ({len(chains)} 条已验证)[/]\n")
    for c in chains:
        console.print(Panel(
            f"[bold cyan]{c.get('name')}[/] ({c.get('id')})  [dim]| 分类:[/] {c.get('category')}  [dim]| 耗时:[/] [green]{c.get('latency_ms')}ms[/]\n"
            f"[dim]契约文档:[/] [yellow]{c.get('doc_ref')}[/]\n"
            f"[dim]穿透层级:[/] {' -> '.join(c.get('layers_involved', []))}\n"
            f"[dim]参与项目:[/] {', '.join(c.get('projects_involved', []))}\n\n"
            f"[white]{c.get('description')}[/]",
            border_style="cyan"
        ))

        step_table = Table(title=f"{c.get('name')} 步骤时序", border_style="dim")
        step_table.add_column("步数", justify="right", style="dim")
        step_table.add_column("参与者 (Actor)", style="bold cyan")
        step_table.add_column("层级", style="dim")
        step_table.add_column("动作说明", style="white")
        step_table.add_column("契约规约", style="magenta")

        for st in c.get("steps", []):
            step_table.add_row(
                str(st.get("step")),
                st.get("actor"),
                st.get("layer"),
                st.get("action"),
                st.get("contract")
            )
        console.print(step_table)
        console.print()

    return 0


def _handle_guard(engine: TopologyEngine, as_json: bool, paths: list[str], strict: bool) -> int:
    res = engine.check_path_collisions(paths)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 1 if (strict and not res.get("safe", True)) else 0

    sev = res.get("max_severity", "CLEAN")
    is_safe = res.get("safe", True)

    if is_safe:
        panel_border = "green"
        header_title = "[bold green]🛡️ 研发安全避障：工作区干净，无并发踩踏风险[/]"
    elif sev == "MEDIUM":
        panel_border = "yellow"
        header_title = "[bold yellow]⚠️ 研发安全避障：存在中度并发或跨层级关联，请留意[/]"
    else:
        panel_border = "red"
        header_title = "[bold red]🚨 研发安全避障：检测到严重并发写锁踩踏隐患！[/]"

    console.print(Panel(
        f"{header_title}\n\n"
        f"[bold]风险评级:[/] {sev}  [dim]|[/] [bold]目标路径:[/] {len(paths)} 个  [dim]|[/] [bold]涉及项目:[/] {', '.join(res.get('affected_projects', []))}\n"
        f"[dim]{res.get('summary')}[/]\n\n"
        f"[bold cyan]避障指引:[/] {res.get('recommendation')}",
        border_style=panel_border
    ))

    conflicts = res.get("conflicts", [])
    if conflicts:
        c_table = Table(title="并发冲突与潜在争用明细", border_style="red" if not is_safe else "yellow")
        c_table.add_column("项目", style="bold cyan")
        c_table.add_column("风险等级", justify="center")
        c_table.add_column("工作树数", justify="right")
        c_table.add_column("冲突分支/Agent", style="yellow")
        c_table.add_column("原因与指引", style="dim")

        for c in conflicts:
            c_sev = c.get("severity", "UNKNOWN")
            c_sev_style = "[bold red]CRITICAL[/]" if c_sev == "CRITICAL" else ("[yellow]HIGH[/]" if c_sev == "HIGH" else "[dim]LOW[/]")
            c_table.add_row(
                c.get("project_name", c.get("project_id")),
                c_sev_style,
                str(c.get("concurrent_worktrees", 0)),
                ", ".join(c.get("conflicting_branches", [])) or "none",
                f"{c.get('reason')}\n-> {c.get('advice')}"
            )
        console.print(c_table)

    if strict and not is_safe:
        console.print("\n[bold red]❌ Strict 模式已拦截：由于检测到并发冲突，终止操作。[/]")
        return 1
    return 0


def _handle_events(as_json: bool, limit: int, evt_type: str | None, severity: str | None) -> int:
    bus = get_event_bus()
    events = bus.get_recent(limit=limit, event_type=evt_type, severity=severity)
    if as_json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold cyan]📜 主权态势事件时间线 (最近 {len(events)} 条)[/]\n")
    if not events:
        console.print("[dim]当前事件总线队列中暂无匹配事件。[/]")
        return 0

    table = Table(border_style="dim")
    table.add_column("时间", style="dim")
    table.add_column("级别", justify="center")
    table.add_column("类型", style="bold cyan")
    table.add_column("项目", style="magenta")
    table.add_column("标题 / 内容", style="white")
    table.add_column("避障指引", style="dim")

    for e in events:
        sev = e.get("severity", "INFO")
        sev_styled = (
            "[bold red]CRITICAL[/]" if sev == "CRITICAL"
            else ("[yellow]HIGH[/]" if sev == "HIGH"
            else ("[blue]MEDIUM[/]" if sev == "MEDIUM"
            else "[dim]INFO[/]"))
        )
        table.add_row(
            e.get("timestamp", "")[-8:],
            sev_styled,
            e.get("type", "EVENT"),
            e.get("project_id", ""),
            e.get("title", ""),
            e.get("advice", "")
        )

    console.print(table)
    return 0


def _handle_listen(filter_type: str | None, timeout: int | None, max_count: int | None) -> int:
    console.print(Panel.fit(
        "[bold cyan]🎧 正在流式监听主权态势事件总线 (Observatory Event Stream)[/]\n"
        f"[dim]过滤类型:[/] {filter_type or '全部 (ALL)'}  [dim]| 超时:[/] {f'{timeout}s' if timeout else '持续 (Ctrl+C 退出)'}  [dim]| 限制条数:[/] {max_count or '无限制'}",
        border_style="cyan"
    ))

    bus = get_event_bus()
    queue = bus.subscribe()

    async def _listen_loop() -> None:
        received = 0
        start_time = asyncio.get_running_loop().time()
        try:
            while True:
                if timeout:
                    elapsed = asyncio.get_running_loop().time() - start_time
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        console.print(f"[yellow]⏰ 达到设定的超时时间 ({timeout}s)，停止监听。[/]")
                        break
                    timeout_param = remaining
                else:
                    timeout_param = 1.0

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout_param)
                    if filter_type and event.type.upper() != filter_type.strip().upper():
                        continue

                    received += 1
                    sev = event.severity.upper()
                    border = "red" if sev in ("CRITICAL", "HIGH") else ("yellow" if sev == "MEDIUM" else "green")
                    console.print(Panel(
                        f"[bold {border}]{event.type}[/]  [dim]({event.severity})[/]  [dim]| 来源:[/] {event.source}  [dim]| 项目:[/] {event.project_id}\n"
                        f"[white]{event.title}[/]\n"
                        f"[dim]时间:[/] {event.timestamp}  [dim]| 指引:[/] [cyan]{event.advice}[/]",
                        border_style=border
                    ))

                    if max_count and received >= max_count:
                        console.print(f"[green]✅ 已捕获指定数量事件 ({max_count} 条)，退出监听。[/]")
                        break
                except TimeoutError:
                    if timeout:
                        elapsed = asyncio.get_running_loop().time() - start_time
                        if elapsed >= timeout:
                            console.print(f"[yellow]⏰ 达到设定的超时时间 ({timeout}s)，停止监听。[/]")
                            break
        finally:
            bus.unsubscribe(queue)

    try:
        asyncio.run(_listen_loop())
    except KeyboardInterrupt:
        console.print("\n[dim]收到中断信号，停止监听。[/]")

    return 0


