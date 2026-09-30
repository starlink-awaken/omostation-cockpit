"""cartridge run 不能宣称做了没做的事(全链路场景实测: 无入口脚本时 sleep 后打印「策略证明/审计凭证已生成」)。"""

from __future__ import annotations

import json
from pathlib import Path

from cockpit.commands.cartridge_ops import pack_cartridge, run_cartridge


def test_run_without_entrypoint_reports_honestly(tmp_path: Path, capsys) -> None:
    src = tmp_path / "domain"
    (src / "rules").mkdir(parents=True)
    (src / "manifest.json").write_text(json.dumps({"cartridge_id": "t", "name": "t"}), encoding="utf-8")
    (src / "rules" / "p.yaml").write_text("rule_id: X\n", encoding="utf-8")
    out = tmp_path / "t.cartridge"
    assert pack_cartridge(str(src), str(out)) == 0
    capsys.readouterr()  # 丢掉打包阶段的输出, 只看运行阶段

    rc = run_cartridge(str(out), "立项论证", tmp_path)
    text = capsys.readouterr().out
    # 无规则的卡带: 策略评估零条规则 → 放行; 不得再出现"已装载/策略证明已生成"式空转话术
    assert rc == 0
    assert "无规则" in text or "0 条规则" in text or "全部通过" in text
    for claim in ("已装载至模型上下文", "策略证明", "审计凭证"):
        assert claim not in text


def test_pack_does_not_modify_source_manifest(tmp_path: Path) -> None:
    """打包只把签名写进产物, 源目录 manifest.json 原样保留(此前被整体覆盖, 策略规则丢失)。"""
    import zipfile

    src = tmp_path / "domain"
    src.mkdir()
    original = {"cartridge_id": "c1", "policy_rules": ["RULE-1: 预算超 50 万须专家论证"]}
    (src / "manifest.json").write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    (src / "rule.md").write_text("x", encoding="utf-8")
    out = tmp_path / "c.cartridge"
    assert pack_cartridge(str(src), str(out)) == 0

    assert json.loads((src / "manifest.json").read_text(encoding="utf-8")) == original
    packed = json.loads(zipfile.ZipFile(out).read("manifest.json"))
    assert packed["cartridge_id"] == "c1" and packed["policy_rules"] == original["policy_rules"]
    assert packed["signature"]


def test_policy_evaluator_semantics():
    """受限求值器: 白名单 AST + action 根解析 + 保守失败。"""
    from cockpit.commands.cartridge_policy import evaluate_constraint

    assert evaluate_constraint("action.args.budget_cny <= 500000 or action.args.has_expert_review == true",
                               {"args": {"budget_cny": 12000000, "has_expert_review": True}})
    assert not evaluate_constraint("action.args.budget_cny <= 500000 or action.args.has_expert_review == true",
                                   {"args": {"budget_cny": 12000000}})
    assert not evaluate_constraint("action.args.budget_cny <= 500000", {"args": {}})  # None 比较 → 保守 False
    assert evaluate_constraint("not (contains(action.uri, 'public-cloud') and not action.args.is_sanitized)",
                               {"uri": "bos://work/local", "args": {}})
    assert not evaluate_constraint('__import__("os").system("x")', {})  # 注入被拒
    assert not evaluate_constraint("action.args.x", {"args": {"x": False}})


def test_run_blocks_on_high_severity(tmp_path: Path, capsys) -> None:
    """HIGH/CRITICAL 未通过 → 阻断(exit 3); 规则全过 → 0。此前无入口脚本时只做完整性校验(空转)。"""
    import yaml

    src = tmp_path / "domain"
    (src / "rules").mkdir(parents=True)
    (src / "manifest.json").write_text(json.dumps({"cartridge_id": "t", "domain": "t"}), encoding="utf-8")
    (src / "rules" / "p.yaml").write_text(yaml.safe_dump({
        "policies": [{"id": "R1", "name": "预算门禁", "severity": "HIGH",
                      "constraint": "action.args.budget_cny <= 500000",
                      "message": "预算超 50 万须专家论证"}]
    }), encoding="utf-8")
    out = tmp_path / "t.cartridge"
    from cockpit.commands.cartridge_ops import pack_cartridge, run_cartridge

    assert pack_cartridge(str(src), str(out)) == 0
    capsys.readouterr()
    import cockpit.commands.cartridge_ops as ops

    ops._extract_args_llm = lambda intent, fields: {"budget_cny": 12000000}  # 不依赖网关
    assert run_cartridge(str(out), "预算 1200 万的立项", tmp_path) == 3
    assert "阻断" in capsys.readouterr().out
    ops._extract_args_llm = lambda intent, fields: {"budget_cny": 300000}
    assert run_cartridge(str(out), "30 万采购", tmp_path) == 0
