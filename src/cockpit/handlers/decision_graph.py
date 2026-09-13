"""cockpit.handlers.decision_graph — 因果决策图聚合层 (BET-Y1Q4-T5-05).

文件契约: 直接读取 .omo/state/decision-graph/graph.jsonl,
不 import omo.resident.decision_bridge 模块 — 解耦架构。

纯函数, 零模型调用。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 默认图文件路径 (相对于 workspace 根)
DEFAULT_GRAPH = Path(".omo") / "state" / "decision-graph" / "graph.jsonl"


def _parse_line(line: str) -> dict[str, Any] | None:
    """解析一行 JSONL, 失败返回 None."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _load_graph(graph_file: str | Path) -> list[dict[str, Any]]:
    """加载所有图记录 (节点 + 边), 返回按顺序的 dict 列表."""
    path = Path(graph_file)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            rec = _parse_line(line)
            if rec is not None:
                records.append(rec)
    return records


def decision_graph_summary(graph_file: str | Path | None = None) -> dict[str, Any]:
    """聚合因果决策图状态, 供 Cockpit 前端/CLI 消费.

    Args:
        graph_file: 图文件路径, 默认 .omo/state/decision-graph/graph.jsonl

    Returns:
        {
            "total_nodes": int,
            "total_edges": int,
            "by_kind": {"patrol": N, "healing": N, "decision": N},
            "by_relation": {"CAUSED": N, "INFLUENCED": N},
            "recent_nodes": [最近 20 个节点的简化信息],
            "actor_activity": {actor: node_count},
            "action_frequency": {action: count},
        }
    """
    path = Path(graph_file) if graph_file else DEFAULT_GRAPH
    records = _load_graph(path)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for rec in records:
        if rec.get("_type") == "node":
            nodes.append(rec)
        elif rec.get("_type") == "edge":
            edges.append(rec)

    # 按 kind 统计
    by_kind: dict[str, int] = {}
    for n in nodes:
        k = n.get("kind", "unknown")
        by_kind[k] = by_kind.get(k, 0) + 1

    # 按 relation 统计
    by_relation: dict[str, int] = {}
    for e in edges:
        r = e.get("relation", "unknown")
        by_relation[r] = by_relation.get(r, 0) + 1

    # 按 actor 统计
    actor_activity: dict[str, int] = {}
    for n in nodes:
        a = n.get("actor", "")
        actor_activity[a] = actor_activity.get(a, 0) + 1

    # 按 action 统计
    action_frequency: dict[str, int] = {}
    for n in nodes:
        act = n.get("action", "")
        action_frequency[act] = action_frequency.get(act, 0) + 1

    # 最近 20 个节点 (时间戳降序)
    sorted_nodes = sorted(nodes, key=lambda n: n.get("ts", ""), reverse=True)
    recent = [
        {
            "node_id": n.get("node_id", ""),
            "kind": n.get("kind", ""),
            "actor": n.get("actor", ""),
            "action": n.get("action", ""),
            "ts": n.get("ts", ""),
        }
        for n in sorted_nodes[:20]
    ]

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "by_kind": by_kind,
        "by_relation": by_relation,
        "recent_nodes": recent,
        "actor_activity": actor_activity,
        "action_frequency": action_frequency,
    }


def decision_graph_edges(graph_file: str | Path | None = None) -> list[dict[str, Any]]:
    """返回所有因果边的列表, 供前端图渲染使用.

    Args:
        graph_file: 图文件路径

    Returns:
        边列表, 每条: {src, dst, relation}
    """
    path = Path(graph_file) if graph_file else DEFAULT_GRAPH
    records = _load_graph(path)
    return [
        {
            "src": e.get("src", ""),
            "dst": e.get("dst", ""),
            "relation": e.get("relation", ""),
        }
        for e in records
        if e.get("_type") == "edge"
    ]


def decision_graph_nodes(graph_file: str | Path | None = None) -> list[dict[str, Any]]:
    """返回所有节点的简化列表, 供前端图渲染使用.

    Args:
        graph_file: 图文件路径

    Returns:
        节点列表, 每个: {node_id, kind, actor, action, ts}
    """
    path = Path(graph_file) if graph_file else DEFAULT_GRAPH
    records = _load_graph(path)
    return [
        {
            "node_id": n.get("node_id", ""),
            "kind": n.get("kind", ""),
            "actor": n.get("actor", ""),
            "action": n.get("action", ""),
            "ts": n.get("ts", ""),
        }
        for n in records
        if n.get("_type") == "node"
    ]


def ancestor_chain(
    node_id: str,
    graph_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    """返回指定节点的因果祖先链 (BFS 反向遍历).

    纯文件读取, 不依赖 decision_bridge 模块。

    Args:
        node_id: 目标节点 ID
        graph_file: 图文件路径

    Returns:
        祖先列表, 每条: {node_id, kind, actor, action, relation, depth}
    """
    path = Path(graph_file) if graph_file else DEFAULT_GRAPH
    records = _load_graph(path)

    # 构建索引
    node_map: dict[str, dict[str, Any]] = {}
    reverse_edges: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        if rec.get("_type") == "node":
            node_map[rec.get("node_id", "")] = rec
        elif rec.get("_type") == "edge":
            dst = rec.get("dst", "")
            reverse_edges.setdefault(dst, []).append(rec)

    if node_id not in node_map:
        return []

    result: list[dict[str, Any]] = []
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(node_id, 0)]

    while queue:
        current_id, depth = queue.pop(0)
        if current_id in visited:
            continue
        visited.add(current_id)

        for edge in reverse_edges.get(current_id, []):
            src_id = edge.get("src", "")
            if src_id in visited or src_id not in node_map:
                continue
            src_node = node_map[src_id]
            result.append(
                {
                    "node_id": src_id,
                    "kind": src_node.get("kind", ""),
                    "actor": src_node.get("actor", ""),
                    "action": src_node.get("action", ""),
                    "relation": edge.get("relation", ""),
                    "depth": depth + 1,
                }
            )
            queue.append((src_id, depth + 1))

    return result
