"""Real-ledger public-boundary tests for the W2-05 personal draft slice."""

from __future__ import annotations

import json
from pathlib import Path

from agora.mcp import policy_enforcement
from agora.mcp.policy_enforcement import reset_pep_provider_cache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from omo.event_ledger import LedgerBroker
from omo.sovereignty import SovereigntyService

from cockpit.web import api_workflow_mesh_operations


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_workflow_mesh_operations.router)  # type: ignore[arg-type]
    return app


def _seed_role(ledger_path: Path) -> None:
    broker = LedgerBroker.connect(ledger_path)
    try:
        SovereigntyService(broker).assign(
            "principal:alice",
            "role:personal-steward",
            role_name="Personal Steward",
            scope="personal",
            responsibilities=["follow-up"],
        )
    finally:
        broker.close()


def _start_payload() -> dict[str, str]:
    return {
        "principal_id": "principal:alice",
        "role_id": "role:personal-steward",
        "responsibility_id": "responsibility:follow-up",
        "executor_id": "agent:personal-steward",
        "request_id": "follow-up-001",
        "summary": "Prepare the commitment follow-up",
        "why_now": "The family commitment needs review",
        "deadline": "2026-08-13",
    }


def _draft_payload(episode_id: str) -> dict[str, str]:
    return {
        "episode_id": episode_id,
        "principal_id": "principal:alice",
        "title": "Commitment follow-up draft",
        "context": "Summarise the next step for review.",
        "deadline": "2026-08-13",
        "next_action": "Review, edit, or discard the local draft.",
    }


def _configure_real_local_runtime(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    ledger_path = tmp_path / "event-ledger.sqlite3"
    draft_dir = tmp_path / "personal-drafts"
    monkeypatch.setenv("OMO_EVENT_LEDGER_DB", str(ledger_path))
    monkeypatch.setenv("PERSONAL_DRAFT_DIR", str(draft_dir))
    monkeypatch.setenv("AGORA_PEP_PROVIDER", "omo.sovereignty.enforcement:AgoraPepProvider")
    reset_pep_provider_cache()
    return ledger_path, draft_dir


def test_personal_episode_real_ledger_to_local_draft_to_feedback(monkeypatch, tmp_path):
    ledger_path, draft_dir = _configure_real_local_runtime(monkeypatch, tmp_path)
    _seed_role(ledger_path)
    client = TestClient(_app())

    started = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())
    assert started.status_code == 200
    episode_id = started.json()["episode"]["episode_id"]

    inbox = client.get("/api/workflow-mesh/episode-projections", params={"principal_id": "principal:alice"})
    assert inbox.status_code == 200
    assert inbox.json()["ok"] is True
    assert any(card["episode"] == episode_id for card in inbox.json()["projection"]["inbox"])

    confirmed = client.post(
        "/api/workflow-mesh/personal-episode/confirm",
        json={
            "episode_id": episode_id,
            "principal_id": "principal:alice",
            "executor_id": "agent:personal-steward",
            "human_confirmed": True,
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmation"]["mandate_id"].startswith("mandate:personal-")

    executed = client.post("/api/workflow-mesh/personal-episode/execute", json=_draft_payload(episode_id))
    assert executed.status_code == 200
    evidence_uri = executed.json()["evidence_uri"]
    assert evidence_uri.startswith("file://")
    artifacts = list(draft_dir.glob("*.json"))
    assert len(artifacts) == 1
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert artifact == {
        "title": "Commitment follow-up draft",
        "context": "Summarise the next step for review.",
        "deadline": "2026-08-13",
        "next_action": "Review, edit, or discard the local draft.",
        "never_send": True,
        "output_origin": "user_provided",
    }

    feedback = client.post(
        "/api/workflow-mesh/personal-episode/feedback",
        json={"episode_id": episode_id, "principal_id": "principal:alice", "verdict": "accept"},
    )
    assert feedback.status_code == 200

    projection = client.get("/api/workflow-mesh/episode-projections", params={"principal_id": "principal:alice"})
    assert projection.status_code == 200
    snapshot = projection.json()["projection"]
    episode = next(item for item in snapshot["episodes"] if item["episode_id"] == episode_id)
    member_payloads = [member["payload"] for member in episode["contains_event_refs"]]
    assert any(payload.get("evidence_uri") == evidence_uri for payload in member_payloads)
    assert any(payload.get("verdict") == "accept" for payload in member_payloads)
    assert snapshot["controls"]["ledger_unchanged"] is True
    assert snapshot["controls"]["chain_after"]["ok"] is True

    broker = LedgerBroker.connect(ledger_path)
    try:
        event_types = {row["event_type"] for row in broker.read(episode_id=episode_id)}
        assert {"Action.Started.v1", "Action.Succeeded.v1", "Evidence.LocalDraft.v1", "Outcome.Human.v1"} <= event_types
        assert broker.verify_chain()["ok"] is True
    finally:
        broker.close()


def test_personal_episode_execute_requires_confirmation_and_creates_no_file(monkeypatch, tmp_path):
    ledger_path, draft_dir = _configure_real_local_runtime(monkeypatch, tmp_path)
    _seed_role(ledger_path)
    client = TestClient(_app())
    started = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())
    episode_id = started.json()["episode"]["episode_id"]

    response = client.post("/api/workflow-mesh/personal-episode/execute", json=_draft_payload(episode_id))

    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert list(draft_dir.glob("*.json")) == [] if draft_dir.exists() else True


def test_personal_episode_repeated_start_uses_fresh_closed_request_brokers(monkeypatch, tmp_path):
    ledger_path, _draft_dir = _configure_real_local_runtime(monkeypatch, tmp_path)
    _seed_role(ledger_path)
    client = TestClient(_app())

    first = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())
    second = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())

    assert first.status_code == second.status_code == 200
    assert first.json()["episode"]["episode_id"] == second.json()["episode"]["episode_id"]
    assert second.json()["episode"]["reused"] is True


