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
    assert rc != 0
    assert "未执行" in text
    for claim in ("已生成", "已装载至模型上下文", "策略证明"):
        assert claim not in text
