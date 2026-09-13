"""cockpit.observatory.mcp_server — 织星主权系统官方 Observatory MCP Server。

向所有 AI Agent (Claude Code, Codex, Cursor, Subagents) 开放原生工具能力：
  1. get_project_perception(project_id) -> 针对单项目的超紧凑 LLM 架构感知与并发冲突防撞 (< 800 tokens)
  2. check_workspace_collisions() -> 全局未合并工作树并发写锁冲突风险与守卫命令
  3. get_submodule_sentinel() -> 16 个子模块 Gitlink 对齐快照与 7 大主权端口探针
  4. get_callchain_contract(chain_id) -> 4 大跨层调用链时序与契约规约
  5. get_system_overview() -> 八层架构项目分布与资产统计
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from cockpit.observatory.event_bus import get_event_bus
from cockpit.observatory.topology_engine import TopologyEngine

# 实例化 FastMCP 服务器
mcp = FastMCP(
    "cockpit-observatory",
    instructions="织星主权操作系统架构拓扑、活体工作树并发冲突防撞与状态哨兵中枢"
)

_ENGINE: TopologyEngine | None = None


def _get_engine() -> TopologyEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = TopologyEngine()
    return _ENGINE


def _envelope(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def get_project_perception(project_id: str) -> str:
    """获取指定受管项目的超紧凑架构感知信息（< 800 Tokens）。

    包含：所属层级与角色、直接上下游依赖、当前并发写冲突状态（CRITICAL/HIGH/CLEAN）、
    并发工作树数量与分支快照、防护建议命令、端口与核心 BOS 接口。
    Agent 在编辑任何项目文件前应优先调用本工具进行避障感知。
    """
    engine = _get_engine()
    res = engine.get_agent_context(project_id)
    return _envelope(res)


@mcp.tool()
def check_workspace_collisions() -> str:
    """全局检查当前工作区内所有未合并工作树的并发写争用风险。

    扫描 42 个真实隔离工作树与当前活跃分支，识别多分支同时修改相同项目的踩踏隐患，
    输出高危项目列表、冲突 Agent/分支快照以及推荐的合流前防护命令。
    """
    engine = _get_engine()
    data = engine.get_workspace_agents()
    return _envelope({
        "collisions_count": data.get("collisions_count", 0),
        "total_active_worktrees": data.get("total_worktrees", 0),
        "collisions": data.get("collisions", []),
        "layer_heatmap": data.get("layer_heatmap", {}),
        "probed_at": data.get("probed_at"),
    })


@mcp.tool()
def check_path_collisions(paths: list[str]) -> str:
    """定向检查一组拟修改文件路径的并发争用与踩踏隐患。

    精确将传入的文件或目录路径归属到具体项目/治理平面，交叉比对当前活跃工作树、
    分支占号与冲突热点，输出风险分级 (CRITICAL/HIGH/MEDIUM/LOW/CLEAN) 与可执行避障建议。
    Agent 在认领任务 (claim) 或写入文件前应调用本工具自检。
    """
    engine = _get_engine()
    res = engine.check_path_collisions(paths)
    return _envelope(res)



@mcp.tool()
def get_submodule_sentinel() -> str:
    """探测主仓 16 个子模块 Gitlink 对齐状态与 7 大关键主权端口健康度。

    用于 Agent 在准备提交前进行环境完整性自检，排查是否有意外产生的子模块漂移或端口假死。
    """
    engine = _get_engine()
    data = engine.get_sentinel_status()
    return _envelope(data)


@mcp.tool()
def get_callchain_contract(chain_id: str = "") -> str:
    """获取主权系统 4 大核心跨层调用链的白盒时序步骤与契约规约。

    可选 chain_id:
      - chain_agora_bos: I0 主权总线 9 步派发链
      - chain_aetherforge_infer: 本地主权算力 0ms TTFT 推理链
      - chain_kos_memory: KOS 认知外脑受管记忆召回链
      - chain_omo_gac: GaC 规则门禁与 Merkle 账本防御链
    若不传 chain_id 则返回全部 4 条链路定义。
    """
    engine = _get_engine()
    chains = engine.get_callchains()
    if chain_id:
        matched = [c for c in chains if c["id"] == chain_id or chain_id.lower() in c["name"].lower()]
        return _envelope(matched[0] if matched else {"error": f"Chain '{chain_id}' not found", "available": [c["id"] for c in chains]})
    return _envelope(chains)


@mcp.tool()
def get_system_overview() -> str:
    """获取织星系统八层架构（L0~L4, I0, M0, X）总览、18 个受管项目与接口大厅汇总统计。"""
    engine = _get_engine()
    return _envelope(engine.get_overview())


@mcp.tool()
def get_recent_events(limit: int = 20, event_type: str = "", severity: str = "") -> str:
    """查询主权态势事件总线中的近期历史事件流。

    包含多 Agent 并发写冲突告警 (COLLISION_RISK)、工作树认领与释放 (WORKTREE_CLAIMED/RELEASED)、
    子模块漂移 (SENTINEL_DRIFT) 等，供 Agent 快速回溯最近发生了哪些架构突变。
    """
    bus = get_event_bus()
    events = bus.get_recent(
        limit=limit,
        event_type=event_type or None,
        severity=severity or None,
    )
    return _envelope({
        "ok": True,
        "count": len(events),
        "events": events,
    })


@mcp.tool()
def probe_live_status() -> str:
    """常驻 Agent (Resident Agent) 专用的极简活体健康与避障心跳看板 (< 500 tokens)。

    整合当前：
      1. 活跃 Worktree 总数与写争用风险统计；
      2. 16 个子模块 Gitlink 对齐总体状态；
      3. 关键端口监听状态；
      4. 最近 3 条高危突发态势事件。
    """
    engine = _get_engine()
    ag = engine.get_workspace_agents()
    sen = engine.get_sentinel_status()
    bus = get_event_bus()
    recent_critical = bus.get_recent(limit=3, severity="CRITICAL")

    return _envelope({
        "ok": True,
        "active_worktrees": ag.get("total_worktrees", 0),
        "collisions_count": ag.get("collisions_count", 0),
        "submodules_state": sen.get("submodules_summary", {}).get("overall_state", "UNKNOWN"),
        "ports_listening": sen.get("ports_summary", {}).get("listening", 0),
        "recent_critical_events": recent_critical,
        "probed_at": ag.get("probed_at"),
    })



def run_stdio() -> None:
    """stdio 模式入口"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_stdio()
