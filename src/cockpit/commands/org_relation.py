"""org_relation.py — 组织人脉图谱查询命令 (BET-Y2Q1-T7-01)。

提供 cockpit org-relation <单位名> 入口，调用 Kairon OrgGraph 并渲染为 Rich 表格。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def cmd_org_relation(args) -> int:
    """查询组织人脉图谱，输出匹配的单位/人物/来件关系网络。"""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    query = getattr(args, "query", None) or getattr(args, "name", "")
    if not query:
        console.print("[yellow]用法: cockpit org-relation <单位名或人名>[/]")
        return 1

    # Resolve kairon package path
    ws_root = _find_workspace_root()
    kairon_src = ws_root / "projects" / "knowledge" / "kairon" / "src"
    if str(kairon_src) not in sys.path:
        sys.path.insert(0, str(kairon_src))

    try:
        from kairon.graph.org_graph import OrgGraph
    except ImportError:
        console.print("[red]无法加载 Kairon OrgGraph 模块。请确认 kairon 子模块已初始化。[/]")
        return 1

    # Load or create demo graph
    data_path = ws_root / ".omo" / "_data" / "org_graph.jsonl"
    if data_path.exists():
        graph = OrgGraph.load(data_path)
    else:
        graph = OrgGraph.demo()

    output_json = getattr(args, "json", False)
    if output_json:
        result = graph.network_view(query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # Rich table output
    matches = graph.search(query, top_k=10)
    if not matches:
        console.print(f"[dim]未找到与 '{query}' 相关的组织或人物。[/]")
        return 0

    console.print(f"\n[bold cyan]组织人脉图谱查询: {query}[/]\n")

    # Nodes table
    node_table = Table(title="匹配节点", border_style="cyan", show_lines=False)
    node_table.add_column("类型", style="bold", width=8)
    node_table.add_column("名称", style="white", min_width=16)
    node_table.add_column("职位/文号", style="dim", min_width=16)
    node_table.add_column("摘要", style="white", max_width=50)
    node_table.add_column("标签", style="yellow", max_width=20)

    type_labels = {
        "organization": "🏢 单位",
        "person": "👤 人物",
        "document": "📄 来件",
    }

    for node, score in matches:
        node_table.add_row(
            type_labels.get(node.node_type.value, node.node_type.value),
            f"{node.name} [dim]({score:.1f})[/]",
            node.title or "—",
            node.summary[:46] + "..." if len(node.summary) > 50 else (node.summary or "—"),
            ", ".join(node.tags[:3]) or "—",
        )

    console.print(node_table)

    # Relations table (from first match)
    if matches:
        top_node = matches[0][0]
        rels = graph.get_neighbors(top_node.id, direction="both")
        if rels:
            rel_table = Table(
                title=f"关系网络 — {top_node.name}",
                border_style="green",
                show_lines=False,
            )
            rel_table.add_column("源", style="cyan", min_width=12)
            rel_table.add_column("关系", style="bold", width=10)
            rel_table.add_column("目标", style="cyan", min_width=12)
            rel_table.add_column("频次", justify="right", width=6)
            rel_table.add_column("有效权重", justify="right", width=10)
            rel_table.add_column("最近联系", style="dim", width=20)

            for rel in rels:
                source = graph.get_node(rel.source_id)
                target = graph.get_node(rel.target_id)
                source_name = source.name if source else rel.source_id
                target_name = target.name if target else rel.target_id
                rel_table.add_row(
                    source_name,
                    rel.relation.value,
                    target_name,
                    str(rel.frequency),
                    f"{rel.effective_weight():.3f}",
                    rel.last_contact[:19] if rel.last_contact else "—",
                )

            console.print()
            console.print(rel_table)

    # Stats
    stats = graph.stats()
    console.print(
        f"\n[dim]图谱统计: {stats['total_nodes']} 节点, "
        f"{stats['total_relations']} 关系, "
        f"平均出度 {stats['avg_out_degree']:.2f}[/]"
    )

    return 0


def _find_workspace_root() -> Path:
    """Find workspace root by searching for .omo directory upward."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".omo").is_dir():
            return parent
    # Fallback: assume standard layout
    return current.parent.parent.parent.parent.parent
