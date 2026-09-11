"""Zhixing Meta-Ontology (ZMO/v2) & Model-Driven Formal Axioms.

Defines the six sovereign planes, ontological entities, directional predicates,
and formal constraint axioms for the 43191 Zhixing Dashboard.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Set, Tuple

# ── 1. The Six Sovereign Planes (六大主权平面) ──────────────────────────────────
SOVEREIGN_PLANES: Dict[str, Dict[str, Any]] = {
    "control": {
        "id": "control",
        "name": "控制面 (Control Plane)",
        "symbol": "🛡️",
        "description": "治理门禁、防御策略、常驻守护与不变量守卫",
        "entities": ["gate", "gate_evidence", "policy", "daemon", "invariant", "admission_rule"]
    },
    "business": {
        "id": "business",
        "name": "业务面 (Business Plane)",
        "symbol": "💼",
        "description": "业务场景卡、执行旅程、案件用例与人类主权裁决",
        "entities": ["scene_card", "journey", "work_case", "human_verdict", "signal"]
    },
    "delivery": {
        "id": "delivery",
        "name": "交付面 (Delivery Plane)",
        "symbol": "🚀",
        "description": "三年愿景、战略目标、战役集、里程碑、BET战役、机器规范与交付凭据",
        "entities": ["vision", "objective", "campaign", "milestone", "bet", "spec", "evidence", "work_packet"]
    },
    "swarm": {
        "id": "swarm",
        "name": "协作面 (Swarm Plane)",
        "symbol": "🤝",
        "description": "智能体蜂群、角色合同、AetherForge 本地算力池与 BOS 协议网格",
        "entities": ["agent_role", "agent_observation", "compute", "bos_service", "engine_pool", "run"]
    },
    "knowledge": {
        "id": "knowledge",
        "name": "知识面 (Knowledge Plane)",
        "symbol": "📚",
        "description": "49份受管架构文档、白皮书、六大记忆通道与 ADR 决策记录",
        "entities": ["document", "heading", "memory_type", "memory_route", "adr", "skill"]
    },
    "evolution": {
        "id": "evolution",
        "name": "进化面 (Evolution Plane)",
        "symbol": "🧬",
        "description": "交付踩坑复盘、SEMA 信念结晶、度量指标与自适应演进",
        "entities": ["retro", "sema_crystallization", "metric", "drift_record", "evaluation_vector"]
    }
}

# ── 2. Ontological Predicates & Inverse Relations (本体谓词与逆关系) ───────────
PREDICATES: Dict[str, Dict[str, Any]] = {
    "governs": {
        "description": "门禁或防御策略对任务执行、工作树或算力的准入守门",
        "inverse": "governed_by",
        "source_plane": "control",
        "target_planes": ["delivery", "swarm", "business"]
    },
    "governed_by": {
        "description": "实体受到门禁与策略的合规性管辖",
        "inverse": "governs"
    },
    "drives": {
        "description": "本地主权算力网关驱动智能体离线推理与投机解码",
        "inverse": "powered_by",
        "source_plane": "swarm",
        "target_planes": ["swarm", "delivery"]
    },
    "powered_by": {
        "description": "智能体推理与执行依托本地算力提供支撑",
        "inverse": "drives"
    },
    "guides": {
        "description": "受管白皮书、治理章程或规范对交付战役提供架构指导",
        "inverse": "implements",
        "source_plane": "knowledge",
        "target_planes": ["delivery", "control"]
    },
    "implements": {
        "description": "交付战役或代码工程实现受管文档中的架构规范",
        "inverse": "guides"
    },
    "specifies": {
        "description": "机器规范(Spec)哈希对工程交付提供不可篡改的验收约束",
        "inverse": "accepts_spec",
        "source_plane": "delivery",
        "target_planes": ["delivery"]
    },
    "accepts_spec": {
        "description": "BET 战役显式绑定并接受该机器规范",
        "inverse": "specifies"
    },
    "produces": {
        "description": "执行流水线产出不可篡改的代码 Diff、测试报告或凭据",
        "inverse": "produced_by",
        "source_plane": "swarm",
        "target_planes": ["delivery", "control"]
    },
    "produced_by": {
        "description": "产出物由特定智能体流水线生成",
        "inverse": "produces"
    },
    "crystallizes_to": {
        "description": "历史踩坑复盘提炼结晶为永久防腐规则与 SEMA 经验信念",
        "inverse": "derived_from",
        "source_plane": "evolution",
        "target_planes": ["knowledge", "control"]
    },
    "derived_from": {
        "description": "经验规则来源于历史真实复盘",
        "inverse": "crystallizes_to"
    },
    "adjudicates": {
        "description": "人类主权负责人审查、确认并签署案件用例或终验成果",
        "inverse": "adjudicated_by",
        "source_plane": "business",
        "target_planes": ["delivery", "business"]
    },
    "adjudicated_by": {
        "description": "业务成果经过人类主权负责人署名批准",
        "inverse": "adjudicates"
    }
}

# ── 3. Four Model-Driven Formal Axioms (四大形式约束公理) ──────────────────────
AXIOMS = {
    "Axiom_Unidirectional_Projection": {
        "id": "AXIOM-01",
        "name": "视窗只读单向流动公理",
        "formal": "∀ e ∈ Dashboard, AccessMode(e) = ReadOnly ∧ Origin(e) ∈ SSOT",
        "description": "控制面严格作为大设备真值的增量投影视窗，严禁包含任何直接写回主仓或未经审计的外部网络请求。"
    },
    "Axiom_TriAxis_Evidence": {
        "id": "AXIOM-02",
        "name": "三维凭证闭环公理",
        "formal": "Status(Bet) = DONE ⟹ ∃ e_eng ∧ ∃ e_ops ∧ ∃ e_val",
        "description": "任何 BET 标记为完成，必须同时具备工程 Commit/Diff、运行态门禁通过与价值复盘三维证据链条。"
    },
    "Axiom_Sovereign_Compute_AirGap": {
        "id": "AXIOM-03",
        "name": "主权算力物理隔离公理",
        "formal": "∀ m ∈ InferenceTasks, Endpoint(m) = http://127.0.0.1:8000/",
        "description": "所有模型推理、向量嵌入与精准重排必须路由至本地 AetherForge 网关，禁止外部数据泄露或公网依赖。"
    },
    "Axiom_Worktree_Sandboxing": {
        "id": "AXIOM-04",
        "name": "工作树物理隔离公理",
        "formal": "∀ w ∈ WriteOperations, Path(w) ∩ MainWorkspace = ∅ ∧ Path(w) ∈ Worktree",
        "description": "所有代码修改与治理变更必须在隔离的工作树中完成，主仓常驻处于只读守门状态。"
    }
}

def get_entity_plane(kind: str) -> str:
    """Resolve which sovereign plane an entity kind belongs to."""
    kind = (kind or "").lower()
    for plane_id, plane in SOVEREIGN_PLANES.items():
        if kind in plane["entities"]:
            return plane_id
    if "doc" in kind or "heading" in kind or "adr" in kind or "memory" in kind:
        return "knowledge"
    if "gate" in kind or "policy" in kind or "daemon" in kind or "rule" in kind:
        return "control"
    if "bet" in kind or "milestone" in kind or "campaign" in kind or "spec" in kind or "evidence" in kind:
        return "delivery"
    if "agent" in kind or "compute" in kind or "bos" in kind or "run" in kind:
        return "swarm"
    if "scene" in kind or "case" in kind or "verdict" in kind:
        return "business"
    if "retro" in kind or "metric" in kind or "sema" in kind:
        return "evolution"
    return "delivery"

def check_axioms(trace_graph: Dict[str, Any], portfolio: Dict[str, Any]) -> Dict[str, Any]:
    """Perform static axiomatic verification against the live graph and portfolio."""
    nodes = trace_graph.get("nodes", [])
    edges = trace_graph.get("edges", [])
    bets = portfolio.get("bet_records", [])
    
    findings = []
    
    # 1. Verify Axiom 02: Tri-axis evidence for done bets
    done_bets = [b for b in bets if b.get("status") in ("done", "complete", "resolved")]
    incomplete_evidence_bets = []
    for b in done_bets:
        ev = b.get("completion_evidence")
        if not ev:
            incomplete_evidence_bets.append(b.get("id"))
    if incomplete_evidence_bets:
        findings.append({
            "axiom": "AXIOM-02",
            "title": "三维凭证不完整风险",
            "severity": "medium",
            "count": len(incomplete_evidence_bets),
            "sample": incomplete_evidence_bets[:3],
            "recommendation": "对终态战役补齐 engineering, operational, value 三维归档证明"
        })
        
    # 2. Verify Axiom 03: Sovereign compute binding
    compute_nodes = [n for n in nodes if n.get("kind") == "compute"]
    if not compute_nodes and nodes:
        findings.append({
            "axiom": "AXIOM-03",
            "title": "主权算力网关未连接",
            "severity": "high",
            "recommendation": "启动 AetherForge (Port 8000) 并接入 compute 拓扑节点"
        })
        
    # 3. Verify Isolated / Orphan Nodes
    connected_node_ids = set()
    for e in edges:
        connected_node_ids.add(e.get("from"))
        connected_node_ids.add(e.get("to"))
        
    orphan_count = sum(1 for n in nodes if n.get("id") not in connected_node_ids)
    
    return {
        "status": "COMPLIANT" if not any(f["severity"] == "high" for f in findings) else "WARNING",
        "findings": findings,
        "metrics": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "total_bets": len(bets),
            "done_bets": len(done_bets),
            "orphan_nodes": orphan_count,
            "connectivity_ratio": round((len(nodes) - orphan_count) / max(1, len(nodes)), 4)
        }
    }

def export_ontology_schema() -> Dict[str, Any]:
    """Export complete Zhixing Meta-Ontology JSON schema."""
    return {
        "schema": "zhixing-meta-ontology/v2",
        "sovereign_planes": SOVEREIGN_PLANES,
        "predicates": PREDICATES,
        "axioms": AXIOMS
    }