def test_personal_episode_missing_provider_binding_replaces_cached_none(monkeypatch, tmp_path):
    ledger_path, _draft_dir = _configure_real_local_runtime(monkeypatch, tmp_path)
    _seed_role(ledger_path)
    client = TestClient(_app())
    started = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())
    episode_id = started.json()["episode"]["episode_id"]
    confirmed = client.post(
        "/api/workflow-mesh/personal-episode/confirm",
        json={
            "episode_id": episode_id,
            "principal_id": "principal:alice",
            "executor_id": "agent:personal-steward",
            "human_confirmed": True,
        },
    )
    assert confirmed.status_code == 200

    monkeypatch.delenv("AGORA_PEP_PROVIDER")
    monkeypatch.setattr(policy_enforcement, "_provider_cache", None)
    executed = client.post("/api/workflow-mesh/personal-episode/execute", json=_draft_payload(episode_id))

    assert executed.status_code == 200
    assert executed.json()["ok"] is True
    assert policy_enforcement.get_pep_provider() is not None


def test_personal_episode_pep_failure_creates_no_file(monkeypatch, tmp_path):
    ledger_path, draft_dir = _configure_real_local_runtime(monkeypatch, tmp_path)
    _seed_role(ledger_path)
    client = TestClient(_app())
    started = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())
    episode_id = started.json()["episode"]["episode_id"]
    confirmed = client.post(
        "/api/workflow-mesh/personal-episode/confirm",
        json={
            "episode_id": episode_id,
            "principal_id": "principal:alice",
            "executor_id": "agent:personal-steward",
            "human_confirmed": True,
        },
    )
    assert confirmed.status_code == 200

    monkeypatch.setenv("AGORA_PEP_PROVIDER", "not.a.real.provider:Provider")
    reset_pep_provider_cache()
    response = client.post("/api/workflow-mesh/personal-episode/execute", json=_draft_payload(episode_id))

    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert list(draft_dir.glob("*.json")) == [] if draft_dir.exists() else True


# ── BET-Y1Q2-T2-02: setup, system draft, status ─────────────────────────


