"""Bounded, read-only declaration catalog for Cockpit Observatory.

Migrated from zhixing-dashboard to cockpit core (BET-Y1Q4-T8-24A).
No subprocess, runtime import, network, tool invocation, or source write occurs.
The public function uses the discovered Workspace root; _collect is injectable for tests.
Registry status/exists fields are declarations, never health or execution proof.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from cockpit.compat import WORKSPACE_ROOT

MOF = "projects/ecos/src/ecos/ssot/mof"
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FILES = 200
MAX_RECORDS = 3000
MAX_MODELS = 100
MAX_SCAN_ENTRIES = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int = 480) -> str | None:
    if not isinstance(value, (str, int, float, bool)):
        return None
    cleaned = re.sub(r"[\x00-\x1f]", " ", str(value))[:limit]
    cleaned = re.sub(r"(?i)(bearer\s+|(?:api[-_]?key|password|secret|token)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", cleaned)
    cleaned = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{10,}|sk-[A-Za-z0-9_-]{12,})\b", "[REDACTED]", cleaned)
    cleaned = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", cleaned)
    return cleaned


def _strings(value: Any, limit: int = 100) -> list[str]:
    return [_text(x) for x in value[:limit] if _text(x)] if isinstance(value, list) else []


class Reader:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.sources: list[dict[str, Any]] = []
        self.errors: list[dict[str, str]] = []
        self.partial_reasons: list[str] = []
        self.total_bytes = 0

    def partial(self, reason: str) -> None:
        if reason not in self.partial_reasons:
            self.partial_reasons.append(reason)

    def schema_error(self, relative: str, code: str) -> None:
        self.errors.append({"source": relative, "code": code})
        self.partial(relative + ":" + code)
        for source in self.sources:
            if source["path"] == relative:
                source["schema_valid"] = False
                source.setdefault("schema_errors", []).append(code)

    def require(self, relative: str, document: Any, key_path: str, expected_type: type) -> bool:
        value = document
        for key in key_path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, expected_type):
            self.schema_error(relative, "schema_missing_or_invalid_" + key_path)
            return False
        for source in self.sources:
            if source["path"] == relative:
                source.setdefault("schema_valid", True)
        return True

    def load(self, relative: str) -> dict[str, Any]:
        source: dict[str, Any] = {"path": relative, "observed_at": _now(), "state": "missing", "sha256": None}
        self.sources.append(source)
        try:
            path = (self.root / relative).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError("outside_workspace")
            if len(self.sources) > MAX_FILES:
                raise ValueError("file_count_budget")
            size = path.stat().st_size
            if size > MAX_FILE_BYTES or self.total_bytes + size > MAX_TOTAL_BYTES:
                raise ValueError("byte_budget")
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES or self.total_bytes + len(raw) > MAX_TOTAL_BYTES:
                raise ValueError("byte_budget")
            self.total_bytes += len(raw)
            source.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            merged: dict[str, Any] = {}
            documents = list(yaml.safe_load_all(raw))
            for doc in documents:
                if doc is None:
                    continue
                if not isinstance(doc, dict):
                    raise ValueError("mapping_document_required")
                merged.update(doc)
            source.update(state="observed", document_count=len(documents))
            return merged
        except FileNotFoundError:
            code = "missing"
        except (yaml.YAMLError, UnicodeError):
            code = "yaml_parse_error"
        except OSError:
            code = "read_error"
        except ValueError as exc:
            code = str(exc)
        source.update(state="missing" if code == "missing" else "error", error=code)
        self.errors.append({"source": relative, "code": code})
        self.partial(relative + ":" + code)
        return {}

    def scan(self, relative: str, pattern: str) -> list[str]:
        directory = (self.root / relative).resolve()
        if not directory.is_relative_to(self.root):
            self.partial(relative + ":outside_workspace")
            return []
        result = []
        try:
            for index, path in enumerate(directory.iterdir()):
                if index >= MAX_SCAN_ENTRIES:
                    self.partial(relative + ":directory_budget")
                    break
                if path.match(pattern) and path.is_file():
                    result.append(str(path.relative_to(self.root)))
        except OSError:
            self.partial(relative + ":directory_unavailable")
        return sorted(result)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _capability(kind: str, identity: Any, title: Any, provider: Any, layer: Any, exists: Any, source: str, **extras: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": _text(identity),
        "title": _text(title),
        "provider": _text(provider),
        "layer": _text(layer),
        "exists": exists if isinstance(exists, bool) else None,
        "exists_basis": "registry_declaration",
        "source": source,
        "status": "declared",
        "online": None,
        **extras,
    }


def _collect(root: Path) -> dict[str, Any]:
    reader = Reader(root)
    project_path = "docs/project-registry.yaml"
    layer_path = "docs/layer-contract.yaml"
    capability_path = "docs/generated/capability-registry.yaml"
    bos_path = "projects/agora/etc/bos-services.yaml"
    project_doc = reader.load(project_path)
    layer_doc = reader.load(layer_path)
    cap_doc = reader.load(capability_path)
    bos_doc = reader.load(bos_path)
    for path, doc, key, typ in (
        (project_path, project_doc, "projects", dict),
        (layer_path, layer_doc, "layers", dict),
        (layer_path, layer_doc, "dependency_rules.allowed_directions", list),
        (capability_path, cap_doc, "mcp_servers", list),
        (capability_path, cap_doc, "cli_commands", list),
        (capability_path, cap_doc, "skills", list),
        (capability_path, cap_doc, "workflows", list),
    ):
        reader.require(path, doc, key, typ)
    bos_comparable = reader.require(bos_path, bos_doc, "services", list)
    projection_comparable = reader.require(capability_path, cap_doc, "bos_services.domains", dict)

    projects = []
    for name, raw in _dict(project_doc.get("projects")).items():
        item = _dict(raw)
        projects.append({
            "id": _text(name),
            "name": _text(name),
            "layer": _text(item.get("layer")),
            "role": _text(item.get("role")),
            "stack": _text(item.get("stack")),
            "status": _text(item.get("status")) or "unspecified",
            "status_basis": "registry_declaration",
            "source": project_path,
        })
        for child_name, child in item.items():
            if isinstance(child, dict) and child.get("role") and ("submodule" in child or "src_dir" in child):
                projects.append({
                    "id": _text(name + "/" + child_name),
                    "name": _text(child_name),
                    "parent": _text(name),
                    "layer": _text(child.get("layer", item.get("layer"))),
                    "role": _text(child.get("role")),
                    "stack": _text(child.get("stack")),
                    "status": _text(child.get("status")) or "unspecified",
                    "status_basis": "registry_declaration",
                    "source": project_path,
                })
    layers = [
        {
            "id": _text(k),
            "name": _text(v.get("name")),
            "description": _text(v.get("description")),
            "projects": _strings(v.get("projects")),
            "source": layer_path,
        }
        for k, v in _dict(layer_doc.get("layers")).items()
        if isinstance(v, dict)
    ]
    rules = _dict(layer_doc.get("dependency_rules"))
    dependency_rules = {
        key: [
            {
                "from": _strings(x.get("from")),
                "to": _strings(x.get("to")),
                "source": layer_path,
                "evidence_class": "allowed_policy" if key == "allowed_directions" else "forbidden_policy",
            }
            for x in _rows(rules.get(key))[:100]
            if isinstance(x, dict)
        ]
        for key in ("allowed_directions", "forbidden_patterns")
    }
    dependency_rules["exceptions"] = [
        {
            "from": _text(x.get("project")),
            "to": _text(x.get("depends_on")),
            "reason": _text(x.get("reason")),
            "source": layer_path,
            "evidence_class": "declared_exception",
        }
        for x in _rows(layer_doc.get("exceptions"))[:100]
        if isinstance(x, dict)
    ]

    services = []
    for row in _rows(bos_doc.get("services"))[:MAX_RECORDS]:
        if not isinstance(row, dict):
            reader.schema_error(bos_path, "schema_invalid_service_row")
            bos_comparable = False
            continue
        uri = _text(row.get("uri"))
        if not uri or not uri.startswith("bos://"):
            reader.schema_error(bos_path, "schema_invalid_uri_row")
            bos_comparable = False
            continue
        services.append({
            "uri": uri,
            "domain": _text(row.get("domain")),
            "package": _text(row.get("package")),
            "transport": _text(row.get("transport")),
            "status": _text(row.get("status")),
            "description": _text(row.get("description")),
            "source": bos_path,
            "evidence_class": "declaration",
            "online": None,
        })
    if len(_rows(bos_doc.get("services"))) > MAX_RECORDS:
        reader.partial(bos_path + ":record_budget")
        bos_comparable = False

    capabilities = []
    for row in _rows(cap_doc.get("mcp_servers")):
        if not isinstance(row, dict):
            continue
        server = row.get("id")
        capabilities.append(
            _capability("mcp_server", server, row.get("name"), server, row.get("layer"), row.get("exists"), capability_path,
                        definition_path=_text(row.get("file")), transport=_text(row.get("transport")))
        )
        for tool in _rows(row.get("tools")):
            if not isinstance(tool, str):
                continue
            capabilities.append(
                _capability("mcp_tool", str(server) + ":" + tool, tool, server, row.get("layer"), row.get("exists"), capability_path)
            )
    for kind, key in (("cli", "cli_commands"), ("skill", "skills"), ("workflow", "workflows")):
        for row in _rows(cap_doc.get(key)):
            if isinstance(row, dict):
                name = row.get("id") or row.get("name")
                capabilities.append(
                    _capability(kind, name, row.get("description") or name,
                                "cockpit" if kind == "cli" else "workspace", None, row.get("exists"), capability_path,
                                definition_path=_text(row.get("file")))
                )
    for row in services:
        capabilities.append(
            _capability("bos", row["uri"], row["description"] or row["uri"], row["package"], None, None, bos_path,
                        declared_status=row["status"], transport=row["transport"])
        )
    capabilities_total = len(capabilities)
    if capabilities_total > MAX_RECORDS:
        reader.partial("capabilities:record_budget")
    capabilities = capabilities[:MAX_RECORDS]

    m3path = MOF + "/m3.yaml"
    m3doc = reader.load(m3path)
    reader.require(m3path, m3doc, "m3.elements", dict)
    reader.require(m3path, m3doc, "m3.relations", dict)
    m3 = _dict(m3doc.get("m3"))
    legend = []
    for family in ("elements", "relations"):
        for key, row in list(_dict(m3.get(family)).items())[:120]:
            if isinstance(row, dict):
                legend.append({
                    "id": _text(row.get("id") or key),
                    "name": _text(row.get("name")),
                    "parent": _text(row.get("parent")),
                    "description": _text(row.get("description")),
                    "abstract": row.get("abstract") if isinstance(row.get("abstract"), bool) else None,
                    "family": family,
                    "mof_level": "M3",
                    "source": m3path,
                })
    m2paths = reader.scan(MOF + "/m2", "*.yaml")
    models = []
    for relative in m2paths[:MAX_MODELS]:
        doc = reader.load(relative)
        identity = _text(doc.get("m2_type"))
        if not identity:
            if doc:
                reader.partial(relative + ":not_type_schema")
            continue
        row = _dict(doc.get(identity))
        machine = _dict(row.get("stateMachine"))
        models.append({
            "id": identity,
            "mof_level": "M2",
            "parent": _text(row.get("m3_parent")),
            "description": _text(row.get("description")),
            "icon": _text(row.get("icon"), 20),
            "version": _text(doc.get("version")),
            "source": relative,
            "required_properties": [_text(k) for k in list(_dict(row.get("requiredProperties")))[:80]],
            "states": [_text(k) for k in list(machine)[:30]],
            "transitions": [
                {"from": _text(k), "to": _text(target)}
                for k, state in list(machine.items())[:30]
                for target in _strings(_dict(state).get("transitions"), 30)
            ],
        })
    if len(m2paths) > MAX_MODELS:
        reader.partial("mof:m2_file_budget")
    nodepaths = reader.scan(MOF + "/nodes", "COMP-WS-*.yaml")
    nodes = []
    for relative in nodepaths[:40]:
        doc = reader.load(relative)
        if doc.get("id"):
            nodes.append({
                "id": _text(doc.get("id")),
                "name": _text(doc.get("name")),
                "type": _text(doc.get("type")),
                "mof_level": "M1",
                "layer": _text(doc.get("layer")),
                "description": _text(doc.get("description")),
                "declared_status": _text(doc.get("status")),
                "sfop_slot": _text(_dict(doc.get("properties")).get("sfop_slot")),
                "source": relative,
                "online": None,
            })
    if len(nodepaths) > 40:
        reader.partial("mof:m1_sample_budget")
    m0path = MOF + "/m0/snapshot.yaml"
    m0 = reader.load(m0path)
    reader.require(m0path, m0, "generated_at", str)
    mof = {
        "hierarchy": [
            {"id": "M3", "name": "元元模型", "meaning": "定义元素、关系与类型系统", "source": m3path},
            {"id": "M2", "name": "元模型", "meaning": "定义 Agent / WorkPacket / Receipt 等类型合同", "source": MOF + "/m2"},
            {"id": "M1", "name": "模型", "meaning": "组件等实例的声明与关系", "source": MOF + "/nodes"},
            {"id": "M0", "name": "运行快照", "meaning": "已持久化的运行观测，须按源时间判读", "source": m0path},
        ],
        "legend": legend,
        "models": models,
        "node_samples": nodes,
        "sample_scope": "M2 top-level YAML; M1 nodes/COMP-WS-*.yaml only; not full MOF inventory",
        "sample_partial": True,
        "counts": {
            "m3_elements": sum(x["family"] == "elements" for x in legend),
            "m3_relations": sum(x["family"] == "relations" for x in legend),
            "m2_files_discovered": len(m2paths),
            "m2_types_loaded": len(models),
            "m1_component_samples": len(nodes),
        },
        "m0": {
            "source": m0path,
            "source_generated_at": _text(m0.get("generated_at")),
            "declared_m1_node_count": m0.get("m1_node_count") if isinstance(m0.get("m1_node_count"), int) else None,
            "health": "NOT_PROVEN",
            "proof_scope": "stored snapshot metadata only; no live health call",
        },
    }
    counts = {
        "projects": len(projects),
        "layers": len(layers),
        "bos_services": len(services),
        "capabilities": len(capabilities),
        "capabilities_before_limit": capabilities_total,
        "by_kind": dict(sorted(Counter(x["kind"] for x in capabilities).items())),
        "by_provider": dict(sorted(Counter(x["provider"] or "unspecified" for x in capabilities).items())),
        "bos_by_domain": dict(sorted(Counter(x["domain"] or "unspecified" for x in services).items())),
        "bos_by_transport": dict(sorted(Counter(x["transport"] or "unspecified" for x in services).items())),
    }
    generated_bos = _dict(_dict(cap_doc.get("bos_services")).get("domains"))
    if any(not isinstance(rows, list) or any(not isinstance(row, dict) or
           not isinstance(row.get("uri"), str) or not row["uri"].startswith("bos://")
           for row in rows) for rows in generated_bos.values()):
        reader.schema_error(capability_path, "schema_invalid_projected_bos_rows")
        projection_comparable = False
    generated_uris = {
        str(row.get("uri"))
        for rows in generated_bos.values()
        for row in _rows(rows)
        if isinstance(row, dict) and isinstance(row.get("uri"), str)
    }
    canonical_uris = {x["uri"] for x in services}
    comparison_proven = bos_comparable and projection_comparable
    uri_domain_mismatches = [
        {"uri": row["uri"], "declared_domain": row["domain"], "uri_domain": row["uri"].split("/")[2]}
        for row in services
        if row["domain"] != row["uri"].split("/")[2]
    ]
    projection_comparison = {
        "state": "OBSERVED" if comparison_proven else "UNPROVABLE",
        "canonical_source": bos_path,
        "projection_source": capability_path,
        "canonical_unique_uris": len(canonical_uris),
        "projected_unique_uris": len(generated_uris),
        "missing_from_projection": sorted(canonical_uris - generated_uris)[:100] if comparison_proven else [],
        "projection_only": sorted(generated_uris - canonical_uris)[:100] if comparison_proven else [],
        "uri_set_equal": canonical_uris == generated_uris if comparison_proven else None,
        "unprovable_reason": None if comparison_proven else "source_schema_missing_invalid_or_truncated",
        "canonical_domain_field_counts": counts["bos_by_domain"],
        "uri_domain_counts": dict(sorted(Counter(x["uri"].split("/")[2] for x in services).items())),
        "declared_domain_differs_from_uri_count": len(uri_domain_mismatches),
        "domain_mismatch_samples": uri_domain_mismatches[:20],
        "proof_scope": "declaration consistency only; mismatches do not establish live routing behavior",
    }
    for source in reader.sources:
        source["extracted_record_count"] = sum(
            x["source"] == source["path"]
            for x in capabilities + projects + layers + legend + models + nodes
        )
    source_summary = {
        "files_observed": sum(x["state"] == "observed" for x in reader.sources),
        "files_missing": sum(x["state"] == "missing" for x in reader.sources),
        "files_error": sum(x["state"] == "error" for x in reader.sources),
        "bytes_read": reader.total_bytes,
    }
    return {
        "schema": "dashboard-catalog/v1",
        "observed_at": _now(),
        "state": "PARTIAL" if reader.partial_reasons else "OBSERVED",
        "authority_class": "observational",
        "implementation_authorized": False,
        "proof_scope": "local Workspace declarations only; allowed dependency edges are policy, not measured calls; no online proof",
        "projects": projects,
        "layers": layers,
        "dependency_rules": dependency_rules,
        "mof": mof,
        "bos_services": services,
        "capabilities": capabilities,
        "counts": counts,
        "bos_projection_comparison": projection_comparison,
        "source_summary": source_summary,
        "sources": reader.sources,
        "partial": bool(reader.partial_reasons),
        "partial_reasons": reader.partial_reasons,
        "errors": reader.errors,
        "budgets": {
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES,
            "max_files": MAX_FILES,
            "max_records": MAX_RECORDS,
            "max_m2_files": MAX_MODELS,
            "max_directory_entries": MAX_SCAN_ENTRIES,
        },
    }


def collect_catalog(workspace: Path | None = None) -> dict[str, Any]:
    """Return JSON-friendly read-only architecture, MOF, BOS, capability data."""
    root = (workspace or WORKSPACE_ROOT).resolve()
    return _collect(root)
