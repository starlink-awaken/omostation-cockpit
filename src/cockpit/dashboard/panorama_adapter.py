"""Read-only, provenance-gated adapter for Zhixing dashboard projections."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from cockpit.dashboard.constants import WORKSPACE_ROOT

PANORAMA_BASE_URL = "http://127.0.0.1:43191"
PANORAMA_HEALTH_URL = f"{PANORAMA_BASE_URL}/health"
PANORAMA_FULL_DATA_URL = f"{PANORAMA_BASE_URL}/data.json"
PANORAMA_COMPACT_DATA_URL = f"{PANORAMA_BASE_URL}/__panorama_data__"
PANORAMA_AGENT_BRIEF_URL = f"{PANORAMA_BASE_URL}/agent-brief.json"
PANORAMA_MAX_HEALTH_BYTES = 64 * 1024
PANORAMA_MAX_DATA_BYTES = 16 * 1024 * 1024
PANORAMA_MAX_BRIEF_BYTES = 4 * 1024 * 1024
PANORAMA_MAX_OBSERVATION_BYTES = 4 * 1024 * 1024
# The bound full projection is a multi-megabyte JSON artifact. Keep the upstream
# budget below the UI's 10s request deadline while allowing slower local reads.
PANORAMA_REQUEST_TIMEOUT_SECONDS = 8.0
PANORAMA_TOTAL_TIMEOUT_SECONDS = 9.0
PANORAMA_MAX_AGE_SECONDS = 5 * 60
AGENT_VISIBILITY_MAX_AGE_SECONDS = 6 * 60 * 60
PANORAMA_OBSERVATION_SCHEMA = "panorama-compact-observation/v1"
PANORAMA_OBSERVATION_PATH = Path(
    os.environ.get(
        "PANORAMA_COMPACT_OBSERVATION_PATH",
        str(
            Path(os.environ.get("OMOSTATION_STATE_ROOT", str(WORKSPACE_ROOT)))
            / "runtime/dashboard/compact-observation.json"
        ),
    )
).expanduser()

# These Cockpit facets have no complete, field-level contract in the compact
# fallback. They stay PARTIAL/UNKNOWN until the full revision artifact is
# readable again; no objective-coverage item is ever promoted to a gate.
UNVERIFIED_FACETS = (
    "gates",
    "alerts",
    "posture",
    "guardian",
    "topology",
    "evolution",
    "knowledge_health",
    "experience_graph",
    "workspace",
    "launchd_health",
    "connectors",
    "agent_visibility",
)
_GATE_IDS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "RF0", "RC-DL")


class PanoramaSourceError(ValueError):
    """An upstream response that cannot safely be represented as current data."""


class FullProjectionUnavailableError(PanoramaSourceError):
    """The known bound-reader size failure; compact fallback is permitted."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PanoramaSourceError(f"schema_invalid:{name}_must_be_object")
    return value


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PanoramaSourceError(f"schema_invalid:{name}_missing")
    return value


