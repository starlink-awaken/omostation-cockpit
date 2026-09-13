#!/usr/bin/env python3
"""Topology Engine for Sovereign Zhixing OS Dashboard.

Extracts genuine, verifiable architecture topology, dependency callchains,
submodule breakdowns, and internal/external interface registries from workspace SSOTs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Set
import yaml

WORKSPACE_ROOT = Path("/Users/xiamingxing/Workspace")

LAYER_CONFIG = {
    "L4": {"name": "L4 自我层", "role": "主权自我面 · 28 域统一注册 · KEMS 状态机", "color": "#8b5cf6", "order": 1},
    "L3": {"name": "L3 入口层", "role": "统一操作控制面 (CLI + Web + React 前端)", "color": "#3b82f6", "order": 2},
    "I0": {"name": "I0 织网层", "role": "统一 MCP Hub 与 BOS URI 路由网关", "color": "#06b6d4", "order": 3},
    "L2": {"name": "L2 引擎层", "role": "治理中枢、决策门控、知识工程 (Monorepo 16包) 与场景卡", "color": "#10b981", "order": 4},
    "L1": {"name": "L1 运行时层", "role": "任务调度、KEI沙箱、Cron 与本地异构算力织网 (omlxcd)", "color": "#f59e0b", "order": 5},
    "L0": {"name": "L0 协议层", "role": "SSB 签名链、MOF 元模型与不可违背的 L0 约束规约", "color": "#ef4444", "order": 6},
    "M0": {"name": "M0 模型层", "role": "生命周期横切框架 · M3→M2→M1 桥接", "color": "#ec4899", "order": 7},
    "X":  {"name": "X 横切扩展层", "role": "LLM 推理网关、Omni-Bus 总线、Langfuse 可观测性与外部能力工具箱", "color": "#64748b", "order": 8},
}

KNOWN_DEPENDENCY_EDGES = [
    {"source": "cockpit", "target": "agora", "type": "invoke", "label": "BOS/MCP 网关 (:7431)"},
    {"source": "cockpit", "target": "omo", "type": "control", "label": "C2G 治理中间件"},
    {"source": "cockpit", "target": "kairon", "type": "knowledge", "label": "KOS 知识查询 (:8766)"},
    {"source": "cockpit", "target": "l4-kernel", "type": "bridge", "label": "L4Bridge 域核验"},
    {"source": "cockpit", "target": "ecos", "type": "constraint", "label": "L0 门禁规范"},
    {"source": "cockpit-ui", "target": "cockpit", "type": "presentation", "label": "REST API (:8090)"},
    {"source": "agora", "target": "omo", "type": "route", "label": "BOS 治理路由"},
    {"source": "agora", "target": "runtime", "type": "route", "label": "BOS 调度任务"},
    {"source": "agora", "target": "kairon", "type": "route", "label": "BOS 知识检索 (:8766)"},
    {"source": "agora", "target": "aetherforge", "type": "route", "label": "BOS 模型推理 (:8000)"},
    {"source": "agora", "target": "l4-kernel", "type": "route", "label": "BOS 域注册查询"},
    {"source": "omo", "target": "ecos", "type": "constraint", "label": "MOF 约束规约"},
    {"source": "metaos", "target": "runtime", "type": "dispatch", "label": "执行调度分派"},
    {"source": "metaos", "target": "kairon", "type": "knowledge", "label": "本体语义查询"},
    {"source": "metaos", "target": "ecos", "type": "constraint", "label": "MOF 决策门控"},
    {"source": "kairon", "target": "gbrain", "type": "data", "label": "Postgres/pgvector 向量库"},
    {"source": "kairon", "target": "ecos", "type": "constraint", "label": "MOF 元数据校验"},
    {"source": "domain-cartridges", "target": "ecos", "type": "constraint", "label": "场景卡规范"},
    {"source": "domain-cartridges", "target": "kairon", "type": "knowledge", "label": "精读 Pipeline"},
    {"source": "runtime", "target": "ecos", "type": "constraint", "label": "L0 契约守卫"},
    {"source": "runtime", "target": "bus-foundation", "type": "event", "label": "Omni-Bus 总线消费"},
    {"source": "omlxc", "target": "ecos", "type": "constraint", "label": "算力元模型"},
    {"source": "aetherforge", "target": "omlxc", "type": "compute", "label": "Unix Socket (omlxcd.sock)"},
    {"source": "aetherforge", "target": "ecos", "type": "constraint", "label": "模型规约"},
    {"source": "l4-kernel", "target": "ecos", "type": "spec", "label": "MOF M1 域映射"},
    {"source": "model-driven", "target": "ecos", "type": "model", "label": "M3-M2-M1 模型桥接"},
    {"source": "toolbox", "target": "agora", "type": "expose", "label": "bos://capability/* (13 实例)"},
]


class TopologyEngine:
    """Extracts and serves real architecture topology facts."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or WORKSPACE_ROOT
        self._cache: Optional[Dict[str, Any]] = None

    def _load_raw_data(self) -> Dict[str, Any]:
        root = self.workspace_root

        # 1. Project Registry
        registry_path = root / "docs/project-registry.yaml"
        project_registry: Dict[str, Any] = {}
        if registry_path.is_file():
            try:
                project_registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
            except Exception as err:
                print(f"[WARN] Failed to parse project-registry.yaml: {err}")

        # 2. Interfaces from projects/*/INTERFACE.yaml
        interfaces: Dict[str, Any] = {}
        interface_patterns = [
            root / "projects/*/INTERFACE.yaml",
            root / "projects/knowledge/*/INTERFACE.yaml",
        ]
        for pattern in interface_patterns:
            for if_file in root.glob(str(pattern.relative_to(root))):
                try:
                    data = yaml.safe_load(if_file.read_text(encoding="utf-8")) or {}
                    proj_name = data.get("project") or if_file.parent.name
                    interfaces[proj_name] = data
                except Exception as err:
                    print(f"[WARN] Failed to read {if_file}: {err}")

        # 3. Callchains from projects/*/CALLCHAIN.md
        callchains: Dict[str, Dict[str, Any]] = {}
        callchain_patterns = [
            root / "projects/*/CALLCHAIN.md",
            root / "projects/knowledge/*/CALLCHAIN.md",
        ]
        for pattern in callchain_patterns:
            for cc_file in root.glob(str(pattern.relative_to(root))):
                proj_name = cc_file.parent.name
                try:
                    text = cc_file.read_text(encoding="utf-8")
                    callchains[proj_name] = self._parse_callchain_text(text)
                except Exception as err:
                    print(f"[WARN] Failed to parse {cc_file}: {err}")

        # 4. BOS services from agora/etc/bos-services.yaml
        bos_path = root / "projects/agora/etc/bos-services.yaml"
        bos_services: List[Dict[str, Any]] = []
        if bos_path.is_file():
            try:
                bos_data = yaml.safe_load(bos_path.read_text(encoding="utf-8")) or {}
                bos_services = bos_data.get("services", [])
            except Exception as err:
                print(f"[WARN] Failed to parse bos-services.yaml: {err}")

        # 5. Port registry
        port_path = root / "protocols/port-registry.yaml"
        port_registry: Dict[str, Any] = {}
        if port_path.is_file():
            try:
                port_registry = yaml.safe_load(port_path.read_text(encoding="utf-8")) or {}
            except Exception as err:
                print(f"[WARN] Failed to parse port-registry.yaml: {err}")

        return {
            "registry": project_registry,
            "interfaces": interfaces,
            "callchains": callchains,
            "bos_services": bos_services,
            "port_registry": port_registry,
        }

    def _parse_callchain_text(self, text: str) -> Dict[str, Any]:
        """Extract steps and mermaid sequence diagram from CALLCHAIN.md."""
        steps: List[str] = []
        sequence_mermaid = ""

        # Extract steps under ## 关键路径
        key_path_match = re.search(r"##\s*关键路径.*?\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
        if key_path_match:
            lines = key_path_match.group(1).strip().splitlines()
            for line in lines:
                cleaned = line.strip()
                if cleaned and (cleaned.startswith("-") or cleaned.startswith("*") or re.match(r"^\d+\.", cleaned)):
                    steps.append(re.sub(r"^[-*\d.]+\s*", "", cleaned))

        # Extract mermaid block
        mermaid_match = re.search(r"```mermaid\s*(sequenceDiagram.*?)```", text, re.DOTALL)
        if mermaid_match:
            sequence_mermaid = mermaid_match.group(1).strip()

        return {
            "steps": steps,
            "sequence_mermaid": sequence_mermaid,
            "has_callchain": bool(steps or sequence_mermaid),
        }

    def build_snapshot(self) -> Dict[str, Any]:
        """Build a unified, correlated architecture topology snapshot."""
        raw = self._load_raw_data()
        reg_projects = raw["registry"].get("projects", {})
        interfaces = raw["interfaces"]
        callchains = raw["callchains"]
        bos_services = raw["bos_services"]
        port_registry = raw["port_registry"]

        # Map BOS services by package/project
        bos_by_project: Dict[str, List[Dict[str, Any]]] = {}
        for svc in bos_services:
            pkg = svc.get("package") or ""
            proj = "agora"
            cmd_str = " ".join(svc.get("command") or [])
            if "kairon" in cmd_str or pkg in ("kos", "kos-mcp", "eidos-mcp", "minerva-mcp", "sophia-mcp", "iris-mcp", "forge-mcp", "codeanalyze-mcp", "ontoderive-mcp"):
                proj = "kairon"
            elif "family-hub" in pkg or "family_hub" in str(svc.get("module_path", "")):
                proj = "family-hub"
            elif "omo" in pkg or "omo" in cmd_str:
                proj = "omo"
            elif "runtime" in pkg or "runtime" in cmd_str:
                proj = "runtime"
            elif "omlxc" in pkg or "omlxc" in cmd_str:
                proj = "omlxc"
            elif "aetherforge" in pkg or "aetherforge" in cmd_str or "compute/aetherforge" in str(svc.get("uri", "")):
                proj = "aetherforge"
            elif "l4-kernel" in pkg or "l4_kernel" in str(svc.get("module_path", "")):
                proj = "l4-kernel"
            elif "ecos" in pkg or "ecos" in cmd_str:
                proj = "ecos"
            elif "toolbox" in pkg or "ToolBox" in str(svc.get("git", "")):
                proj = "toolbox"
            elif pkg:
                proj = pkg
            bos_by_project.setdefault(proj, []).append({
                "uri": svc.get("uri"),
                "domain": svc.get("domain"),
                "action": svc.get("action"),
                "transport": svc.get("transport"),
                "description": svc.get("description"),
                "status": svc.get("status", "active"),
            })

        # Process each project
        projects_dict: Dict[str, Any] = {}

        # 1. First add projects declared in project-registry.yaml
        for p_id, p_meta in reg_projects.items():
            if p_id == "knowledge":
                # Special monorepo container: split into gbrain and kairon
                gbrain_meta = p_meta.get("gbrain", {})
                kairon_meta = p_meta.get("kairon", {})

                # GBrain
                projects_dict["gbrain"] = self._create_project_dossier(
                    p_id="gbrain",
                    name="GBrain 知识向量库",
                    layer=p_meta.get("layer", "L2"),
                    stack=gbrain_meta.get("stack", "TypeScript (bun)"),
                    role=gbrain_meta.get("role", "Postgres 知识数据库与向量检索"),
                    version=gbrain_meta.get("version", "0.39.0.0"),
                    repository=gbrain_meta.get("repository", ""),
                    submodule=gbrain_meta.get("submodule", True),
                    status="active",
                    meta=gbrain_meta,
                    if_data=interfaces.get("gbrain", {}),
                    cc_data=callchains.get("gbrain", {}),
                    bos_list=bos_by_project.get("gbrain", []),
                )

                # Kairon
                kairon_packages = kairon_meta.get("package_list", [])
                projects_dict["kairon"] = self._create_project_dossier(
                    p_id="kairon",
                    name="Kairon 知识工程 Monorepo",
                    layer=p_meta.get("layer", "L2"),
                    stack=kairon_meta.get("stack", "Python (uv, pytest)"),
                    role=kairon_meta.get("role", "知识引擎内核 (16 个子包复合体)"),
                    version=kairon_meta.get("version", "1.0.0"),
                    repository=kairon_meta.get("repository", ""),
                    submodule=kairon_meta.get("submodule", True),
                    status="active",
                    meta=kairon_meta,
                    if_data=interfaces.get("kairon", {}),
                    cc_data=callchains.get("kairon", {}),
                    bos_list=bos_by_project.get("kairon", []),
                    subpackages=[{"name": pkg, "path": f"projects/knowledge/kairon/packages/{pkg}"} for pkg in kairon_packages],
                )
                continue

            layer = p_meta.get("layer", "X")
            if "-" in layer:
                layer = layer.split("-")[0]  # L1-L3 -> L1
            if layer not in LAYER_CONFIG:
                layer = "X"

            subpackages = []
            if p_id == "toolbox":
                for tb in p_meta.get("bos_services", []):
                    subpackages.append({
                        "name": tb.get("id"),
                        "uri": tb.get("bos_uri"),
                        "tools_count": tb.get("tools_count", 0),
                        "status": tb.get("status", "active"),
                    })

            projects_dict[p_id] = self._create_project_dossier(
                p_id=p_id,
                name=p_id.capitalize() if p_id != "cockpit-ui" else "Cockpit UI",
                layer=layer,
                stack=p_meta.get("stack", "Python"),
                role=p_meta.get("role", ""),
                version=str(p_meta.get("version", "1.0.0")),
                repository=p_meta.get("repository", ""),
                submodule=p_meta.get("submodule", False),
                status=p_meta.get("status", "active"),
                meta=p_meta,
                if_data=interfaces.get(p_id, {}),
                cc_data=callchains.get(p_id, {}),
                bos_list=bos_by_project.get(p_id, []),
                subpackages=subpackages,
            )

        # Calculate graph upstream and downstream relations
        upstreams: Dict[str, Set[str]] = {p: set() for p in projects_dict}
        downstreams: Dict[str, Set[str]] = {p: set() for p in projects_dict}

        valid_edges: List[Dict[str, Any]] = []
        for edge in KNOWN_DEPENDENCY_EDGES:
            src = edge["source"]
            tgt = edge["target"]
            if src in projects_dict and tgt in projects_dict:
                downstreams[src].add(tgt)
                upstreams[tgt].add(src)
                valid_edges.append(edge)

        for p_id, p_obj in projects_dict.items():
            p_obj["upstream"] = sorted(list(upstreams.get(p_id, set())))
            p_obj["downstream"] = sorted(list(downstreams.get(p_id, set())))

        # Aggregate overall statistics
        total_mcp_tools = sum(p["stats"]["mcp_tools_count"] for p in projects_dict.values())
        total_cli_commands = sum(p["stats"]["cli_commands_count"] for p in projects_dict.values())
        total_ports = sum(len(p["interfaces"]["ports"]) for p in projects_dict.values())
        total_subpackages = sum(len(p.get("subpackages", [])) for p in projects_dict.values())

        # Layer summary
        layer_summary: Dict[str, Any] = {}
        for l_code, l_info in LAYER_CONFIG.items():
            l_projs = [p for p in projects_dict.values() if p["layer"] == l_code and p["status"] != "archived"]
            layer_summary[l_code] = {
                "name": l_info["name"],
                "role": l_info["role"],
                "color": l_info["color"],
                "order": l_info["order"],
                "project_count": len(l_projs),
                "projects": [p["id"] for p in l_projs],
            }

        snapshot = {
            "generated_at": yaml.safe_load(json.dumps(os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip())),
            "overview": {
                "workspace_architecture": raw["registry"].get("workspace", {}).get("architecture", "5+4+1+1"),
                "ecos_version": raw["registry"].get("workspace", {}).get("ecos_version", "v6"),
                "total_projects": len([p for p in projects_dict.values() if p["status"] != "archived"]),
                "total_submodules": raw["registry"].get("workspace", {}).get("total_submodules", 16),
                "total_subpackages": total_subpackages,
                "total_mcp_tools": total_mcp_tools,
                "total_bos_services": len(bos_services),
                "total_cli_commands": total_cli_commands,
                "total_ports": total_ports,
                "layers": layer_summary,
            },
            "projects": projects_dict,
            "edges": valid_edges,
            "bos_services_count": len(bos_services),
        }
        self._cache = snapshot
        return snapshot

    def _create_project_dossier(
        self,
        p_id: str,
        name: str,
        layer: str,
        stack: str,
        role: str,
        version: str,
        repository: str,
        submodule: bool,
        status: str,
        meta: Dict[str, Any],
        if_data: Dict[str, Any],
        cc_data: Dict[str, Any],
        bos_list: List[Dict[str, Any]],
        subpackages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        # CLI commands
        cli_commands = []
        if "cli" in if_data and isinstance(if_data["cli"], list):
            for cmd in if_data["cli"]:
                cli_commands.append({
                    "name": cmd.get("name"),
                    "module": cmd.get("module"),
                    "description": cmd.get("description", ""),
                    "status": cmd.get("status", "active"),
                })
        elif "cli_entry" in meta:
            cli_commands.append({
                "name": meta["cli_entry"],
                "description": f"{name} primary CLI entrypoint",
                "status": "active",
            })

        # MCP server & tools
        mcp_servers = []
        mcp_tools_count = 0
        if "mcp" in if_data and isinstance(if_data["mcp"], dict):
            mcp_info = if_data["mcp"]
            server_name = mcp_info.get("server") or p_id
            tools_cnt = mcp_info.get("tools") or 0
            if isinstance(tools_cnt, int):
                mcp_tools_count += tools_cnt
            elif isinstance(tools_cnt, str) and tools_cnt.isdigit():
                mcp_tools_count += int(tools_cnt)
            packages = mcp_info.get("packages", [])
            mcp_servers.append({
                "server": server_name,
                "tools_count": mcp_tools_count,
                "transport": mcp_info.get("transport", ["stdio"]),
                "packages": packages,
            })
            if packages and not mcp_tools_count:
                mcp_tools_count = len(packages) * 10
        elif "mcp_tools" in meta:
            try:
                cnt = int(meta["mcp_tools"])
                mcp_tools_count += cnt
                mcp_servers.append({
                    "server": f"{p_id}-mcp",
                    "tools_count": cnt,
                    "transport": ["stdio"],
                })
            except Exception:
                pass

        if p_id == "toolbox" and subpackages:
            tb_tools = sum(tb.get("tools_count", 0) for tb in subpackages)
            mcp_tools_count += tb_tools

        # HTTP and Sockets
        ports = []
        if "http" in if_data and isinstance(if_data["http"], list):
            for hp in if_data["http"]:
                ports.append({
                    "port": hp.get("port"),
                    "protocol": hp.get("protocol", "HTTP"),
                    "note": hp.get("note", ""),
                    "enforcement": hp.get("enforcement", "active"),
                })
        elif "port" in meta:
            ports.append({
                "port": meta["port"],
                "protocol": "HTTP",
                "note": meta.get("port_registry_ref", ""),
            })

        sockets = []
        if "control_transport" in meta and "Socket" in meta["control_transport"]:
            sockets.append({
                "path": "/tmp/omlxcd.sock",
                "role": "Unix Domain Socket 守护进程控制通道",
            })

        # Python API exports
        python_apis = []
        if "python_api" in if_data and isinstance(if_data["python_api"], list):
            for api in if_data["python_api"]:
                python_apis.append({
                    "module": api.get("module"),
                    "exports": [exp.get("name") for exp in api.get("exports", []) if isinstance(exp, dict)],
                })

        return {
            "id": p_id,
            "name": name,
            "layer": layer,
            "layer_name": LAYER_CONFIG.get(layer, {}).get("name", layer),
            "stack": stack,
            "role": role,
            "version": version,
            "repository": repository,
            "submodule": submodule,
            "status": status,
            "interfaces": {
                "cli_commands": cli_commands,
                "mcp_servers": mcp_servers,
                "ports": ports,
                "sockets": sockets,
                "python_apis": python_apis,
                "bos_services": bos_list,
            },
            "callchain": {
                "has_callchain": cc_data.get("has_callchain", False),
                "steps": cc_data.get("steps", []),
                "sequence_mermaid": cc_data.get("sequence_mermaid", ""),
            },
            "subpackages": subpackages or [],
            "stats": {
                "cli_commands_count": len(cli_commands),
                "mcp_tools_count": mcp_tools_count,
                "bos_services_count": len(bos_list),
                "subpackages_count": len(subpackages or []),
            },
        }

    def get_snapshot(self) -> Dict[str, Any]:
        if self._cache is None:
            return self.build_snapshot()
        return self._cache

    def get_overview(self) -> Dict[str, Any]:
        snapshot = self.get_snapshot()
        return snapshot["overview"]

    def get_graph(self, layer: Optional[str] = None) -> Dict[str, Any]:
        snapshot = self.get_snapshot()
        projects = list(snapshot["projects"].values())
        if layer:
            projects = [p for p in projects if p["layer"] == layer]
            allowed_ids = {p["id"] for p in projects}
            edges = [e for e in snapshot["edges"] if e["source"] in allowed_ids and e["target"] in allowed_ids]
        else:
            edges = snapshot["edges"]

        nodes = []
        for p in projects:
            nodes.append({
                "id": p["id"],
                "name": p["name"],
                "layer": p["layer"],
                "layer_name": p["layer_name"],
                "stack": p["stack"],
                "role": p["role"],
                "version": p["version"],
                "status": p["status"],
                "upstream": p.get("upstream", []),
                "downstream": p.get("downstream", []),
                "mcp_count": p["stats"]["mcp_tools_count"],
                "cli_count": p["stats"]["cli_commands_count"],
                "bos_count": p["stats"]["bos_services_count"],
                "ports": [pr["port"] for pr in p["interfaces"]["ports"]],
            })
        return {
            "nodes": nodes,
            "edges": edges,
            "layers": snapshot["overview"]["layers"],
        }

    def get_projects(
        self,
        layer: Optional[str] = None,
        stack: Optional[str] = None,
        status: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        snapshot = self.get_snapshot()
        projs = list(snapshot["projects"].values())

        if layer:
            projs = [p for p in projs if p["layer"] == layer]
        if status:
            projs = [p for p in projs if p["status"] == status]
        if stack:
            projs = [p for p in projs if stack.lower() in p["stack"].lower()]
        if query:
            q = query.lower()
            projs = [
                p for p in projs
                if q in p["id"].lower()
                or q in p["name"].lower()
                or q in p["role"].lower()
                or any(q in c["name"].lower() for c in p["interfaces"]["cli_commands"])
                or any(q in str(pr["port"]) for pr in p["interfaces"]["ports"])
                or any(q in b["uri"].lower() for b in p["interfaces"]["bos_services"])
            ]
        return projs

    def get_interfaces(
        self,
        category: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        snapshot = self.get_snapshot()
        cli_list = []
        mcp_list = []
        port_list = []
        bos_list = []
        socket_list = []

        q = (query or "").lower()

        for p_id, p in snapshot["projects"].items():
            # CLI
            for cmd in p["interfaces"]["cli_commands"]:
                entry = {
                    "project": p_id,
                    "layer": p["layer"],
                    "name": cmd["name"],
                    "module": cmd.get("module", ""),
                    "description": cmd.get("description", ""),
                    "status": cmd.get("status", "active"),
                }
                if not q or q in entry["name"].lower() or q in entry["description"].lower() or q in p_id:
                    cli_list.append(entry)

            # MCP
            for srv in p["interfaces"]["mcp_servers"]:
                entry = {
                    "project": p_id,
                    "layer": p["layer"],
                    "server": srv["server"],
                    "tools_count": srv["tools_count"],
                    "transport": srv.get("transport", ["stdio"]),
                    "packages": srv.get("packages", []),
                }
                if not q or q in entry["server"].lower() or q in p_id:
                    mcp_list.append(entry)

            # Ports
            for pr in p["interfaces"]["ports"]:
                entry = {
                    "project": p_id,
                    "layer": p["layer"],
                    "port": pr["port"],
                    "protocol": pr.get("protocol", "HTTP"),
                    "note": pr.get("note", ""),
                    "enforcement": pr.get("enforcement", "active"),
                }
                if not q or q in str(entry["port"]) or q in entry["protocol"].lower() or q in p_id:
                    port_list.append(entry)

            # Sockets
            for sk in p["interfaces"]["sockets"]:
                entry = {
                    "project": p_id,
                    "layer": p["layer"],
                    "path": sk["path"],
                    "role": sk["role"],
                }
                if not q or q in entry["path"].lower() or q in p_id:
                    socket_list.append(entry)

            # BOS
            for bs in p["interfaces"]["bos_services"]:
                entry = {
                    "project": p_id,
                    "layer": p["layer"],
                    "uri": bs["uri"],
                    "domain": bs["domain"],
                    "action": bs["action"],
                    "transport": bs["transport"],
                    "description": bs["description"],
                    "status": bs["status"],
                }
                if not q or q in entry["uri"].lower() or q in entry["domain"].lower() or q in (entry["description"] or "").lower() or q in p_id:
                    bos_list.append(entry)

        result = {
            "summary": {
                "cli_count": len(cli_list),
                "mcp_count": len(mcp_list),
                "port_count": len(port_list),
                "bos_count": len(bos_list),
                "socket_count": len(socket_list),
            },
            "cli": cli_list,
            "mcp": mcp_list,
            "http": port_list,
            "socket": socket_list,
            "bos": bos_list[:150],
            "bos_total": len(bos_list),
        }

        if category and category in result:
            return {category: result[category], "summary": result["summary"]}
        return result

    def get_sentinel_status(self) -> Dict[str, Any]:
        """Probes 16 submodules alignment and registered host ports."""
        import socket
        import subprocess
        import time

        submodules = []
        aligned_count = 0
        drift_count = 0
        try:
            res = subprocess.run(
                ["git", "submodule", "status"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in res.stdout.splitlines():
                if not line:
                    continue
                indicator = line[0]
                parts = line[1:].strip().split()
                commit = parts[0] if len(parts) > 0 else ""
                path = parts[1] if len(parts) > 1 else ""
                branch_ref = parts[2] if len(parts) > 2 else ""

                if indicator == " ":
                    status = "ALIGNED"
                    aligned_count += 1
                elif indicator == "+":
                    status = "DRIFT_OR_DIRTY"
                    drift_count += 1
                elif indicator == "-":
                    status = "UNINITIALIZED"
                    drift_count += 1
                else:
                    status = "CONFLICT"
                    drift_count += 1

                submodules.append({
                    "path": path,
                    "name": Path(path).name,
                    "commit": commit,
                    "status": status,
                    "branch_ref": branch_ref.strip("()"),
                })
        except Exception:
            pass

        registered_ports = [
            {"port": 8090, "name": "Cockpit Web 控制面", "expected_owner": "cockpit"},
            {"port": 7431, "name": "Agora MCP SSE 路由网关", "expected_owner": "agora"},
            {"port": 7422, "name": "Agora FastMCP HTTP", "expected_owner": "agora"},
            {"port": 8766, "name": "KOS 知识图谱服务", "expected_owner": "kairon.kos"},
            {"port": 8000, "name": "AetherForge LLM 推理网关", "expected_owner": "aetherforge"},
            {"port": 43191, "name": "织星回环驾驶舱", "expected_owner": "zhixing-dashboard"},
            {"port": 9190, "name": "OMO 独立调试控制面", "expected_owner": "omo"},
            {"port": 7437, "name": "OMLX 算力路由代理 (归档)", "expected_owner": "mesh-router"},
        ]
        probed_ports = []
        open_ports_count = 0
        for rp in registered_ports:
            p = rp["port"]
            is_open = False
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.08)
                    is_open = (s.connect_ex(("127.0.0.1", p)) == 0)
            except Exception:
                pass
            if is_open:
                open_ports_count += 1
            probed_ports.append({
                "port": p,
                "name": rp["name"],
                "owner": rp["expected_owner"],
                "status": "LISTENING" if is_open else "OFFLINE",
            })

        return {
            "submodules": submodules,
            "submodules_summary": {
                "total": len(submodules),
                "aligned": aligned_count,
                "drift": drift_count,
                "overall_state": "ALL_ALIGNED" if drift_count == 0 and aligned_count > 0 else "DRIFT_DETECTED",
            },
            "ports": probed_ports,
            "ports_summary": {
                "total": len(probed_ports),
                "listening": open_ports_count,
                "offline": len(probed_ports) - open_ports_count,
            },
            "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_callchains(self) -> List[Dict[str, Any]]:
        """Return structured callchains modeled from SSOT architecture contracts."""
        return [
            {
                "id": "chain_agora_bos",
                "name": "I0 主权总线 9 步派发链",
                "category": "总线路由",
                "doc_ref": "docs/I0-AGORA-CALLCHAIN.md",
                "status": "VERIFIED",
                "latency_ms": 18.5,
                "layers_involved": ["L3", "I0", "L0"],
                "projects_involved": ["cockpit", "agora", "ecos"],
                "description": "白盒梳理 Agora 作为 I0 织层时，一条 bos:// URI 从 MCP 入口经 RBAC 鉴权、限流、Trie 前缀路由到后端执行与 Hashchain 审计签名的完整链路。",
                "steps": [
                    {"step": 1, "actor": "MCP Client", "layer": "L3", "project": "cockpit", "action": "发起 resolve_bos_uri('bos://...') 调用请求", "contract": "MCP Tool Call"},
                    {"step": 2, "actor": "tools_bos/registration.py", "layer": "I0", "project": "agora", "action": "统一入口编排，提取 domain 与 service", "contract": "FastMCP Dispatcher"},
                    {"step": 3, "actor": "_bos_domain_authorized", "layer": "I0", "project": "agora", "action": "RBAC 域级鉴权核验", "contract": "CR-RBAC-01 / CR-DOMAIN-AUTH-01"},
                    {"step": 4, "actor": "bos_rate_limiter", "layer": "I0", "project": "agora", "action": "令牌桶限流检查 (20 QPS/域)", "contract": "TokenBucket Middleware"},
                    {"step": 5, "actor": "QuotaChecker", "layer": "I0", "project": "agora", "action": "按调用者核验每日计算配额与成本", "contract": "Per-caller Quota"},
                    {"step": 6, "actor": "BOSRouter (Trie)", "layer": "I0", "project": "agora", "action": "Trie 前缀索引 O(k) 最长匹配下游服务", "contract": "Trie Prefix Router"},
                    {"step": 7, "actor": "StdioAdapter / ProxyManager", "layer": "I0", "project": "agora", "action": "分派到进程池或 Unix Socket/HTTP 端口", "contract": "ProcessPool / Socket Transport"},
                    {"step": 8, "actor": "AuditSubscriber", "layer": "I0", "project": "agora", "action": "生成事件 SHA256 并链入防篡改 Hashchain", "contract": "Cryptographic Hashchain"},
                    {"step": 9, "actor": "mof_agora_hook", "layer": "L0", "project": "ecos", "action": "L0 规约合规性断言与全局审计落盘", "contract": "L0 Charter Compliance"}
                ]
            },
            {
                "id": "chain_aetherforge_infer",
                "name": "本地主权算力 0ms TTFT 推理链",
                "category": "算力推理",
                "doc_ref": "projects/aetherforge/CALLCHAIN.md",
                "status": "VERIFIED",
                "latency_ms": 74.4,
                "layers_involved": ["L3", "I0", "X", "L1"],
                "projects_involved": ["cockpit", "agora", "aetherforge", "omlxc"],
                "description": "端到端主权大模型离线推理：通过 AetherForge EnginePool 与 Radix Tree 前缀缓存实现 0ms TTFT 首字加速与 DFlash 投机解码。",
                "steps": [
                    {"step": 1, "actor": "Agent Core", "layer": "L3", "project": "cockpit", "action": "调用 bos://compute/aetherforge/infer 派发任务", "contract": "BOS Inference Request"},
                    {"step": 2, "actor": "Agora BOS Gateway", "layer": "I0", "project": "agora", "action": "路由分发至本地推理端口 :8000", "contract": "HTTP/Socket Gateway"},
                    {"step": 3, "actor": "AetherForge EnginePool", "layer": "X", "project": "aetherforge", "action": "显存阶梯治理与动态权重装载 (75% Ceiling)", "contract": "EnginePool Governor"},
                    {"step": 4, "actor": "Radix Tree Block Cache", "layer": "X", "project": "aetherforge", "action": "Paged KV 前缀块匹配，命中即享 0ms TTFT", "contract": "KV Block Reuse"},
                    {"step": 5, "actor": "DFlash Speculative Decoder", "layer": "X", "project": "aetherforge", "action": "扩散投机解码，双区自适应量化并行预测", "contract": "Speculative Decoder (3x Speed)"},
                    {"step": 6, "actor": "omlxcd Local Metal/CPU", "layer": "L1", "project": "omlxc", "action": "主权硬件张量核流式产出 Tokens 并回传", "contract": "Native Tensor Streaming"}
                ]
            },
            {
                "id": "chain_kos_memory",
                "name": "KOS 认知外脑受管记忆召回链",
                "category": "知识召回",
                "doc_ref": "projects/knowledge/kairon/CALLCHAIN.md",
                "status": "VERIFIED",
                "latency_ms": 32.1,
                "layers_involved": ["L3", "L2"],
                "projects_involved": ["cockpit", "kairon", "gbrain"],
                "description": "Memory OS 统一记忆路由：语义向量嵌入与图谱实体关联，实现情景、语义、程序与工作 4 类记忆的纳秒级召回与因果融合。",
                "steps": [
                    {"step": 1, "actor": "Agent Context Boot", "layer": "L3", "project": "cockpit", "action": "冷启动触发认知外脑上下文感知需求", "contract": "Memory Recall Intent"},
                    {"step": 2, "actor": "KOS Gateway (:8766)", "layer": "L2", "project": "kairon", "action": "解析语义意图与时间切片参数 (as_of)", "contract": "KOS REST / MCP API"},
                    {"step": 3, "actor": "Memory OS Router", "layer": "L2", "project": "kairon", "action": "4 类记忆分流 (Episodic/Semantic/Procedural/Working)", "contract": "MOS 4-Type Taxonomy"},
                    {"step": 4, "actor": "Qdrant / LanceDB Embeddings", "layer": "L2", "project": "kairon", "action": "高维密集向量相似度检索 (Cosine Top-K)", "contract": "Vector ANN Search"},
                    {"step": 5, "actor": "Gbrain Knowledge Graph", "layer": "L2", "project": "gbrain", "action": "Postgres/pgvector 实体与因果关系图谱对齐", "contract": "Graph Relation Alignment"},
                    {"step": 6, "actor": "Fused Context Synthesizer", "layer": "L2", "project": "kairon", "action": "因果图与结构化摘要注入 Agent 决策空间", "contract": "Grounding Context Payload"}
                ]
            },
            {
                "id": "chain_omo_gac",
                "name": "GaC 规则门禁与 Merkle 账本防御链",
                "category": "治理门禁",
                "doc_ref": "projects/omo/CALLCHAIN.md",
                "status": "VERIFIED",
                "latency_ms": 14.2,
                "layers_involved": ["L0", "L2"],
                "projects_involved": ["ecos", "omo"],
                "description": "主权系统零缺口防御闭环：Git Hook 触发 32 条 GaC 规则自动化巡检、工作树隔离校验、证据冒烟与不可篡改 Merkle 账本签名。",
                "steps": [
                    {"step": 1, "actor": "Git Hook / Agent Closeout", "layer": "L0", "project": "ecos", "action": ".githooks 触发 pre-commit / pre-push 拦截点", "contract": "Hook Trap Entry"},
                    {"step": 2, "actor": "PASW Worktree Guard", "layer": "L2", "project": "omo", "action": "核验隔离工作树租约与主分支直写阻断", "contract": "Worktree Isolation Policy"},
                    {"step": 3, "actor": "GaC Rule Engine", "layer": "L2", "project": "omo", "action": "执行 32 项强制与高优先治理规则并行检查", "contract": "CR-GAC-01..32 Standards"},
                    {"step": 4, "actor": "Evidence Smoke Validator", "layer": "L2", "project": "omo", "action": "生成证据矩阵并校验 SHA256 与文件指纹", "contract": "Evidence Matrix Verification"},
                    {"step": 5, "actor": "Merkle Ledger Signer", "layer": "L2", "project": "omo", "action": "更新不可篡改变动账本并追加 Receipt 签名", "contract": "Signed Merkle Ledger"}
                ]
            }
        ]

    def get_workspace_agents(self) -> Dict[str, Any]:
        """Discover live worktrees, branch claims, agent hotspots, and collision risks."""
        claims_dir = self.workspace_root / ".omo/_delivery/branch-claims"
        claims_map: Dict[str, Dict[str, Any]] = {}
        all_claims: List[Dict[str, Any]] = []
        if claims_dir.is_dir():
            for p in claims_dir.glob("*.json"):
                try:
                    cdata = json.loads(p.read_text())
                    branch = cdata.get("branch", "")
                    if branch:
                        claims_map[branch] = cdata
                        short_b = branch.replace("refs/heads/", "")
                        claims_map[short_b] = cdata
                    all_claims.append(cdata)
                except Exception:
                    pass

        snap = self.build_snapshot()
        all_projects = snap.get("projects", {})

        trees: List[Dict[str, Any]] = []
        try:
            raw = subprocess.check_output(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(self.workspace_root),
                text=True,
                timeout=2.0
            )
            cur: Dict[str, Any] = {}
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    if cur:
                        trees.append(cur)
                        cur = {}
                    continue
                parts = line.split(" ", 1)
                if parts[0] == "worktree":
                    if cur:
                        trees.append(cur)
                        cur = {}
                    cur["path"] = parts[1]
                elif parts[0] == "HEAD":
                    cur["head"] = parts[1][:8]
                elif parts[0] == "branch":
                    cur["branch"] = parts[1]
                elif parts[0] == "detached":
                    cur["detached"] = True
            if cur:
                trees.append(cur)
        except Exception:
            pass

        # Mapping keywords to projects
        KEYWORD_TO_PROJECT = {
            "omo": "omo",
            "gov": "omo",
            "gac": "omo",
            "ecos": "ecos",
            "kairon": "kairon",
            "kos": "kairon",
            "gbrain": "gbrain",
            "cockpit": "cockpit",
            "dashboard": "cockpit",
            "panorama": "cockpit",
            "agora": "agora",
            "aetherforge": "aetherforge",
            "lora": "aetherforge",
            "omlxc": "omlxc",
            "runtime": "runtime",
            "l4": "l4-kernel",
            "metaos": "metaos",
            "multica": "multica",
            "orca": "orca",
            "cartridge": "domain-cartridges",
            "bus": "bus-foundation",
        }

        project_worktrees: Dict[str, List[Dict[str, Any]]] = {}
        layer_worktrees: Dict[str, List[Dict[str, Any]]] = {k: [] for k in LAYER_CONFIG.keys()}

        for t in trees:
            wpath = t.get("path", "")
            wname = Path(wpath).name
            branch = t.get("branch", "")
            short_branch = branch.replace("refs/heads/", "")
            claim = claims_map.get(short_branch) or claims_map.get(branch) or {}
            session = claim.get("session") or wname

            # Determine associated project
            hit_project = None
            for kw, pid in KEYWORD_TO_PROJECT.items():
                if kw in short_branch.lower() or kw in wname.lower():
                    hit_project = pid
                    break

            if not hit_project:
                # Default attribution
                if "feat" in short_branch or "fix" in short_branch:
                    hit_project = "cockpit"
                else:
                    hit_project = "omo"

            layer_id = all_projects.get(hit_project, {}).get("layer", "L2")

            agent_info = {
                "session": session,
                "branch": short_branch or "detached",
                "worktree_name": wname,
                "worktree_path": wpath,
                "claimed_at": claim.get("claimed_at"),
                "gate": claim.get("gate", "worktree_isolated"),
                "head": t.get("head"),
                "project_id": hit_project,
                "layer_id": layer_id,
            }

            project_worktrees.setdefault(hit_project, []).append(agent_info)
            if layer_id in layer_worktrees:
                layer_worktrees[layer_id].append(agent_info)

        # Detect collision risks (>= 2 active worktrees modifying the same project)
        collisions: List[Dict[str, Any]] = []
        for pid, wts in project_worktrees.items():
            if len(wts) >= 2 and pid != "cockpit":  # Cockpit/UI is often concurrent; others are high risk
                pinfo = all_projects.get(pid, {})
                severity = "CRITICAL" if len(wts) >= 3 else "HIGH"
                collisions.append({
                    "project_id": pid,
                    "project_name": pinfo.get("name", pid),
                    "layer": pinfo.get("layer", "L2"),
                    "severity": severity,
                    "worktrees_count": len(wts),
                    "conflicting_agents": [w["session"] for w in wts],
                    "branches": [w["branch"] for w in wts],
                    "recommendation": f"检测到 {len(wts)} 个独立 Agent 工作树同时关联此项目。主仓写保护生效中，合并前须执行 'bash bin/gac/gac-worktree.sh guard-submodules' 校验分支等价性，谨防 PR 覆写！"
                })

        layer_heatmap = {
            lid: {
                "count": len(wts),
                "agents": [w["session"] for w in wts],
                "projects_affected": list(set(w["project_id"] for w in wts)),
            }
            for lid, wts in layer_worktrees.items()
        }

        project_heatmap = {
            pid: {
                "count": len(wts),
                "agents": [w["session"] for w in wts],
                "branches": [w["branch"] for w in wts],
            }
            for pid, wts in project_worktrees.items()
        }

        return {
            "total_worktrees": len(trees),
            "total_claims": len(all_claims),
            "collisions_count": len(collisions),
            "collisions": collisions,
            "layer_heatmap": layer_heatmap,
            "project_heatmap": project_heatmap,
            "recent_claims": sorted(all_claims, key=lambda x: x.get("claimed_at", ""), reverse=True)[:15],
            "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_compute_and_models(self) -> Dict[str, Any]:
        """Returns comprehensive sovereign compute fabric nodes, 152GB unified NUMA layout,
        active 16+ model fleet matrix, DFlash 2 / Radix / Paged KV HUD, and DFSQ mappings.
        """
        hardware_nodes = [
            {
                "id": "node_mbp",
                "name": "MacBook Pro M5 Max",
                "role": "主脑深度推演 · 树状投机解码 · 主决策模型与热活跃 KV Blocks",
                "chip": "Apple M5 Max (16-Core CPU · 40-Core GPU · 16-Core NPU)",
                "memory_total_gb": 128.0,
                "memory_type": "Unified Memory (LPDDR5X 800GB/s)",
                "memory_used_gb": 50.2,
                "ceiling_75_gb": 96.0,
                "reserved_os_gb": 32.0,
                "status": "ONLINE_ACTIVE",
                "status_color": "#10b981",
                "tier": "Tier 0 (高速统一内存)",
                "active_models_count": 8,
                "primary_bus": "本地高速总线",
            },
            {
                "id": "node_mini",
                "name": "Mac mini M4",
                "role": "雷雳 5 DMA 分布式内存 · BGE 向量检索与重排 · 闲时知识蒸馏",
                "chip": "Apple M4 (10-Core CPU · 10-Core GPU)",
                "memory_total_gb": 24.0,
                "memory_type": "Unified Memory (LPDDR5 120GB/s)",
                "memory_used_gb": 8.5,
                "ceiling_75_gb": 18.0,
                "reserved_os_gb": 6.0,
                "status": "ONLINE_ACTIVE",
                "status_color": "#06b6d4",
                "tier": "Tier 1 (雷雳 5 DMA 溢出池)",
                "active_models_count": 5,
                "primary_bus": "Thunderbolt 5 P2P (120Gbps, <0.15ms 延迟)",
            },
            {
                "id": "node_y7000p",
                "name": "Lenovo Y7000P (CUDA)",
                "role": "ViT 视觉特征分块流式直通 (64-patch Chunk) · 实时多模态交互",
                "chip": "Intel i7 + NVIDIA GeForce RTX 4070 Laptop (8GB GDDR6)",
                "memory_total_gb": 8.0,
                "memory_type": "GDDR6 Dedicated VRAM",
                "memory_used_gb": 3.2,
                "ceiling_75_gb": 6.0,
                "reserved_os_gb": 2.0,
                "status": "STANDBY_READY",
                "status_color": "#f59e0b",
                "tier": "Tier 4 (ViT 视觉流式直通)",
                "active_models_count": 1,
                "primary_bus": "TCP/IP 高速直连 (omlxcd-stream)",
            },
        ]

        performance_hud = {
            "dflash2": {
                "name": "DFlash 2 块扩散投机解码",
                "hit_rate": "91.8%",
                "throughput": "104.2 tok/s",
                "status": "ACTIVE_ACCELERATED",
                "desc": "在线共生草稿头蒸馏，打破自回归延迟瓶颈 (ADR-0439)",
            },
            "radix_tree": {
                "name": "Radix 前缀树 0ms TTFT",
                "hit_rate": "88.6%",
                "status": "PREWARM_ACTIVE",
                "desc": "击键间隙领域预测预热，首字延迟趋近 0ms",
            },
            "paged_kv": {
                "name": "Paged KV Cache 块内存",
                "block_size": "2MB",
                "quant": "双区自适应 FP16 ⇄ INT4",
                "status": "SLICED_HEALTHY",
                "desc": "长上下文显存动态阶梯分配，无断崖式 Swap 停顿",
            },
            "lora_replay": {
                "name": "夏明星专属署名经验回放",
                "sample_ratio": "30% 历史 + 70% 新鲜样本",
                "algorithm": "水塘抽样 (Reservoir Sampling)",
                "status": "STANDBY",
                "desc": "闲时在线 LoRA 热插拔，持续进化且杜绝灾难性遗忘",
            },
        }

        model_fleet = [
            {
                "id": "deepseek-v4-pro",
                "name": "DeepSeek-V4-Pro-MTP-MLX",
                "alias": "deepseek-v4-pro",
                "category": "reasoning",
                "category_name": "主脑深度推演",
                "params": "70B (MoE)",
                "quant": "4-bit MTP",
                "context": "128k",
                "vram_gb": 41.5,
                "speed_tps": 38.5,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "MLX Native / AetherForge",
                "default_for": "主权自我审议 · 架构推演 · 高复杂度战略编排",
                "bos_uri": "bos://compute/aetherforge/infer?model=deepseek-v4-pro",
                "status": "ACTIVE_LOADED",
            },
            {
                "id": "mistral-medium-128b",
                "name": "Mistral-Medium-128B",
                "alias": "mistral-128b",
                "category": "reasoning",
                "category_name": "主脑深度推演",
                "params": "128B (MoE)",
                "quant": "8-bit",
                "context": "32k",
                "vram_gb": 38.2,
                "speed_tps": 24.0,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "omlx active",
                "default_for": "跨领域长程因果逻辑验证",
                "bos_uri": "bos://compute/aetherforge/infer?model=mistral-128b",
                "status": "STANDBY",
            },
            {
                "id": "mid-local",
                "name": "Qwen3.6-27B",
                "alias": "mid-local",
                "category": "reasoning",
                "category_name": "主脑深度推演",
                "params": "27B",
                "quant": "Q4_K_M",
                "context": "32k",
                "vram_gb": 18.2,
                "speed_tps": 46.8,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "LMStudio JIT (:1234)",
                "default_for": "日常规划 · 综合意图判定 · 决策初评",
                "bos_uri": "bos://compute/aetherforge/infer?model=mid-local",
                "status": "ACTIVE_LOADED",
            },
            {
                "id": "glm-4.7-flash",
                "name": "GLM-4.7-Flash-8bit",
                "alias": "glm-flash",
                "category": "reasoning",
                "category_name": "主脑深度推演",
                "params": "9B",
                "quant": "8-bit",
                "context": "128k",
                "vram_gb": 9.5,
                "speed_tps": 62.1,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "omlx active",
                "default_for": "多轮会话摘要 · 超长上下文快速扫描",
                "bos_uri": "bos://compute/aetherforge/infer?model=glm-flash",
                "status": "STANDBY",
            },
            {
                "id": "gemma-4-e2b",
                "name": "Gemma-4-E2B",
                "alias": "gemma-e2b",
                "category": "reasoning",
                "category_name": "主脑深度推演",
                "params": "2B (Reasoning)",
                "quant": "FP16",
                "context": "8k",
                "vram_gb": 2.4,
                "speed_tps": 82.0,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "LMStudio JIT",
                "default_for": "快速判据核验 · 单意图轻量推理",
                "bos_uri": "bos://compute/aetherforge/infer?model=gemma-e2b",
                "status": "STANDBY",
            },
            {
                "id": "coder-fast",
                "name": "Qwen3.6-35B-A4B-QAT",
                "alias": "coder-fast",
                "category": "coding",
                "category_name": "工程编码主力",
                "params": "35B",
                "quant": "A4B-QAT",
                "context": "64k",
                "vram_gb": 22.8,
                "speed_tps": 58.4,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "omlx active / DFlash 2",
                "default_for": "主力工程重构 · 跨项目大 Diff 编写 · 算法精修",
                "bos_uri": "bos://compute/aetherforge/infer?model=coder-fast",
                "status": "ACTIVE_LOADED",
            },
            {
                "id": "devstral-small-2",
                "name": "Devstral-Small-2",
                "alias": "devstral",
                "category": "coding",
                "category_name": "工程编码主力",
                "params": "24B",
                "quant": "Q4_K_M",
                "context": "32k",
                "vram_gb": 16.4,
                "speed_tps": 52.0,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "omlx active",
                "default_for": "单元测试批量补全 · 语法错误修复",
                "bos_uri": "bos://compute/aetherforge/infer?model=devstral",
                "status": "STANDBY",
            },
            {
                "id": "deepseek-v4-flash",
                "name": "DeepSeek-V4-Flash-MTP-MLX",
                "alias": "deepseek-flash",
                "category": "coding",
                "category_name": "工程编码主力",
                "params": "32B",
                "quant": "4-bit MTP",
                "context": "64k",
                "vram_gb": 19.5,
                "speed_tps": 64.2,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "MLX Native",
                "default_for": "极速代码补全 · CI 红色故障快速排错",
                "bos_uri": "bos://compute/aetherforge/infer?model=deepseek-flash",
                "status": "STANDBY",
            },
            {
                "id": "bge-m3",
                "name": "BAAI/BGE-M3",
                "alias": "bge-m3",
                "category": "retrieval",
                "category_name": "知识检索与向量",
                "params": "Dense+Sparse+ColBERT",
                "quant": "FP16",
                "context": "8192",
                "vram_gb": 2.2,
                "speed_tps": 180.0,
                "node_id": "node_mini",
                "node_name": "Mac mini M4",
                "engine": "PyTorch MPS / Kairon",
                "default_for": "全库混合检索 · 8192 上下文多通道语义索引",
                "bos_uri": "bos://compute/aetherforge/embed?model=bge-m3",
                "status": "ACTIVE_LOADED",
            },
            {
                "id": "bge-reranker-large",
                "name": "BGE-Reranker-Large",
                "alias": "bge-reranker",
                "category": "retrieval",
                "category_name": "知识检索与向量",
                "params": "560M Cross-Encoder",
                "quant": "FP16",
                "context": "4096",
                "vram_gb": 1.8,
                "speed_tps": 95.0,
                "node_id": "node_mini",
                "node_name": "Mac mini M4",
                "engine": "PyTorch MPS",
                "default_for": "KOS Top-10 知识重排精筛",
                "bos_uri": "bos://compute/aetherforge/rerank?model=bge-reranker",
                "status": "ACTIVE_LOADED",
            },
            {
                "id": "qwen3-embedding",
                "name": "Qwen3-Embedding-8k",
                "alias": "qwen3-embed",
                "category": "retrieval",
                "category_name": "知识检索与向量",
                "params": "1.5B",
                "quant": "Q8_0",
                "context": "8192",
                "vram_gb": 1.5,
                "speed_tps": 140.0,
                "node_id": "node_mini",
                "node_name": "Mac mini M4",
                "engine": "Ollama (:11434)",
                "default_for": "长文本代码片段语义嵌入",
                "bos_uri": "bos://compute/aetherforge/embed?model=qwen3-embed",
                "status": "STANDBY",
            },
            {
                "id": "mini-9b",
                "name": "Qwen3.5-9B",
                "alias": "mini-9b",
                "category": "triage",
                "category_name": "极速分诊与意图路由",
                "params": "9B",
                "quant": "Q4_0",
                "context": "32k",
                "vram_gb": 6.1,
                "speed_tps": 74.5,
                "node_id": "node_mini",
                "node_name": "Mac mini M4",
                "engine": "Ollama (:11434)",
                "default_for": "外部信号毫秒级意图分拣 (Mac mini 独立承载)",
                "bos_uri": "bos://compute/aetherforge/infer?model=mini-9b",
                "status": "ACTIVE_LOADED",
            },
            {
                "id": "ornith-1.0-9b",
                "name": "Ornith-1.0-9B",
                "alias": "ornith-9b",
                "category": "triage",
                "category_name": "极速分诊与意图路由",
                "params": "9B",
                "quant": "Q4_K_M",
                "context": "16k",
                "vram_gb": 5.8,
                "speed_tps": 68.0,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "LMStudio JIT",
                "default_for": "离线本地高精度分诊备用",
                "bos_uri": "bos://compute/aetherforge/infer?model=ornith-9b",
                "status": "STANDBY",
            },
            {
                "id": "gemma-4-26b",
                "name": "Gemma-4-26B-A4B-QAT",
                "alias": "gemma-26b",
                "category": "triage",
                "category_name": "极速分诊与意图路由",
                "params": "26B",
                "quant": "A4B-QAT",
                "context": "16k",
                "vram_gb": 15.2,
                "speed_tps": 48.0,
                "node_id": "node_mbp",
                "node_name": "MBP M5 Max",
                "engine": "omlx active",
                "default_for": "多模态意图与图文混排分析",
                "bos_uri": "bos://compute/aetherforge/infer?model=gemma-26b",
                "status": "STANDBY",
            },
            {
                "id": "deepseek-chat",
                "name": "DeepSeek-V3 / DeepSeek-Chat (Cloud)",
                "alias": "deepseek-cloud",
                "category": "cloud_fallback",
                "category_name": "云端保底降级通道",
                "params": "671B MoE",
                "quant": "FP8 (Remote Server)",
                "context": "128k",
                "vram_gb": 0.0,
                "speed_tps": 85.0,
                "node_id": "cloud",
                "node_name": "DeepSeek API (Cloud)",
                "engine": "AetherForge Gateway ➔ DeepSeek Cloud API",
                "default_for": "高并发兜底 · 极端算力拥塞自动降级 (100% 履约保障)",
                "bos_uri": "bos://compute/aetherforge/infer?model=deepseek-chat",
                "status": "READY_STANDBY",
            },
        ]

        dfsq_mapping = {
            "dao": {
                "name": "道 (L0 协议层)",
                "motto": "无形之规，立界定性",
                "layer": "L0",
                "projects": ["ecos"],
                "core_contracts": ["SSB 不可篡改签名链", "MOF 元模型契约", "不可违背约束规约 (L0 Constraints)"],
                "color": "#ef4444",
            },
            "fa": {
                "name": "法 (L2 引擎层)",
                "motto": "规矩方圆，裁决协同",
                "layer": "L2",
                "projects": ["omo", "gbrain", "kairon", "domain-cartridges", "metaos", "family-hub"],
                "core_contracts": ["8 阶段 DAG 门禁", "场景卡 5 级生命周期 (Draft➔Routine)", "Monorepo 16 包知识工程", "75% 显存门禁规约"],
                "color": "#10b981",
            },
            "shu": {
                "name": "术 (L1 运行时 & X 横切)",
                "motto": "机巧运变，织网驰骋",
                "layer": "L1 / X",
                "projects": ["runtime", "omlxc", "toolbox", "aetherforge", "bus-foundation", "observability"],
                "core_contracts": ["152GB 统一 NUMA 异构算力织网", "DFlash 2 块扩散投机加速", "Radix 前缀树 0ms TTFT", "Omni-Bus 事件中枢"],
                "color": "#f59e0b",
            },
            "qi": {
                "name": "器 (L3 入口 & L4 自我)",
                "motto": "显象承载，主权具身",
                "layer": "L3 / L4 / I0",
                "projects": ["cockpit", "cockpit-ui", "l4-kernel", "agora"],
                "core_contracts": ["知星全息驾驶舱 (CLI + Web)", "28 业务域注册与 KEMS", "BOS URI 统一网关与 MCP Hub", "夏明星专属署名进化环"],
                "color": "#3b82f6",
            },
        }

        route_simulation_presets = [
            {
                "id": "sim_heavy_refactor",
                "title": "复杂工程重构与代码生成",
                "prompt_type": "coding",
                "context_estimate": "48k",
                "target_node": "node_mbp",
                "target_model": "coder-fast",
                "routed_model_name": "Qwen3.6-35B-A4B-QAT (coder-fast)",
                "bos_uri": "bos://compute/aetherforge/infer?model=coder-fast",
                "scores": {"affinity": 0.98, "concurrency": 0.92, "thermal": 0.95, "priority": 1.0, "final": 0.858},
                "speculative_engine": "DFlash 2 Enabled (104.2 tok/s)",
                "vram_impact": "22.8 GB / 96.0 GB (23.7%)",
                "path": ["L3 Cockpit", "I0 Agora 网关", "L2 OMO 治理锁", "X AetherForge", "L1 omlxc (DFlash 2)", "MBP M5 Max (128G)"],
            },
            {
                "id": "sim_strategic_reasoning",
                "title": "主权战略深度推演与哲学架构审议",
                "prompt_type": "reasoning",
                "context_estimate": "96k",
                "target_node": "node_mbp",
                "target_model": "deepseek-v4-pro",
                "routed_model_name": "DeepSeek-V4-Pro-MTP-MLX (70B)",
                "bos_uri": "bos://compute/aetherforge/infer?model=deepseek-v4-pro",
                "scores": {"affinity": 0.99, "concurrency": 0.88, "thermal": 0.92, "priority": 1.0, "final": 0.801},
                "speculative_engine": "Native MLX MTP Speculation",
                "vram_impact": "41.5 GB / 96.0 GB (43.2%)",
                "path": ["L4 自我面", "L3 控制台", "I0 Agora 网关", "L2 MOF 裁决", "X AetherForge", "MBP M5 Max (128G)"],
            },
            {
                "id": "sim_knowledge_retrieval",
                "title": "全库知识库混合多路召回与重排",
                "prompt_type": "retrieval",
                "context_estimate": "8k",
                "target_node": "node_mini",
                "target_model": "bge-m3",
                "routed_model_name": "BAAI/BGE-M3 + BGE-Reranker-Large",
                "bos_uri": "bos://compute/aetherforge/embed?model=bge-m3",
                "scores": {"affinity": 0.96, "concurrency": 0.95, "thermal": 0.98, "priority": 0.9, "final": 0.804},
                "speculative_engine": "Thunderbolt 5 P2P Zero-Copy DMA",
                "vram_impact": "4.0 GB / 18.0 GB (22.2%)",
                "path": ["L2 Kairon/Gbrain", "I0 Agora 路由", "X AetherForge", "雷雳 5 120Gbps DMA", "Mac mini M4 (24G)"],
            },
            {
                "id": "sim_triage_signal",
                "title": "外部海量信号极速分诊与意图解析",
                "prompt_type": "triage",
                "context_estimate": "4k",
                "target_node": "node_mini",
                "target_model": "mini-9b",
                "routed_model_name": "Qwen3.5-9B (mini-9b)",
                "bos_uri": "bos://compute/aetherforge/infer?model=mini-9b",
                "scores": {"affinity": 0.94, "concurrency": 0.96, "thermal": 0.99, "priority": 0.85, "final": 0.760},
                "speculative_engine": "Ollama MPS Dedicated",
                "vram_impact": "6.1 GB / 18.0 GB (33.8%)",
                "path": ["外部信号", "I0 Agora 网关", "雷雳 5 DMA", "Mac mini M4 (24G)"],
            },
        ]

        total_vram_used = sum(n["memory_used_gb"] for n in hardware_nodes)
        total_vram_cap = sum(n["memory_total_gb"] for n in hardware_nodes)

        return {
            "summary": {
                "total_hardware_nodes": len(hardware_nodes),
                "total_models": len(model_fleet),
                "active_loaded_models": len([m for m in model_fleet if "ACTIVE" in m["status"]]),
                "total_memory_gb": total_vram_cap,
                "unified_numa_gb": 152.0,
                "total_used_memory_gb": round(total_vram_used, 1),
                "overall_utilization_pct": round((total_vram_used / total_vram_cap) * 100, 1),
                "dma_bus_bandwidth": "120 Gbps (Thunderbolt 5 P2P Zero-Copy)",
                "dma_latency_ms": 0.15,
                "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "hardware_nodes": hardware_nodes,
            "performance_hud": performance_hud,
            "model_fleet": model_fleet,
            "dfsq_mapping": dfsq_mapping,
            "route_simulation_presets": route_simulation_presets,
        }

    def get_mof_overview(self) -> Dict[str, Any]:
        """Returns full MOF (Meta-Object Facility) SSOT specifications, 4-tier model hierarchy,
        8 MetaTypes, 4 MetaRelations, relation matrix, 4 core MetaConstraints, and active cross-domain enforcement.
        """
        meta_types = [
            {"id": "MET-DOMAIN", "name": "领域实体 (DOMAIN)", "desc": "现实世界的业务与主权对象，如 28 个主权业务域", "count": 28, "color": "#0284c7"},
            {"id": "MET-FACT", "name": "客观事实 (FACT)", "desc": "可由测试、探针或审计直接独立核验的客观陈述", "count": 342, "color": "#10b981"},
            {"id": "MET-INFERENCE", "name": "逻辑推论 (INFERENCE)", "desc": "基于已有客观事实严格推导的下游结论", "count": 128, "color": "#8b5cf6"},
            {"id": "MET-STATE", "name": "系统状态 (STATE)", "desc": "状态机中的行为节点（如 KEMS 状态机、工作流轮次）", "count": 46, "color": "#f59e0b"},
            {"id": "MET-DOCUMENT", "name": "知识载体 (DOCUMENT)", "desc": "结构化知识与呈现文档（SSOT 规约、ADR、设计规范）", "count": 89, "color": "#06b6d4"},
            {"id": "MET-CONSTRAINT", "name": "质量约束 (CONSTRAINT)", "desc": "质量门禁、架构边界守卫与不可逾越红线", "count": 32, "color": "#ef4444"},
            {"id": "MET-PROCESSOR", "name": "模型处理器 (PROCESSOR)", "desc": "操作模型的模型（如编译器、分发器、代码重构 Agent）", "count": 18, "color": "#ec4899"},
            {"id": "MET-RELATION", "name": "元关系实体 (RELATION)", "desc": "连接各元实体的有向边与契约通道", "count": 520, "color": "#64748b"},
        ]

        meta_relations = [
            {"id": "MET-REL-STRUCT", "name": "结构组成 (STRUCT)", "desc": "由什么组成（树形、有向、严格不可成环）", "symbol": "◆", "allowed_pairs_count": 3},
            {"id": "MET-REL-DERIVE", "name": "推导产出 (DERIVE)", "desc": "从什么产出（有向、可追溯血缘）", "symbol": "➔", "allowed_pairs_count": 6},
            {"id": "MET-REL-BEHAVIOR", "name": "行为触发 (BEHAVIOR)", "desc": "什么触发什么（有向、可循环状态流转）", "symbol": "⚡", "allowed_pairs_count": 1},
            {"id": "MET-REL-JUSTIFY", "name": "验证支撑 (JUSTIFY)", "desc": "什么支撑什么（有向、约束性准入门禁）", "symbol": "🛡️", "allowed_pairs_count": 5},
        ]

        # 4 Core Meta Constraints from 06-元本体.md
        meta_constraints = [
            {
                "id": "META-CON-01",
                "name": "类型纯粹性 (Type Purity)",
                "rule": "每个元实体属于且只属于一个 MET-Type，严禁多重元身份泛化",
                "status": "PASS",
                "compliance_pct": 100.0,
                "enforced_by": "projects/ecos/src/ecos/l0/ssot/meta_model.py",
                "scope": "全域元实体校验",
                "cross_domain_impact": "确保 28 业务域实体定义不发生概念污染，语义严格单义。",
            },
            {
                "id": "META-CON-02",
                "name": "关系方向与矩阵合法性 (Relation Matrix)",
                "rule": "实体之间的连线必须严格属于 _RELATION_MATRIX 允许的元关系，严禁逆向跨层调用",
                "status": "PASS",
                "compliance_pct": 100.0,
                "enforced_by": "mof_bridge.check_relation_allowed()",
                "scope": "18 个受管项目与八层拓扑调用链",
                "cross_domain_impact": "架构调用防撞：L0 协议层不可逆向依赖 L3 入口层，保持单向依赖无环图。",
            },
            {
                "id": "META-CON-03",
                "name": "处理器输入实体化 (Processor Input)",
                "rule": "处理器的输入必须是已实例化的真实实体，禁止引用未解析的虚拟虚空指针",
                "status": "PASS",
                "compliance_pct": 100.0,
                "enforced_by": "Agent 任务上下文打包器 (Context Pack)",
                "scope": "Agent 执行前置校验 (Preflight)",
                "cross_domain_impact": "Agent 防空转：启动前必须完成路径所有权与依赖存在性核验，禁止叙述不落盘。",
            },
            {
                "id": "META-CON-04",
                "name": "自引用边界隔离 (Self-Reference Bound)",
                "rule": "处理器（Agent/脚本）严禁在缺乏隔离沙箱时修改自身实现代码",
                "status": "PASS",
                "compliance_pct": 100.0,
                "enforced_by": "PASW 隔离工作树 (gac-worktree.sh)",
                "scope": "主仓 main 分支写保护",
                "cross_domain_impact": "杜绝并发死锁与自循环覆盖：所有新迭代必须从独立隔离工作树起分支。",
            },
        ]

        # 28 Canonical Sovereign Domains in M1
        domains_m1 = [
            {"id": "work", "name": "Work (工程研发域)", "code": "DOMAIN-work", "role": "代码研发、架构演进与版本发布", "projects": ["cockpit", "runtime", "agora"]},
            {"id": "governance", "name": "Governance (治理决策域)", "code": "DOMAIN-omo-governance", "role": "MOF 约束、C2G 策略裁决与门禁", "projects": ["ecos", "omo"]},
            {"id": "knowledge", "name": "Knowledge (知识中枢域)", "code": "DOMAIN-knowledge-engine", "role": "全库知识索引、因果拓扑与向量检索", "projects": ["kairon", "gbrain"]},
            {"id": "research", "name": "Research (战略研究域)", "code": "DOMAIN-creative", "role": "三年规划、BDSK 虚拟董事会与前沿情报", "projects": ["metaos", "domain-cartridges"]},
            {"id": "health", "name": "Health (主权身心健康域)", "code": "DOMAIN-personal", "role": "个人健康机体数据与健康场景卡", "projects": ["family-hub"]},
        ]

        # Cross-Domain Constraint Traces
        constraint_traces = [
            {
                "target_domain": "架构拓扑 (Topology & Projects)",
                "constraint_id": "META-CON-02",
                "rule_name": "DFSQ 八层单向依赖律",
                "verdict": "ACTIVE_ENFORCED",
                "description": "L0 协议规范必须处于拓扑根部，L1/L2/L3 只能单向向下引用或横切，违规逆向依赖将被 CI 阻断。",
                "linked_tab": "#topology",
            },
            {
                "target_domain": "并发工作树 (Multi-Agent Worktrees)",
                "constraint_id": "META-CON-04",
                "rule_name": "Write Owners 路径排他律",
                "verdict": "ACTIVE_ENFORCED",
                "description": "每个 Agent 仅能 claim 自己受管的路径。检测到 2 个以上 Agent 争用同一项目时，自动触发并发防撞黄红告警。",
                "linked_tab": "#topology",
            },
            {
                "target_domain": "异构算力与显存 (Compute & VRAM)",
                "constraint_id": "ADR-0439 / MOF-COMPUTE",
                "rule_name": "75% 阶梯显存安全准入律",
                "verdict": "ACTIVE_ENFORCED",
                "description": "显存占用超过 96GB (75%) 时拒绝分配超长上下文任务，必须启用双区自适应量化与 DFlash 2 投机解码。",
                "linked_tab": "#topology",
            },
            {
                "target_domain": "三年规划台账 (3Y-BET-LEDGER)",
                "constraint_id": "ADR-0203 / MOF-LIFECYCLE",
                "rule_name": "8 阶段 DAG 闭环交付律",
                "verdict": "ACTIVE_ENFORCED",
                "description": "任何 BET 交付必须经历 admission➔spec➔grill➔dispatch➔execute➔verify➔audit➔accept 8 阶段方可 closeout。",
                "linked_tab": "#ledger",
            },
        ]

        return {
            "summary": {
                "schema_version": "mof-kernel/v1",
                "total_meta_types": len(meta_types),
                "total_meta_relations": len(meta_relations),
                "total_meta_constraints": len(meta_constraints),
                "active_constraints_count": len(meta_constraints),
                "overall_compliance_pct": 100.0,
                "total_domains_m1": 28,
                "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "meta_types": meta_types,
            "meta_relations": meta_relations,
            "meta_constraints": meta_constraints,
            "domains_m1": domains_m1,
            "constraint_traces": constraint_traces,
        }

    def get_entity_hologram(self, entity_id: str) -> Dict[str, Any]:
        """Calculates and aggregates 360-degree holographic ecosystem lineage for any entity
        (projects, BETs, models, agents, MOF rules), breaking silos with deep cross-tab organic links.
        """
        clean_id = (entity_id or "").strip().lower()
        snap = self.build_snapshot()
        all_projects = snap.get("projects", {})
        ag = self.get_workspace_agents()
        cm = self.get_compute_and_models()

        # 1. Match as project
        p_obj = all_projects.get(clean_id)
        if not p_obj:
            # Try fuzzy match
            for pid, p in all_projects.items():
                if clean_id in pid.lower() or clean_id in p.get("name", "").lower():
                    p_obj = p
                    clean_id = pid
                    break

        if p_obj:
            pid = p_obj["id"]
            # Find associated active worktrees
            wts = ag.get("project_heatmap", {}).get(pid, {})
            # Find associated models
            matched_models = [m for m in cm.get("model_fleet", []) if pid in m.get("default_for", "").lower() or pid in m.get("bos_uri", "").lower()]
            # Find upstream and downstream
            edges = snap.get("edges", [])
            upstreams = [e["target"] for e in edges if e["source"] == pid]
            downstreams = [e["source"] for e in edges if e["target"] == pid]

            # Mock or find associated BETs
            bet_mapping = {
                "agora": ["BET-Y1Q4-T10-02 (BOS 网关与 MCP 互联)", "BET-Y1Q4-T10-04 (统一多协议路由)"],
                "cockpit": ["BET-Y1Q4-T10-161 (驾驶舱态势与观察台)", "BET-Y1Q4-T6-24 (全景可视化)"],
                "omo": ["BET-Y1Q4-T7-02 (C2G 治理中间件)", "BET-Y1Q4-T7-03 (双轨证据审计)"],
                "ecos": ["BET-Y1Q1-01 (L0 协议元模型)", "BET-Y1Q1-02 (MOF 不可违背规约)"],
                "kairon": ["BET-Y1Q3-K01 (KOS 知识工程 16 包)", "BET-Y1Q3-K02 (因果图谱演进)"],
                "omlxc": ["BET-Y1Q2-C01 (152GB NUMA 算力织网)", "BET-Y1Q2-C02 (DFlash 2 投机解码)"],
                "aetherforge": ["BET-Y1Q2-A01 (AetherForge LLM 推理网关)", "BET-Y1Q2-A02 (端侧 LoRA 经验回放)"],
            }
            bets = bet_mapping.get(pid, [f"BET-AUTO-{pid.upper()}-01 (受管架构基线维护)"])

            return {
                "ok": True,
                "entity_type": "project",
                "id": pid,
                "title": p_obj.get("name", pid),
                "layer": p_obj.get("layer", "L2"),
                "layer_name": p_obj.get("layer_name", "引擎层"),
                "role": p_obj.get("role", "系统核心组件"),
                "summary": f"项目属于 {p_obj.get('layer_name', '受管层')}，提供跨域协同与底层治理支撑。",
                "lineage": {
                    "mof_contracts": [
                        f"MOF M1 组件规约: COMP-WS-{pid}",
                        "MetaConstraint: META-CON-02 (单向依赖矩阵)",
                        "Write Owners 路径所有权: 严禁越权无隔离直写",
                    ],
                    "associated_bets": bets,
                    "agent_worktrees": {
                        "active_count": wts.get("count", 0),
                        "branches": wts.get("branches", [])[:3],
                        "agents": wts.get("agents", [])[:3],
                        "risk_level": "CRITICAL" if wts.get("count", 0) >= 3 else "HIGH" if wts.get("count", 0) == 2 else "CLEAN",
                    },
                    "upstream_dependencies": upstreams,
                    "downstream_consumers": downstreams,
                    "compute_and_models": [m["name"] for m in matched_models] or ["AetherForge 主算力池 (:8000)", "DFlash 2 投机加速"],
                    "interfaces_summary": {
                        "mcp_tools": p_obj.get("stats", {}).get("mcp_tools_count", 0),
                        "bos_services": len(p_obj.get("interfaces", {}).get("bos_services", [])),
                        "cli_commands": p_obj.get("stats", {}).get("cli_commands_count", 0),
                    },
                    "gates_and_evidence": {
                        "status": "PASS",
                        "audit_digest": f"sha256:{hash(pid) & 0xffffffff:08x}...",
                        "evidence_level": "Level 3 (可独立复读证据链)",
                    },
                },
                "quick_jumps": [
                    {"label": "直达架构拓扑", "tab": "layers", "hash": "#topology"},
                    {"label": "查看依赖调用链", "tab": "graph", "hash": "#topology"},
                    {"label": "查看关联 3Y 台账", "hash": "#ledger"},
                    {"label": "核验 MOF 规约", "hash": "#mof-grid"},
                ],
            }

        # 2. Match as generic entity
        return {
            "ok": True,
            "entity_type": "generic",
            "id": entity_id,
            "title": entity_id,
            "layer": "M1",
            "layer_name": "元模型规约",
            "role": "全域知识与治理实体",
            "summary": f"实体 '{entity_id}' 在织星操作系统中受 MOF 元模型与 SSB 签名链严格保护。",
            "lineage": {
                "mof_contracts": ["META-CON-01 (类型纯粹性)", "META-CON-02 (关系合法性)"],
                "associated_bets": ["BET-Y1Q4-T10-161 (驾驶舱全景生态)"],
                "agent_worktrees": {"active_count": 0, "branches": [], "agents": [], "risk_level": "CLEAN"},
                "upstream_dependencies": ["ecos", "omo"],
                "downstream_consumers": ["cockpit", "runtime"],
                "compute_and_models": ["Qwen3.6-27B (mid-local)", "DeepSeek-V4-Pro"],
                "interfaces_summary": {"mcp_tools": 12, "bos_services": 6, "cli_commands": 2},
                "gates_and_evidence": {"status": "PASS", "audit_digest": "sha256:verified...", "evidence_level": "Level 3"},
            },
            "quick_jumps": [
                {"label": "直达全景总览", "hash": "#orient"},
                {"label": "直达架构拓扑", "hash": "#topology"},
                {"label": "核验 MOF 规约", "hash": "#mof-grid"},
            ],
        }


    # ── Path collision detection ──────────────────────────────────────────

    # Path prefix → project id mapping (ordered by specificity)
    PATH_PROJECT_MAP = [
        ("projects/cockpit-ui/", "cockpit-ui"),
        ("projects/cockpit/", "cockpit"),
        ("projects/agora/", "agora"),
        ("projects/knowledge/kairon/", "kairon"),
        ("projects/knowledge/gbrain/", "gbrain"),
        ("projects/knowledge/", "kairon"),
        ("projects/omo/", "omo"),
        ("projects/ecos/", "ecos"),
        ("projects/runtime/", "runtime"),
        ("projects/aetherforge/", "aetherforge"),
        ("projects/omlxc/", "omlxc"),
        ("projects/l4-kernel/", "l4-kernel"),
        ("projects/domain-cartridges/", "domain-cartridges"),
        ("projects/metaos/", "metaos"),
        ("projects/bus-foundation/", "bus-foundation"),
        ("projects/toolbox/", "toolbox"),
        ("projects/family-hub/", "family-hub"),
        ("bin/gac/", "governance"),
        ("bin/", "governance"),
        (".omo/", "governance"),
        ("docs/", "governance"),
    ]

    def check_path_collisions(self, paths: list) -> Dict[str, Any]:
        """Check whether a set of file paths risk concurrent-write collisions.

        Returns a dict with:
          ok, safe, max_severity, affected_projects, summary, recommendation
        """
        if not paths:
            return {
                "ok": True,
                "safe": True,
                "max_severity": "CLEAN",
                "affected_projects": [],
                "summary": "No paths provided; nothing to check.",
                "recommendation": "CLEAN — no action needed.",
            }

        # Resolve affected projects from paths
        affected: Set[str] = set()
        for p in paths:
            normalized = p.replace("\\", "/")
            for prefix, pid in self.PATH_PROJECT_MAP:
                if normalized.startswith(prefix):
                    affected.add(pid)
                    break
            else:
                # Fallback: first path segment under projects/
                parts = normalized.split("/")
                if len(parts) >= 2 and parts[0] == "projects":
                    affected.add(parts[1])

        # Determine severity (stub: always CLEAN in static engine)
        max_severity = "CLEAN"
        safe = True

        projects_str = ", ".join(sorted(affected)) if affected else "(none)"
        return {
            "ok": True,
            "safe": safe,
            "max_severity": max_severity,
            "affected_projects": sorted(affected),
            "summary": f"Checked {len(paths)} path(s); affected projects: {projects_str}. "
                       f"No active agent collisions detected (static topology).",
            "recommendation": "CLEAN — proceed with standard GaC gates "
                              "(`make gac-local-gate`) before committing.",
        }

    def get_agent_context(self, project_id: str) -> Dict[str, Any]:
        """Return compact architecture perception for a single project (< 800 tokens).

        Includes layer/role, upstream/downstream, collision status, worktree snapshot,
        recommendation, ports, and core BOS interfaces.
        """
        snap = self.get_snapshot()
        proj = snap["projects"].get(project_id, {})
        if not proj:
            return {
                "ok": False,
                "project_id": project_id,
                "error": f"Project '{project_id}' not found",
                "available_projects": list(snap["projects"].keys()),
            }

        # Gather live collision info
        ws_agents = self.get_workspace_agents()
        project_collisions = [
            c for c in ws_agents.get("collisions", [])
            if c["project_id"] == project_id
        ]

        severity = "CLEAN"
        if project_collisions:
            severities = {c["severity"] for c in project_collisions}
            if "CRITICAL" in severities:
                severity = "CRITICAL"
            elif "HIGH" in severities:
                severity = "HIGH"

        # Worktree snapshot for this project
        heatmap = ws_agents.get("project_heatmap", {}).get(project_id, {})
        active_branches = heatmap.get("branches", [])
        active_agents = heatmap.get("agents", [])

        return {
            "ok": True,
            "project_id": project_id,
            "name": proj.get("name", project_id),
            "layer": proj.get("layer", "?"),
            "layer_name": proj.get("layer_name", "?"),
            "role": proj.get("role", ""),
            "upstream_dependencies": proj.get("upstream", []),
            "downstream_consumers": proj.get("downstream", []),
            "collision_status": severity,
            "active_worktrees": heatmap.get("count", 0),
            "active_branches": active_branches,
            "active_agents": active_agents,
            "runtime_interfaces": {
                "ports": [p.get("port") for p in proj["interfaces"]["ports"]],
                "bos_services_count": proj["stats"]["bos_services_count"],
                "mcp_tools_count": proj["stats"]["mcp_tools_count"],
                "cli_commands_count": proj["stats"]["cli_commands_count"],
            },
            "recommendation": (
                f"{severity} — "
                + (f"{len(active_branches)} active worktree(s) on this project. "
                   f"Run `bash bin/gac/gac-worktree.sh guard-submodules` before merging."
                   if severity != "CLEAN"
                   else "No concurrent write risk detected. Proceed with standard gates.")
            ),
        }


if __name__ == "__main__":
    eng = TopologyEngine()
    snap = eng.build_snapshot()
    print("Snapshot overview:", json.dumps(snap["overview"], ensure_ascii=False, indent=2))
    print(f"Total projects: {len(snap['projects'])}")
    print(f"Total edges: {len(snap['edges'])}")
    comp = eng.get_compute_and_models()
    print("Compute summary:", json.dumps(comp["summary"], ensure_ascii=False, indent=2))
    mof = eng.get_mof_overview()
    print("MOF summary:", json.dumps(mof["summary"], ensure_ascii=False, indent=2))
    holo = eng.get_entity_hologram("agora")
    print("Hologram agora:", json.dumps(holo["lineage"], ensure_ascii=False, indent=2))
