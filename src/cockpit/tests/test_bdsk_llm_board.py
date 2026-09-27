"""bdsk evaluate --llm: LLM 四角董事会接入(bdsk_engine 此前无任何 CLI 调用方)。"""

from __future__ import annotations

import argparse
import json

from cockpit.commands import bdsk, bdsk_engine

PROVEN = {
    "status": "ok",
    "proof_state": "proven",
    "persona_uri": "bos://persona/bdsk/evaluate",
    "compute_uri": "bos://compute/aetherforge/infer",
    "verdict": "PROCEED_WITH_GUARDRAILS",
    "risk_score": 45,
    "conclusion": "加可观测性",
    "builder": "b",
    "devil": "d",
    "sage": "s",
    "keeper": "k",
}


def test_llm_board_flattens_spec_and_keeps_stdout_pure_json(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake(topic, *, context="", mode="deep"):
        seen.update(topic=topic, context=context)
        return PROVEN

    monkeypatch.setattr(bdsk_engine.DynamicBDSKAdjudicator, "adjudicate", staticmethod(fake))
    spec = tmp_path / "spec.md"
    spec.write_text("# 方案: 超时调到 300s\n- 冷加载 504\n- 风险: 等待更久\n", encoding="utf-8")
    out = tmp_path / "madr.md"
    args = argparse.Namespace(spec=str(spec), demo=False, out=str(out), json=True, llm=True)
    assert bdsk.cmd_bdsk_evaluate(args) == 0

    # persona 隐私闸拒绝控制字符与 " /" 路径样式: 必须是单行且不含 " /"
    assert seen["topic"] == "方案: 超时调到 300s"
    assert "\n" not in seen["context"] and " /" not in seen["context"]
    # --out 的状态提示不得污染 stdout 上的 JSON
    data = json.loads(capsys.readouterr().out)
    assert data["llm_board"]["verdict"] == "PROCEED_WITH_GUARDRAILS"
    assert "LLM 四角董事会" in out.read_text(encoding="utf-8")


def test_llm_board_not_proven_is_reported_honestly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        bdsk_engine.DynamicBDSKAdjudicator,
        "adjudicate",
        staticmethod(lambda topic, **kw: bdsk_engine._not_proven("persona_route_unavailable")),
    )
    out = tmp_path / "madr.md"
    args = argparse.Namespace(spec=None, demo=True, out=str(out), json=True, llm=True)
    assert bdsk.cmd_bdsk_evaluate(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["llm_board"]["proof_state"] == "not_proven"
    assert "NOT_PROVEN" in out.read_text(encoding="utf-8")
