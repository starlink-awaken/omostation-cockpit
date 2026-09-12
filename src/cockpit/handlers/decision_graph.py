"""
decision_graph.py — Cockpit 决策因果图聚合层 (T5-05)

纯函数聚合：读 graph.jsonl → 节点/边统计 + 祖先链与下游影响面。
不新增路由，仅作为 cockpit 现有 handler 的聚合函数层。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def decision_graph_summary(graph_path: str | Path) -> dict[str, Any]:
    """读取 graph.jsonl 返回节点 / 边统计。"""
    graph_path = Path(graph_path)
    nodes = 0
    edges = 0
    by_kind: dict[str, int] = {}
    if not graph_path.exists():
        return {"nodes": 0, "edges": 0, "by_kind": {}}
    with graph_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = __import__("json").loads(line)
            if "relation" in obj:
                edges += 1
            else:
                nodes += 1
                kind = obj.get("kind", "unknown")
                by_kind[kind] = by_kind.get(kind, 0) + 1
    return {"nodes": nodes, "edges": edges, "by_kind": by_kind}


def node_subgraph(graph_path: str | Path, node_id: str) -> dict[str, Any]:
    """返回指定节点的祖先链与下游影响面（BFS）。"""
    from omo.resident.decision_bridge import DecisionGraph

    g = DecisionGraph(graph_path)
    try:
        node = g.get_node(node_id)
    except Exception:
        return {"error": "node not found"}
    return {
        "node": node.to_dict(),
        "ancestors": g.ancestors(node_id),
        "downstream": g.downstream(node_id),
    }
