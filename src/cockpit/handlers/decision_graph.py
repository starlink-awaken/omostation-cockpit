"""
decision_graph.py — Cockpit 决策因果图聚合层 (T5-05)

纯函数聚合：读 graph.jsonl → 节点/边统计 + 全量列表 + 祖先链与下游影响面。
不新增路由，仅作为 cockpit 现有 handler 的聚合函数层。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _read_lines(graph_path: str | Path) -> list[dict[str, Any]]:
    """读取 JSONL 文件返回所有有效行。"""
    graph_path = Path(graph_path)
    if not graph_path.exists():
        return []
    lines: list[dict[str, Any]] = []
    with graph_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return lines


def decision_graph_summary(graph_path: str | Path) -> dict[str, Any]:
    """读取 graph.jsonl 返回节点/边统计 + actors/actions 聚合。"""
    lines = _read_lines(graph_path)
    nodes: list[dict] = []
    edges: list[dict] = []
    for obj in lines:
        if "relation" in obj:
            edges.append(obj)
        else:
            nodes.append(obj)

    by_kind = Counter(obj.get("kind", "unknown") for obj in nodes)
    actors = Counter(obj.get("actor", "unknown") for obj in nodes)
    actions = Counter(obj.get("action", "unknown") for obj in nodes)

    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "by_kind": dict(by_kind),
        "actors": dict(actors),
        "actions": dict(actions),
    }


def decision_graph_nodes(graph_path: str | Path) -> dict[str, Any]:
    """返回完整节点列表与边列表。"""
    lines = _read_lines(graph_path)
    nodes: list[dict] = []
    edges: list[dict] = []
    for obj in lines:
        if "relation" in obj:
            edges.append(obj)
        else:
            nodes.append(obj)
    return {"nodes": nodes, "edges": edges}


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