def _configure_runtime_no_seed(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Like _configure_real_local_runtime but does NOT seed the role."""
    ledger_path = tmp_path / "event-ledger.sqlite3"
    draft_dir = tmp_path / "personal-drafts"
    monkeypatch.setenv("OMO_EVENT_LEDGER_DB", str(ledger_path))
    monkeypatch.setenv("PERSONAL_DRAFT_DIR", str(draft_dir))
    monkeypatch.setenv("AGORA_PEP_PROVIDER", "omo.sovereignty.enforcement:AgoraPepProvider")
    reset_pep_provider_cache()
    return ledger_path, draft_dir


def _setup_payload() -> dict:
    return {
        "principal_id": "principal:alice",
        "role_id": "role:personal-steward",
        "role_name": "Personal Steward",
        "scope": "personal",
        "responsibilities": ["follow-up"],
    }


def test_personal_setup_creates_role_idempotent(monkeypatch, tmp_path):
    """POST /setup creates the assignment; a second call with same params is idempotent."""
    ledger_path, _ = _configure_runtime_no_seed(monkeypatch, tmp_path)
    client = TestClient(_app())

    first = client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload())
    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert first.json()["status"] == "assigned"

    broker = LedgerBroker.connect(ledger_path)
    try:
        events_before = broker.read()
        count_before = broker.count()
        tail_hash_before = events_before[-1]["event_hash"]
        assert broker.verify_chain()["ok"] is True
    finally:
        broker.close()

    second = client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload())
    assert second.status_code == 200
    assert second.json()["ok"] is True
    assert second.json()["status"] == "already_active"

    broker = LedgerBroker.connect(ledger_path)
    try:
        events_after = broker.read()
        assert broker.count() == count_before
        assert events_after[-1]["event_hash"] == tail_hash_before
        assert broker.verify_chain()["ok"] is True
    finally:
        broker.close()


def test_personal_setup_blocks_conflicting_scope(monkeypatch, tmp_path):
    """An already-active assignment with a different scope must not silently succeed."""
    _configure_runtime_no_seed(monkeypatch, tmp_path)
    client = TestClient(_app())

    client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload())

    conflict = _setup_payload()
    conflict["scope"] = "work"
    response = client.post("/api/workflow-mesh/personal-episode/setup", json=conflict)
    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert response.json()["error"] == "scope_conflict"


def test_personal_setup_blocks_conflicting_role_name(monkeypatch, tmp_path):
    """A different role_name on an active assignment is blocked."""
    _configure_runtime_no_seed(monkeypatch, tmp_path)
    client = TestClient(_app())

    client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload())

    conflict = _setup_payload()
    conflict["role_name"] = "Different Name"
    response = client.post("/api/workflow-mesh/personal-episode/setup", json=conflict)
    assert response.status_code == 409
    assert response.json()["error"] == "role_name_conflict"


def test_personal_setup_then_full_flow_user_provided(monkeypatch, tmp_path):
    """Setup → Start → Confirm → Execute (full draft) → output_origin=user_provided."""
    _configure_runtime_no_seed(monkeypatch, tmp_path)
    client = TestClient(_app())

    assert client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload()).status_code == 200

    started = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())
    assert started.status_code == 200
    episode_id = started.json()["episode"]["episode_id"]

    confirmed = client.post(
        "/api/workflow-mesh/personal-episode/confirm",
        json={
            "episode_id": episode_id,
            "principal_id": "principal:alice",
            "executor_id": "agent:personal-steward",
            "human_confirmed": True,
        },
    )
    assert confirmed.status_code == 200

    executed = client.post("/api/workflow-mesh/personal-episode/execute", json=_draft_payload(episode_id))
    assert executed.status_code == 200
    assert executed.json()["output_origin"] == "user_provided"


def test_personal_execute_system_draft_from_snapshot(monkeypatch, tmp_path):
    """Omitted draft fields → server builds from Episode snapshot, output_origin=system."""
    _, draft_dir = _configure_runtime_no_seed(monkeypatch, tmp_path)
    client = TestClient(_app())

    client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload())
    started = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())
    episode_id = started.json()["episode"]["episode_id"]
    client.post(
        "/api/workflow-mesh/personal-episode/confirm",
        json={
            "episode_id": episode_id,
            "principal_id": "principal:alice",
            "executor_id": "agent:personal-steward",
            "human_confirmed": True,
        },
    )

    executed = client.post(
        "/api/workflow-mesh/personal-episode/execute",
        json={"episode_id": episode_id, "principal_id": "principal:alice"},
    )
    assert executed.status_code == 200
    assert executed.json()["ok"] is True
    assert executed.json()["output_origin"] == "system"

    artifacts = list(draft_dir.glob("*.json"))
    assert len(artifacts) == 1
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert artifact["never_send"] is True
    assert artifact["output_origin"] == "system"
    assert artifact["title"] == "Prepare the commitment follow-up"


def test_personal_execute_partial_draft_rejected(monkeypatch, tmp_path):
    """Partial draft fields (some but not all) are rejected — all-or-nothing."""
    _configure_runtime_no_seed(monkeypatch, tmp_path)
    client = TestClient(_app())

    client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload())
    started = client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())
    episode_id = started.json()["episode"]["episode_id"]
    client.post(
        "/api/workflow-mesh/personal-episode/confirm",
        json={
            "episode_id": episode_id,
            "principal_id": "principal:alice",
            "executor_id": "agent:personal-steward",
            "human_confirmed": True,
        },
    )

    response = client.post(
        "/api/workflow-mesh/personal-episode/execute",
        json={"episode_id": episode_id, "principal_id": "principal:alice", "title": "Partial"},
    )
    assert response.status_code == 409
    assert response.json()["ok"] is False
    assert response.json()["error"] == "invalid_request"


def test_personal_status_read_only_summary(monkeypatch, tmp_path):
    """GET /status returns a read-only summary with no side effects."""
    _configure_runtime_no_seed(monkeypatch, tmp_path)
    client = TestClient(_app())

    client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload())
    client.post("/api/workflow-mesh/personal-episode/start", json=_start_payload())

    status = client.get(
        "/api/workflow-mesh/personal-episode/status",
        params={"principal_id": "principal:alice"},
    )
    assert status.status_code == 200
    body = status.json()
    assert body["ok"] is True
    summary = body["summary"]
    assert summary["total_episodes"] >= 1
    assert summary["pending_confirmation"] >= 1
    assert body["controls"]["read_only"] is True
    assert body["controls"]["workflow_state_mutation"] is False


def test_personal_setup_ingest_system_draft_e2e(monkeypatch, tmp_path):
    """Setup → Ingest (local signal) → Confirm → System Draft works end-to-end."""
    import base64

    ledger_path = tmp_path / "event-ledger.sqlite3"
    signal_dir = tmp_path / "signals"
    signal_dir.mkdir(parents=True, exist_ok=True)
    draft_dir = tmp_path / "personal-drafts"
    monkeypatch.setenv("OMO_EVENT_LEDGER_DB", str(ledger_path))
    monkeypatch.setenv("PERSONAL_SIGNAL_DIR", str(signal_dir))
    monkeypatch.setenv("PERSONAL_DRAFT_DIR", str(draft_dir))
    monkeypatch.setenv("IRIS_LOCAL_FILES_DIRECTORY", str(signal_dir))
    monkeypatch.setenv("AGORA_PEP_PROVIDER", "omo.sovereignty.enforcement:AgoraPepProvider")
    reset_pep_provider_cache()

    note = signal_dir / "notes" / "follow-up.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntitle: Follow up with team\n---\n\nImportant.\n", encoding="utf-8")
    item_id = base64.urlsafe_b64encode(b"notes/follow-up.md").decode().rstrip("=")

    client = TestClient(_app())

    assert client.post("/api/workflow-mesh/personal-episode/setup", json=_setup_payload()).status_code == 200

    ingested = client.post(
        "/api/workflow-mesh/personal-signal/ingest",
        json={
            "item_id": item_id,
            "principal_id": "principal:alice",
            "role_id": "role:personal-steward",
            "responsibility_id": "responsibility:follow-up",
            "executor_id": "agent:personal-steward",
        },
    )
    assert ingested.status_code == 200
    episode_id = ingested.json()["episode"]["episode_id"]

    assert client.post(
        "/api/workflow-mesh/personal-episode/confirm",
        json={
            "episode_id": episode_id,
            "principal_id": "principal:alice",
            "executor_id": "agent:personal-steward",
            "human_confirmed": True,
        },
    ).status_code == 200

    executed = client.post(
        "/api/workflow-mesh/personal-episode/execute",
        json={"episode_id": episode_id, "principal_id": "principal:alice"},
    )
    assert executed.status_code == 200
    assert executed.json()["output_origin"] == "system"

    artifacts = list(draft_dir.glob("*.json"))
    assert len(artifacts) == 1
    artifact = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert artifact["title"] == "Follow up with team"
    assert artifact["never_send"] is True
    assert artifact["output_origin"] == "system"
    assert "Important." not in json.dumps(artifact)