def _timestamp(value: object, name: str) -> datetime:
    raw = _nonempty_string(value, name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PanoramaSourceError(f"schema_invalid:{name}_invalid") from exc
    if parsed.tzinfo is None:
        raise PanoramaSourceError(f"schema_invalid:{name}_timezone_missing")
    return parsed.astimezone(UTC)


def _number(value: object) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _read_observation(path: Path = PANORAMA_OBSERVATION_PATH) -> object | None:
    """Read the optional collector state through a bounded, no-follow boundary."""
    try:
        if path.is_symlink():
            return None
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > PANORAMA_MAX_OBSERVATION_BYTES:
                return None
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                body = stream.read(PANORAMA_MAX_OBSERVATION_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(body) > PANORAMA_MAX_OBSERVATION_BYTES:
            return None
        return json.loads(body)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _unknown_posture() -> dict[str, None]:
    """Represent unobserved posture without fabricating a zero score."""
    return {
        "health_score": None,
        "compliance_rate": None,
        "active_agents_count": None,
    }


def _unknown_guardian() -> dict[str, Any]:
    """Represent an unobserved guardian without claiming it is offline."""
    return {
        "interval_seconds": None,
        "status": "UNKNOWN",
        "last_heartbeat": None,
        "healthy_count": None,
        "warning_count": None,
        "danger_count": None,
    }


def _unknown_gates() -> list[dict[str, Any]]:
    return [
        {
            "id": identifier,
            "title": identifier,
            "verdict": "UNKNOWN",
            "detail": "数据源未提供此门禁的逐项可验证结论。",
            "live": False,
        }
        for identifier in _GATE_IDS
    ]


def _unknown_payload(error: str, fetched_at: str) -> dict[str, Any]:
    return {
        "generated_at": "",
        "mode": "UNKNOWN",
        "data_state": "UNKNOWN",
        "source": {
            "kind": "zhixing-dashboard",
            "url": PANORAMA_FULL_DATA_URL,
            "status": "UNKNOWN",
            "fetched_at": fetched_at,
            "error": error,
            "partial_facets": list(UNVERIFIED_FACETS),
        },
        "posture": _unknown_posture(),
        "gates": [],
        "guardian": _unknown_guardian(),
        "alerts": [],
        "topology": None,
        "evolution": None,
    }


def _read_only_health(health: object, now: datetime) -> Mapping[str, Any]:
    value = _mapping(health, "health")
    if value.get("read_only") is not True:
        raise PanoramaSourceError("health_not_read_only")
    if value.get("code_drift") is not False:
        raise PanoramaSourceError("health_code_drift_or_unknown")
    if value.get("projection_status") != "BOUND_FRESH":
        raise PanoramaSourceError("projection_not_bound_fresh")
    if _timestamp(value.get("projection_fresh_until"), "health.projection_fresh_until") <= now:
        raise PanoramaSourceError("projection_lease_expired")
    _nonempty_string(value.get("state_revision"), "health.state_revision")
    return value


def _validate_generated_at(value: Mapping[str, Any], name: str, now: datetime) -> datetime:
    generated_at = _timestamp(value.get("generated_at"), f"{name}.generated_at")
    age = (now - generated_at).total_seconds()
    if age < 0:
        raise PanoramaSourceError("projection_generated_in_future")
    return generated_at


def _freshness(generated_at: datetime, now: datetime) -> tuple[str, str]:
    """Keep a provenance-valid old snapshot visible while marking it stale."""
    if (now - generated_at).total_seconds() > PANORAMA_MAX_AGE_SECONDS:
        return "STALE", "projection_stale"
    return "PARTIAL", "field_provenance_partial"


def _canonical_digest(value: object) -> str:
    """Digest exactly the value covered by a field-level evidence record."""
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PanoramaSourceError("schema_invalid:field_value_not_canonicalizable") from exc
    return hashlib.sha256(encoded).hexdigest()


def _current_observation_collector_digest() -> str | None:
    try:
        return hashlib.sha256((WORKSPACE_ROOT / "bin/panorama/panorama-collect.py").read_bytes()).hexdigest()
    except OSError:
        return None


def _bound_field_provenance(
    projection: Mapping[str, Any],
    field: str,
    *,
    revision_id: str,
    now: datetime,
) -> Mapping[str, Any] | None:
    """Check a field's revision, observation time, and exact-value digest.

    A full projection is an immutable artifact, but it is not enough to know
    that *some* artifact was read.  Gate verdicts become displayable only when
    their own field proof binds the exact array to the health revision.
    """
    evidence_by_field = projection.get("field_provenance")
    if not isinstance(evidence_by_field, Mapping):
        return None
    evidence = evidence_by_field.get(field)
    if not isinstance(evidence, Mapping):
        return None
    if evidence.get("revision_id") != revision_id:
        return None
    source_ref = evidence.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref.strip():
        return None
    source_digest = evidence.get("source_digest")
    if not isinstance(source_digest, str) or len(source_digest) != 64:
        return None
    try:
        int(source_digest, 16)
        observed_at = _timestamp(evidence.get("observed_at"), f"field_provenance.{field}.observed_at")
    except (ValueError, PanoramaSourceError):
        return None
    if observed_at > now or (now - observed_at).total_seconds() > PANORAMA_MAX_AGE_SECONDS:
        return None
    return evidence if source_digest == _canonical_digest(projection.get(field)) else None


def _validate_full_projection_binding(
    projection: Mapping[str, Any],
    compact_binding: object,
    health: Mapping[str, Any],
) -> None:
    """Bind a full artifact through the compact revision metadata.

    The full endpoint deliberately serves only the immutable projection body;
    its body digest is not the health manifest digest and it currently carries
    no revision field.  The compact endpoint is the authoritative bridge: its
    ``source`` names the health revision and its generation must equal the full
    body's generation.  Both checks are required before any full-field value
    is considered part of the current revision.
    """
    binding = _mapping(compact_binding, "compact_binding")
    if _nonempty_string(binding.get("source"), "compact_binding.source") != health["state_revision"]:
        raise PanoramaSourceError("projection_revision_mismatch")
    if _nonempty_string(projection.get("generation_id"), "projection.generation_id") != _nonempty_string(
        binding.get("generation_id"), "compact_binding.generation_id"
    ):
        raise PanoramaSourceError("projection_generation_mismatch")


def _project_gates(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise PanoramaSourceError("schema_invalid:gates_must_be_nonempty_array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        gate = _mapping(raw, f"gates[{index}]")
        identifier = _nonempty_string(gate.get("id"), f"gates[{index}].id")
        title = _nonempty_string(gate.get("title"), f"gates[{index}].title")
        source_verdict = gate.get("verdict")
        if not isinstance(source_verdict, str):
            raise PanoramaSourceError(f"schema_invalid:gates[{index}].verdict")
        normalized_source_verdict = source_verdict.upper()
        verdict = {
            "PASS": "PASS",
            "FAIL": "FAIL",
            "WARN": "WARN",
            "PARTIAL": "WARN",
            "UNKNOWN": "UNKNOWN",
            "NOT_ADMITTED": "BLOCKED",
            "BLOCKED": "BLOCKED",
            "PENDING": "PENDING",
            # ABSENT means the producer has no qualifying evidence; it is not
            # a pass or failure and must remain visibly unverified.
            "ABSENT": "UNKNOWN",
        }.get(normalized_source_verdict)
        if verdict is None:
            raise PanoramaSourceError(f"schema_invalid:gates[{index}].verdict")
        detail = str(gate.get("detail") or "")
        if verdict != normalized_source_verdict:
            detail = f"{detail}（原始状态：{normalized_source_verdict}）" if detail else f"原始状态：{normalized_source_verdict}"
        result.append({
            "id": identifier,
            "title": title,
            "verdict": verdict,
            "detail": detail,
            "live": gate.get("live") if isinstance(gate.get("live"), bool) else False,
            "last_checked_at": gate.get("last_checked_at"),
        })
    return result


def _project_alerts(value: object) -> list[dict[str, Any]]:
    raw_alerts = value.get("alerts", []) if isinstance(value, Mapping) else value
    if not isinstance(raw_alerts, list):
        raise PanoramaSourceError("schema_invalid:alerts_must_be_array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_alerts):
        alert = _mapping(raw, f"alerts[{index}]")
        severity = {"critical": "critical", "high": "critical", "warning": "warning", "medium": "warning", "info": "info", "low": "info"}.get(str(alert.get("severity", "info")).lower(), "info")
        message = str(alert.get("message") or alert.get("msg") or "")
        result.append({
            "id": str(alert.get("id") or f"alert-{index + 1}"),
            "title": str(alert.get("title") or message or "观察项"),
            "severity": severity,
            "category": str(alert.get("category") or "observer"),
            "timestamp": str(alert.get("timestamp") or ""),
            "message": message,
            "source": str(alert.get("source") or "zhixing-projection"),
        })
    return result


def _project_knowledge_health(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    names = ("total", "fresh", "stale", "orphaned", "freshness_pct", "coverage_pct", "orphan_pct")
    if any(_number(value.get(name)) is None for name in names):
        return None
    result: dict[str, Any] = {name: value[name] for name in names}
    stale_docs = value.get("stale_docs")
    if isinstance(stale_docs, list):
        normalized: list[dict[str, Any]] = []
        for item in stale_docs:
            if not isinstance(item, Mapping) or not isinstance(item.get("path"), str) or _number(item.get("age_days")) is None:
                return None
            normalized.append({"path": item["path"], "age_days": item["age_days"]})
        result["stale_docs"] = normalized
    return result


def _project_experience_graph(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    internal_refs, connectivity_pct = _number(value.get("internal_refs")), _number(value.get("connectivity_pct"))
    nodes_by_type, hotspots = value.get("nodes_by_type"), value.get("hotspots")
    if internal_refs is None or connectivity_pct is None or not isinstance(nodes_by_type, Mapping) or not isinstance(hotspots, list):
        return None
    if any(not isinstance(name, str) or _number(count) is None for name, count in nodes_by_type.items()):
        return None
    normalized_hotspots: list[dict[str, Any]] = []
    for item in hotspots:
        if not isinstance(item, Mapping) or not isinstance(item.get("type"), str) or _number(item.get("count")) is None:
            return None
        normalized_hotspots.append({"type": item["type"], "count": item["count"]})
    return {"nodes_by_type": dict(nodes_by_type), "internal_refs": internal_refs, "hotspots": normalized_hotspots, "connectivity_pct": connectivity_pct}


def _project_connectors(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or _number(value.get("total")) is None:
        return None
    result: dict[str, Any] = {"total": value["total"]}
    for name in ("available", "wired_to_scenes", "unwired_available"):
        items = value.get(name)
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            return None
        result[name] = list(items)
    return result


def _compact_alerts(value: object, observed_at: str) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping) or (errors := _number(value.get("last_run_errors"))) is None or errors <= 0:
        return []
    return [{
        "id": "zhixing-bos-verifier-errors",
        "title": "BOS verifier reported errors",
        "severity": "warning",
        "category": "verification",
        "timestamp": observed_at,
        "message": f"BOS verifier last run reported {errors} errors.",
        "source": "zhixing-compact-projection.bos_verifier.last_run_errors",
    }]


def _base_payload(*, generated_at: datetime, fetched_at: str, health: Mapping[str, Any], kind: str, url: str, state: str, error: str, partial_facets: list[str]) -> dict[str, Any]:
    observed_at = _iso(generated_at)
    return {
        "generated_at": observed_at,
        "mode": "read-only-ssot-aggregation",
        "data_state": state,
        "source": {
            "kind": kind,
            "url": url,
            "status": state,
            "fetched_at": fetched_at,
            "observed_at": observed_at,
            "projection_fresh_until": health["projection_fresh_until"],
            "revision_id": health["state_revision"],
            "error": error,
            "partial_facets": partial_facets,
        },
        "posture": _unknown_posture(),
        "gates": _unknown_gates(),
        "guardian": _unknown_guardian(),
        "alerts": [],
        "topology": None,
        "evolution": None,
    }


def _attach_optional_sections(result: dict[str, Any], data: Mapping[str, Any], partial_facets: list[str]) -> None:
    for name, value in {
        "knowledge_health": _project_knowledge_health(data.get("knowledge_health")),
        "experience_graph": _project_experience_graph(data.get("experience_graph")),
        "connectors": _project_connectors(data.get("connectors")),
    }.items():
        if value is not None and _bound_field_provenance(
            data, name, revision_id=result["source"]["revision_id"], now=_utc_now()
        ) is not None:
            result[name] = value
            partial_facets.remove(name)


def _project_field_if_proven(
    result: dict[str, Any], data: Mapping[str, Any], field: str, projector: Any,
    *, revision_id: str, now: datetime, partial_facets: list[str],
) -> None:
    evidence = _bound_field_provenance(data, field, revision_id=revision_id, now=now)
    if evidence is None:
        return
    try:
        value = projector(data.get(field))
    except PanoramaSourceError:
        return
    if value is None:
        return
    result[field] = value
    if field in partial_facets:
        partial_facets.remove(field)
    result["source"].setdefault("field_provenance", {})[field] = {
        "revision_id": evidence["revision_id"],
        "observed_at": evidence["observed_at"],
        "source_digest": evidence["source_digest"],
        "source_ref": evidence["source_ref"],
    }


def _project_bos_verifier(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    last_run_ok = _number(value.get("last_run_ok"))
    last_run_errors = _number(value.get("last_run_errors"))
    if last_run_ok is None or last_run_errors is None:
        return None
    return {"last_run_ok": last_run_ok, "last_run_errors": last_run_errors}


def _project_evolution(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    total = _number(value.get("total"))
    paths = value.get("proposal_paths")
    recent = value.get("recent_proposals")
    if (
        total is None
        or total < 0
        or int(total) != total
        or not isinstance(paths, list)
        or len(paths) != int(total)
        or any(not isinstance(path, str) or not path for path in paths)
        or paths != sorted(set(paths))
        or not isinstance(recent, list)
        or any(not isinstance(item, str) for item in recent)
    ):
        return None
    return {"total": int(total), "proposal_paths": list(paths), "recent_proposals": list(recent)}


def _project_workspace(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    worktrees, lock_files = value.get("worktrees"), value.get("lock_files")
    total_worktrees, total_lock_files = _number(value.get("total_worktrees")), _number(value.get("total_lock_files"))
    if (
        not isinstance(worktrees, list)
        or total_worktrees is None
        or int(total_worktrees) != total_worktrees
        or total_worktrees != len(worktrees)
        or not isinstance(lock_files, list)
        or total_lock_files is None
        or int(total_lock_files) != total_lock_files
        or total_lock_files != len(lock_files)
        or any(
            not isinstance(item, Mapping)
            or not isinstance(item.get("path"), str)
            or not item.get("path")
            or (item.get("branch") is not None and not isinstance(item.get("branch"), str))
            for item in worktrees
        )
        or any(not isinstance(path, str) or not path for path in lock_files)
    ):
        return None
    return {
        "worktrees": [
            {"path": item["path"], **({"branch": item["branch"]} if isinstance(item.get("branch"), str) else {})}
            for item in worktrees
        ],
        "total_worktrees": int(total_worktrees),
        "lock_files": list(lock_files),
        "total_lock_files": int(total_lock_files),
    }


def _project_launchd_health(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or value.get("schema") != "launchd-health-observation/v1":
        return None
    jobs = value.get("jobs")
    registry_digest = value.get("registry_sha256")
    if (
        not isinstance(jobs, list) or not jobs
        or value.get("facet_state") not in {"LIVE", "PARTIAL"}
        or value.get("verdict") not in {"PASS", "DEGRADED", "FAILED"}
        or not isinstance(registry_digest, str) or len(registry_digest) != 64
    ):
        return None
    try:
        int(registry_digest, 16)
        _canonical_digest(value)
    except (ValueError, PanoramaSourceError):
        return None
    for job in jobs:
        if (
            not isinstance(job, Mapping)
            or not isinstance(job.get("label"), str)
            or not isinstance(job.get("uid"), int)
            or job.get("command_result_class") not in {"loaded", "confirmed_unloaded", "unknown"}
            or not isinstance(job.get("observed_at"), str)
            or not isinstance(job.get("stdout"), str)
            or not isinstance(job.get("stderr"), str)
        ):
            return None
    return dict(value)


def _project_agent_visibility(value: object) -> dict[str, Any] | None:
    """Keep the projection-derived visibility view and its subordinate evidence intact."""
    if not isinstance(value, Mapping) or value.get("available") is not True:
        return None
    if not isinstance(value.get("input_sources"), Mapping):
        return None
    if not isinstance(value.get("generation_id"), str) or not value["generation_id"].strip():
        return None
    normalized = dict(value)
    try:
        _canonical_digest(normalized)
    except PanoramaSourceError:
        return None
    return normalized


def _apply_compact_observation(
    result: dict[str, Any],
    observation: object,
    *,
    now: datetime,
    partial_facets: list[str],
) -> None:
    """Attach direct facet evidence without inheriting projection lease time."""
    if not isinstance(observation, Mapping) or observation.get("schema") != PANORAMA_OBSERVATION_SCHEMA:
        return
    facets = observation.get("facets")
    if not isinstance(facets, Mapping):
        return
    projectors = {
        "knowledge_health": _project_knowledge_health,
        "experience_graph": _project_experience_graph,
        "connectors": _project_connectors,
        "bos_verifier": _project_bos_verifier,
        "evolution": _project_evolution,
        "workspace": _project_workspace,
        "launchd_health": _project_launchd_health,
    }
    source_refs = {
        "knowledge_health": "bin/panorama/panorama-collect.py::collect_knowledge_health",
        "experience_graph": "bin/panorama/panorama-collect.py::collect_experience_graph",
        "connectors": "bin/panorama/panorama-collect.py::collect_connectors",
        "bos_verifier": "bin/panorama/panorama-collect.py::collect_bos_verifier",
        "evolution": "bin/panorama/panorama-collect.py::collect_evolution",
        "workspace": "bin/panorama/panorama-collect.py::collect_workspace_hygiene",
        "launchd_health": "bin/panorama/panorama-collect.py::collect_launchd_health",
    }
    expected_collector_digest = _current_observation_collector_digest()
    projected_meta: dict[str, Any] = {}
    for name, projector in projectors.items():
        raw = facets.get(name)
        if not isinstance(raw, Mapping):
            continue
        status = raw.get("observation_status", raw.get("status"))
        if raw.get("status") is not None and raw.get("status") != status:
            continue
        if status not in {"OBSERVED", "STALE", "UNKNOWN"}:
            continue
        try:
            last_attempt_at = _timestamp(raw.get("last_attempt_at"), f"observation.{name}.last_attempt_at")
        except PanoramaSourceError:
            continue
        if last_attempt_at > now:
            continue
        duration_ms = _number(raw.get("duration_ms"))
        overrun = raw.get("overrun")
        provenance = raw.get("provenance")
        if duration_ms is None or duration_ms < 0 or not isinstance(overrun, bool) or not isinstance(provenance, Mapping):
            continue
        source_ref = provenance.get("source_ref")
        collector_sha256 = provenance.get("collector_sha256")
        source_digest = raw.get("source_digest")
        provenance_source_digest = provenance.get("source_digest")
        if (
            provenance.get("kind") != "direct-read"
            or source_ref != source_refs[name]
            or expected_collector_digest is None
            or collector_sha256 != expected_collector_digest
            or not isinstance(collector_sha256, str)
            or len(collector_sha256) != 64
            or (provenance_source_digest is not None and provenance_source_digest != source_digest)
        ):
            continue
        try:
            int(collector_sha256, 16)
        except ValueError:
            continue
        error_class = raw.get("error_class")
        projected = projector(raw.get("value"))
        observed_at: datetime | None = None
        last_success_at: datetime | None = None
        if raw.get("observed_at") is not None or raw.get("last_success_at") is not None:
            try:
                observed_at = _timestamp(raw.get("observed_at"), f"observation.{name}.observed_at")
                last_success_at = _timestamp(raw.get("last_success_at"), f"observation.{name}.last_success_at")
            except PanoramaSourceError:
                continue
            if observed_at > now or last_success_at > now or observed_at != last_success_at:
                continue
        state = "UNKNOWN"
        valid_last_good = (
            projected is not None
            and isinstance(source_digest, str)
            and len(source_digest) == 64
            and source_digest == _canonical_digest(projected)
            and (provenance_source_digest is None or provenance_source_digest == source_digest)
            and observed_at is not None
            and last_success_at == observed_at
            and (
                name != "launchd_health"
                or (
                    isinstance(raw.get("value"), Mapping)
                    and isinstance(provenance.get("registry_sha256"), str)
                    and len(provenance["registry_sha256"]) == 64
                    and provenance["registry_sha256"] == raw["value"].get("registry_sha256")
                )
            )
        )
        try:
            if isinstance(source_digest, str):
                int(source_digest, 16)
        except ValueError:
            valid_last_good = False
        if status == "OBSERVED" and valid_last_good and error_class is None:
            within_ttl = (now - observed_at).total_seconds() <= PANORAMA_MAX_AGE_SECONDS
            state = (
                "PARTIAL" if name == "launchd_health" and projected.get("facet_state") == "PARTIAL"
                else "LIVE" if within_ttl else "STALE"
            ) if within_ttl else "STALE"
        elif status == "STALE" and valid_last_good and isinstance(error_class, str) and error_class:
            state = "PARTIAL" if (now - observed_at).total_seconds() <= PANORAMA_MAX_AGE_SECONDS else "STALE"
        elif status == "UNKNOWN" and raw.get("value") is None and source_digest is None and observed_at is None and last_success_at is None and isinstance(error_class, str) and error_class:
            state = "UNKNOWN"
        else:
            status = "UNKNOWN"
        if state == "UNKNOWN":
            source_digest = None
            projected = None
            observed_at = None
            last_success_at = None
            if not isinstance(error_class, str) or not error_class:
                error_class = "invalid_observation"
        projected_meta[name] = {
            "state": state,
            "observation_status": status,
            "observed_at": _iso(observed_at) if observed_at else None,
            "last_attempt_at": _iso(last_attempt_at),
            "last_success_at": _iso(last_success_at) if last_success_at else None,
            "error_class": error_class if isinstance(error_class, str) else None,
            "source_digest": source_digest,
            "value": projected if state in {"LIVE", "PARTIAL", "STALE"} else None,
            "source_generation_id": None,
            "source_revision_id": None,
            "duration_ms": duration_ms,
            "overrun": overrun,
            "provenance": {
                "kind": provenance.get("kind"),
                "source_ref": source_ref,
                "collector_sha256": collector_sha256,
                "source_digest": source_digest,
                **({"registry_sha256": provenance["registry_sha256"]} if name == "launchd_health" else {}),
            },
        }
        if projected is None or observed_at is None or state in {"UNKNOWN", "STALE"}:
            continue
        result[name] = projected
        if name == "bos_verifier":
            preserved_alerts = [
                alert
                for alert in result.get("alerts", [])
                if isinstance(alert, Mapping) and alert.get("id") != "zhixing-bos-verifier-errors"
            ]
            result["alerts"] = [*preserved_alerts, *_compact_alerts(projected, _iso(observed_at))]
        if state == "LIVE" and name in partial_facets:
            partial_facets.remove(name)
        elif state != "LIVE" and name not in partial_facets:
            partial_facets.append(name)
    if projected_meta:
        result["source"]["facet_observations"] = {
            **result["source"].get("facet_observations", {}),
            **projected_meta,
        }
        result["source"]["observation_schema"] = PANORAMA_OBSERVATION_SCHEMA


def project_full_projection(
    projection: object,
    health: object,
    *,
    compact_binding: object = None,
    observation: object = None,
    now: datetime | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Project the full bound revision artifact when its reader is available."""
    now = now or _utc_now()
    fetched_at = fetched_at or _iso(now)
    health_data = _read_only_health(health, now)
    data = _mapping(projection, "projection")
    generated_at = _validate_generated_at(data, "projection", now)
    state, error = _freshness(generated_at, now)
    _validate_full_projection_binding(data, compact_binding, health_data)
    partial_facets: list[str] = list(UNVERIFIED_FACETS)
    result = _base_payload(generated_at=generated_at, fetched_at=fetched_at, health=health_data, kind="zhixing-bound-revision", url=PANORAMA_FULL_DATA_URL, state=state, error=error, partial_facets=partial_facets)
    for field, projector in (
        ("alerts", _project_alerts),
        ("gates", _project_gates),
        ("knowledge_health", _project_knowledge_health),
        ("experience_graph", _project_experience_graph),
        ("connectors", _project_connectors),
    ):
        _project_field_if_proven(
            result, data, field, projector, revision_id=health_data["state_revision"],
            now=now, partial_facets=partial_facets,
        )
    visibility = _project_agent_visibility(data.get("agent_visibility"))
    generation_id = data.get("generation_id")
    if (
        visibility is not None
        and isinstance(generation_id, str)
        and visibility.get("generation_id") == generation_id
        and visibility.get("generated_at") == _iso(generated_at)
    ):
        source_digest = _canonical_digest(visibility)
        visibility_state = (
            "LIVE"
            if (now - generated_at).total_seconds() <= AGENT_VISIBILITY_MAX_AGE_SECONDS
            else "STALE"
        )
        observed_at = _iso(generated_at)
        result["agent_visibility"] = visibility
        result["source"].setdefault("generation_id", generation_id)
        result["source"]["facet_observations"] = {
            "agent_visibility": {
                "state": visibility_state,
                "observation_status": "OBSERVED",
                "observed_at": observed_at,
                "last_attempt_at": observed_at,
                "last_success_at": observed_at,
                "duration_ms": None,
                "overrun": False,
                "error_class": None,
                "source_digest": source_digest,
                "source_generation_id": generation_id,
                "source_revision_id": health_data["state_revision"],
                "value": visibility,
                "provenance": {
                    "kind": "projection-derived",
                    "source_ref": "collect_agent_visibility",
                    "collector_sha256": _current_observation_collector_digest(),
                    "source_digest": source_digest,
                },
            }
        }
        if visibility_state == "LIVE" and "agent_visibility" in partial_facets:
            partial_facets.remove("agent_visibility")
        elif "agent_visibility" not in partial_facets:
            partial_facets.append("agent_visibility")
    _apply_compact_observation(result, observation, now=now, partial_facets=partial_facets)
    return result


def _brief_gates(brief: object) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    health = _mapping(brief, "agent_brief").get("health")
    data = _mapping(health, "agent_brief.health")
    total, passed, failing = _number(data.get("gates_total")), _number(data.get("gates_pass")), data.get("gates_failing")
    if total is None or passed is None or not isinstance(failing, list) or any(not isinstance(item, str) for item in failing):
        raise PanoramaSourceError("schema_invalid:agent_brief.gate_summary")
    gates = {item["id"]: item for item in _unknown_gates()}
    for identifier in failing:
        if identifier in gates:
            gates[identifier] = {**gates[identifier], "verdict": "FAIL", "detail": "agent-brief gate summary lists this identifier as failing."}
    reference = data.get("reference_cell")
    if isinstance(reference, Mapping) and isinstance(reference.get("id"), str) and reference["id"] in gates and reference.get("verdict") in {"PASS", "FAIL", "WARN", "UNKNOWN"}:
        gates[reference["id"]] = {**gates[reference["id"]], "verdict": reference["verdict"], "detail": "agent-brief reference-cell verdict."}
    return list(gates.values()), {"total": total, "pass_count": passed, "failing_ids": list(failing), "source": PANORAMA_AGENT_BRIEF_URL}


def project_compact_projection(
    projection: object,
    brief: object,
    health: object,
    *,
    observation: object = None,
    now: datetime | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Project the compact fallback and agent brief without inventing gate detail."""
    now = now or _utc_now()
    fetched_at = fetched_at or _iso(now)
    health_data = _read_only_health(health, now)
    data = _mapping(projection, "compact_projection")
    generated_at = _validate_generated_at(data, "compact_projection", now)
    state, error = _freshness(generated_at, now)
    if _nonempty_string(data.get("source"), "compact_projection.source") != health_data["state_revision"]:
        raise PanoramaSourceError("projection_revision_mismatch")
    generation_id = _nonempty_string(data.get("generation_id"), "compact_projection.generation_id")
    brief_data = _mapping(brief, "agent_brief")
    if _validate_generated_at(brief_data, "agent_brief", now) != generated_at:
        raise PanoramaSourceError("projection_generation_mismatch")
    partial_facets: list[str] = list(UNVERIFIED_FACETS)
    if error == "field_provenance_partial":
        error = "bound_reader_unavailable"
    result = _base_payload(generated_at=generated_at, fetched_at=fetched_at, health=health_data, kind="zhixing-compact-fallback", url=PANORAMA_COMPACT_DATA_URL, state=state, error=error, partial_facets=partial_facets)
    result["source"].update({
        "generation_id": generation_id,
        "source_paths": {"full": PANORAMA_FULL_DATA_URL, "compact": PANORAMA_COMPACT_DATA_URL, "agent_brief": PANORAMA_AGENT_BRIEF_URL},
    })
    # The brief only shares a timestamp with this projection. Until it carries
    # exact revision/generation and per-field evidence, its gates stay UNKNOWN.
    _apply_compact_observation(result, observation, now=now, partial_facets=partial_facets)
    return result


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    declared_size = response.headers.get("content-length")
    if declared_size is not None:
        try:
            if int(declared_size) > max_bytes:
                raise PanoramaSourceError("response_too_large")
        except ValueError as exc:
            raise PanoramaSourceError("invalid_content_length") from exc
    chunks: list[bytes] = []
    received = 0
    async for chunk in response.aiter_bytes():
        received += len(chunk)
        if received > max_bytes:
            raise PanoramaSourceError("response_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _get_json(client: httpx.AsyncClient, url: str, *, max_bytes: int, compact_fallback: bool = False) -> object:
    async with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
        if response.status_code >= 400:
            if compact_fallback and response.status_code == 503:
                try:
                    body = json.loads(await _read_limited(response, PANORAMA_MAX_HEALTH_BYTES))
                except (PanoramaSourceError, UnicodeDecodeError, json.JSONDecodeError):
                    body = None
                if isinstance(body, Mapping) and body.get("error") == "agent_projection_unavailable":
                    raise FullProjectionUnavailableError("bound_reader_unavailable")
            response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if not content_type.lower().startswith("application/json"):
            raise PanoramaSourceError("invalid_content_type")
        raw = await _read_limited(response, max_bytes)
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PanoramaSourceError("invalid_json") from exc


async def fetch_panorama_projection(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    observation_path: Path = PANORAMA_OBSERVATION_PATH,
    now: datetime | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Prefer the full bound artifact; use compact only for its known 503 fault."""
    now = now or _utc_now()
    fetched_at = fetched_at or _iso(now)
    stage = "health"
    try:
        async with asyncio.timeout(PANORAMA_TOTAL_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=httpx.Timeout(PANORAMA_REQUEST_TIMEOUT_SECONDS), follow_redirects=False, transport=transport) as client:
                health = await _get_json(client, PANORAMA_HEALTH_URL, max_bytes=PANORAMA_MAX_HEALTH_BYTES)
                try:
                    stage = "full_projection"
                    full = await _get_json(client, PANORAMA_FULL_DATA_URL, max_bytes=PANORAMA_MAX_DATA_BYTES, compact_fallback=True)
                except FullProjectionUnavailableError:
                    stage = "compact_projection"
                    compact = await _get_json(client, PANORAMA_COMPACT_DATA_URL, max_bytes=PANORAMA_MAX_DATA_BYTES)
                    stage = "agent_brief"
                    brief = await _get_json(client, PANORAMA_AGENT_BRIEF_URL, max_bytes=PANORAMA_MAX_BRIEF_BYTES)
                    observation = _read_observation(observation_path)
                    return project_compact_projection(
                        compact,
                        brief,
                        health,
                        observation=observation,
                        now=now,
                        fetched_at=fetched_at,
                    )
                stage = "compact_binding"
                compact_binding = await _get_json(client, PANORAMA_COMPACT_DATA_URL, max_bytes=PANORAMA_MAX_DATA_BYTES)
        observation = _read_observation(observation_path)
        return project_full_projection(
            full,
            health,
            compact_binding=compact_binding,
            observation=observation,
            now=now,
            fetched_at=fetched_at,
        )
    except PanoramaSourceError as exc:
        return _unknown_payload(error=str(exc), fetched_at=fetched_at)
    except httpx.TimeoutException:
        return _unknown_payload(error=f"upstream_timeout:{stage}", fetched_at=fetched_at)
    except httpx.HTTPError as exc:
        return _unknown_payload(error=f"upstream_request_failed:{stage}:{type(exc).__name__}", fetched_at=fetched_at)
    except TimeoutError:
        return _unknown_payload(error=f"upstream_timeout:{stage}", fetched_at=fetched_at)
    except ValueError:
        return _unknown_payload(error="projection_validation_failed", fetched_at=fetched_at)
